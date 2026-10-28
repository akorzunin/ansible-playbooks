"""Local readiness/abort evidence only; no launch, gate release or worker signals."""

import errno
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import stat
import time

ARTIFACTS = ('manifest.json', 'events.jsonl', 'summary.json', 'SUMMARY.md')
EVENTS = {'run-start', 'preflight', 'request-start', 'progress', 'request-end',
          'host-sample', 'route-evidence', 'run-end'}
REPORT_RESERVE = 8192


class UnsafeFile(ValueError):
    pass


def directory(path):
    """Open every component without following symlinks, including ancestors."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise UnsafeFile('absolute-nonsymlink-path-required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        return fd
    except BaseException:
        os.close(fd)
        raise


def regular(parent, name):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise UnsafeFile('single-link-regular-file-required')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)):
        os.close(fd)
        raise UnsafeFile('single-link-regular-file-required')
    return fd


def error_code(error):
    if isinstance(error, PermissionError):
        return 'permission-error'
    if isinstance(error, UnsafeFile) or getattr(error, 'errno', None) in (errno.ELOOP, errno.ENOTDIR):
        return 'unsafe-file'
    return 'read-error'


def record(line, expected):
    try:
        row = json.loads(line)
    except (ValueError, UnicodeError, RecursionError):
        return 'malformed-json', None
    if (not isinstance(row, dict) or type(row.get('schema_version')) is not int
            or row['schema_version'] != 1 or not isinstance(row.get('event'), str)
            or row['event'] not in EVENTS
            or any(row.get(k) != v for k, v in expected.items())
            or not isinstance(row.get('utc'), str) or not row['utc']
            or type(row.get('elapsed_s')) not in (int, float)
            or not 0 <= row['elapsed_s'] <= 660 or not math.isfinite(row['elapsed_s'])):
        return 'wrong-schema', None
    if row['event'] == 'run-end':
        return 'worker-ended', None
    if 'ready' in row and type(row['ready']) is not bool:
        return 'wrong-schema', None
    if row['event'] != 'route-evidence' or row.get('ready') is not True:
        return 'non-ready', None
    if (any(type(row.get(k)) is not int or row[k] < minimum
            for k, minimum in (('pid', 2), ('uid', 1), ('gid', 1)))
            or not isinstance(row.get('groups'), list)
            or not all(type(g) is int and g >= 0 for g in row['groups'])
            or not isinstance(row.get('network_namespace'), str)
            or not re.fullmatch(r'net:\[[0-9]+\]', row['network_namespace'])
            or row.get('stage') != 'route' or row.get('outcome') != 'route-unverified'
            or row.get('underlay') != 'unverified'):
        return 'wrong-schema', None
    return 'ready-candidate', {k: row[k] for k in ('pid', 'uid', 'gid', 'groups', 'network_namespace')}


def poll_ready(path, alive, expected, *, timeout=10, interval=.05, max_polls=200,
               max_bytes=1048576, clock=time.monotonic, sleep=time.sleep):
    """Candidate only. alive checks this attempt's Python/unit, NOT launcher success.

    Local regular files only: deadlines are cooperative around filesystem calls;
    a stalled filesystem needs an outer controller deadline, not longer gate waits.
    """
    if (not 0 < timeout <= 30 or not 0 < interval <= 1 or not 1 <= max_polls <= 600
            or not 1 <= max_bytes <= 1048576
            or set(expected) != {'run', 'route', 'endpoint'}
            or not all(isinstance(v, str) and v for v in expected.values())):
        raise ValueError('invalid-poll-bounds-or-identity')
    end = clock() + timeout
    offset, tail, identity, prior_size = 0, b'', None, 0
    non_ready, polls, pending = 0, 0, 'missing'

    def result(status, candidate=None):
        return {'status': status, 'candidate': candidate, 'polls': polls,
                'bytes_read': offset, 'tail_bytes': len(tail),
                'non_ready_records': non_ready, 'pending': pending}

    def running():
        value = alive()
        if type(value) is not bool:
            raise ValueError('liveness-must-be-explicit')
        return value

    for polls in range(1, max_polls + 1):
        if clock() >= end:
            return result('timeout')
        try:
            if not running():
                return result('early-exit')
        except (OSError, ValueError, RuntimeError):
            return result('process-error')
        parent = fd = None
        candidate = None
        try:
            parent = directory(Path(path).parent)
            fd = regular(parent, Path(path).name)
            info = os.fstat(fd)
            current = (info.st_dev, info.st_ino)
            if identity is not None and current != identity:
                return result('replaced')
            if info.st_size < prior_size:
                return result('truncated')
            identity, prior_size = current, info.st_size
            if info.st_size > max_bytes:
                return result('byte-limit')
            os.lseek(fd, offset, os.SEEK_SET)
            while offset < info.st_size:
                if clock() >= end:
                    return result('timeout')
                chunk = os.read(fd, min(65536, info.st_size - offset))
                if not chunk:
                    return result('truncated')
                offset += len(chunk)
                tail += chunk
                lines = tail.split(b'\n')
                tail = lines.pop()
                for line in lines:
                    if not line.strip():
                        continue
                    status, value = record(line, expected)
                    if status == 'non-ready':
                        non_ready += 1
                    elif status == 'ready-candidate':
                        if candidate is not None:
                            return result('wrong-schema')
                        candidate = value
                    else:
                        return result(status)
            pending = 'partial' if tail.strip() else ('empty' if offset == 0 else 'blank-or-non-ready')
        except FileNotFoundError:
            if identity is not None:
                return result('disappeared')
            pending = 'missing'
        except (OSError, UnsafeFile) as error:
            return result(error_code(error))
        finally:
            if fd is not None:
                os.close(fd)
            if parent is not None:
                os.close(parent)
        try:
            if not running():
                return result('early-exit')
        except (OSError, ValueError, RuntimeError):
            return result('process-error')
        if clock() >= end:
            return result('timeout')
        if candidate is not None:
            return result('ready-candidate', candidate)
        sleep(min(interval, max(0, end - clock())))
    return result('poll-limit')


def save_report(dest, report):
    data = (json.dumps(report, sort_keys=True) + '\n').encode()
    if len(data) > REPORT_RESERVE // 2:
        raise ValueError('report-limit')
    fd = os.open('collection.tmp', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=dest)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.rename('collection.tmp', 'collection.json', src_dir_fd=dest, dst_dir_fd=dest)


def copy_artifacts(source, dest, report, file_limit, total_limit):
    """Child-only copier. Parent enforces time; sizes include metadata reserve."""
    used = 0
    try:
        src = directory(source)
    except (OSError, UnsafeFile) as error:
        report['status'] = 'source-missing' if isinstance(error, FileNotFoundError) else error_code(error)
        save_report(dest, report)
        return
    try:
        for name in ARTIFACTS:
            entry = report['files'][name]
            fd = None
            operation = 'read'
            try:
                fd = regular(src, name)
                before = os.fstat(fd)
                limit = min(before.st_size, file_limit, total_limit - REPORT_RESERVE - used)
                # Conservative reservation, no failure refunds; track actual writes if salvage needs more room.
                used += limit
                operation = 'write'
                out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=dest)
                with os.fdopen(out, 'wb') as stream:
                    while entry['bytes'] < limit:
                        operation = 'read'
                        chunk = os.read(fd, min(65536, limit - entry['bytes']))
                        operation = 'write'
                        if not chunk:
                            break
                        stream.write(chunk)
                        entry['bytes'] += len(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                operation = 'read'
                after = os.fstat(fd)
                linked = os.stat(name, dir_fd=src, follow_symlinks=False)
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino) != (
                        after.st_size, after.st_mtime_ns, after.st_ctime_ns, linked.st_ino):
                    entry['status'] = 'changed-during-copy'
                elif entry['bytes'] < before.st_size:
                    entry['status'] = 'partial-limit' if entry['bytes'] == limit else 'partial-eof'
                else:
                    entry['status'] = 'copied-snapshot'
            except FileNotFoundError:
                entry['status'] = ('write-error' if operation == 'write' else
                                   'partial-disappeared' if fd is not None else 'missing')
            except (OSError, UnsafeFile) as error:
                entry['status'] = 'write-error' if operation == 'write' else error_code(error)
                try:
                    entry['bytes'] = os.stat(name, dir_fd=dest, follow_symlinks=False).st_size
                except FileNotFoundError:
                    pass
            finally:
                if fd is not None:
                    os.close(fd)
            save_report(dest, report)
        report['status'] = 'collected' if all(
            e['status'] == 'copied-snapshot' for e in report['files'].values()) else 'incomplete'
        save_report(dest, report)
    finally:
        os.close(src)


def copy_child(*args):
    try:
        copy_artifacts(*args)
    except BaseException:
        raise SystemExit(1) from None  # Parent records collector-error; no raw child traceback.


def collect_artifacts(source, destination, *, timeout=5, file_limit=1048576, total_limit=4202496):
    """New private destination; bounded child copies only ARTIFACTS, never credentials.

    Linux/local-filesystem ceiling: a kernel-uninterruptible IO cannot be reaped on
    a deadline. Use only reviewed local runtime/output mounts, not remote/FUSE IO.
    """
    if not 0 < timeout <= 5 or not 0 < file_limit <= 1048576 or not REPORT_RESERVE < total_limit <= 4202496:
        raise ValueError('invalid-collection-bounds')
    report = {'status': 'collecting', 'snapshot_only': True, 'worker_complete': 'unknown',
              'files': {name: {'status': 'not-collected', 'bytes': 0} for name in ARTIFACTS}}
    parent = directory(Path(destination).parent)
    dest = None
    child = None
    try:
        # Caller selects a trusted controller parent; never collect into worker state.
        info = os.fstat(parent)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
            raise UnsafeFile('controller-owned-private-destination-parent-required')
        os.mkdir(Path(destination).name, mode=0o700, dir_fd=parent)
        dest = os.open(Path(destination).name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        save_report(dest, report)
        child = multiprocessing.get_context('fork').Process(
            target=copy_child, args=(source, dest, report, file_limit, total_limit))
        child.start()
        child.join(timeout)
        timed_out = child.is_alive()
        if timed_out:
            child.kill()  # Only this helper's child, never a worker/candidate PID.
            child.join(.2)
        fd = regular(dest, 'collection.json')
        with os.fdopen(fd, 'rb') as stream:
            report = json.loads(stream.read(REPORT_RESERVE))
        if timed_out or child.exitcode != 0:
            report['status'] = 'collection-timeout' if timed_out else 'collector-error'
            for name, entry in report['files'].items():
                if entry['status'] == 'not-collected':
                    try:
                        entry['bytes'] = os.stat(name, dir_fd=dest, follow_symlinks=False).st_size
                        entry['status'] = 'partial-unknown'
                    except FileNotFoundError:
                        pass
        # A killed child may have left a bounded report temp; never follow it.
        try:
            os.unlink('collection.tmp', dir_fd=dest)
        except FileNotFoundError:
            pass
        save_report(dest, report)
        return report
    finally:
        if child is not None:
            if child.pid is not None and child.is_alive():
                child.kill()
                child.join(.2)
            if child.pid is None or not child.is_alive():
                child.close()
        if dest is not None:
            os.close(dest)
        os.close(parent)


def collect_before_teardown(source, destination, teardown, **bounds):
    """Use on EVERY exit path, inside the separate endpoint-teardown finally.

    No cancellation authority here: controller may first gracefully cancel an
    independently verified owned Python worker, within the existing hold/deadline.
    Collection exceptions/cancellation propagate, but cannot skip own teardown.
    """
    try:
        return collect_artifacts(source, destination, **bounds)
    finally:
        teardown()
