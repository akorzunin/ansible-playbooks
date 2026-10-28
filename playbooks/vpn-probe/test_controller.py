import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('controller', Path(__file__).with_name('controller.py'))
ctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctl)

IDENTITY = {'run': 'offline', 'route': 'cherry-vless', 'endpoint': 'reference-on-vpn'}
READY = IDENTITY | {'schema_version': 1, 'event': 'route-evidence', 'utc': '2026-10-27T00:00:00Z',
                    'elapsed_s': .01, 'ready': True, 'pid': 12345, 'uid': 64001, 'gid': 64001,
                    'groups': [64001], 'network_namespace': 'net:[123]', 'underlay': 'unverified',
                    'stage': 'route', 'outcome': 'route-unverified'}


def line(row=READY):
    return json.dumps(row).encode() + b'\n'


class Clock:
    def __init__(self, action=lambda n: None):
        self.now = 0
        self.poll = 0
        self.action = action

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.poll += 1
        self.action(self.poll)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'runtime'
        self.source.mkdir(mode=0o700)
        self.events = self.source / 'events.jsonl'
        self.dest = self.root / 'evidence'
        # These regressions must never send packets, launch units, or release a gate.
        self.network = patch('socket.socket', side_effect=AssertionError('no sockets'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.assertFalse, (self.root / 'go').exists())

    def poll(self, *, action=lambda n: None, alive=lambda: True, **bounds):
        clock = Clock(action)
        return ctl.poll_ready(self.events, alive, IDENTITY, clock=clock, sleep=clock.sleep,
                              **({'timeout': 1, 'interval': .1, 'max_polls': 20} | bounds))

    def artifacts(self):
        for name in ctl.ARTIFACTS:
            (self.source / name).write_bytes(b'partial worker evidence\n')
        # Never export these, even when the source is otherwise empty/partial.
        for name in ('core.json', 'worker.json', 'ca.pem', 'handoff', 'private.key'):
            (self.source / name).write_bytes(b'SECRET_SENTINEL')

    def test_missing_empty_whitespace_and_partial_are_pending(self):
        for data, pending in ((None, 'missing'), (b'', 'empty'), (b' \n\t\n', 'blank-or-non-ready'),
                              (b'  ', 'blank-or-non-ready'), (b'{"schema_version":', 'partial')):
            with self.subTest(data=data):
                self.events.unlink(missing_ok=True)
                if data is not None:
                    self.events.write_bytes(data)
                with patch.object(ctl.json, 'loads', wraps=json.loads) as loads:
                    result = self.poll()
                self.assertEqual(result['status'], 'timeout')
                self.assertEqual(result['pending'], pending)
                loads.assert_not_called()
                self.assertIsNone(result['candidate'])

    def test_delayed_creation_and_ready_split_across_writes(self):
        data = line()

        def writes(n):
            if n == 1:
                self.events.write_bytes(b'')
            elif n == 2:
                self.events.write_bytes(b'\n ' + data[:25])
            elif n == 3:
                with self.events.open('ab') as stream:
                    stream.write(data[25:-1])
            elif n == 4:
                with self.events.open('ab') as stream:
                    stream.write(b'\n')

        result = self.poll(action=writes)
        self.assertEqual(result['status'], 'ready-candidate')
        self.assertEqual(result['polls'], 5)
        self.assertEqual(result['candidate']['pid'], READY['pid'])
        self.assertEqual(result['bytes_read'], len(data) + 2)
        self.assertEqual(result['tail_bytes'], 0)

    def test_complete_records_consumed_once_and_partial_tail_kept(self):
        other = READY | {'event': 'run-start'}
        self.events.write_bytes(b'\n' + line(other) + b'{')
        result = self.poll()
        self.assertEqual(result['non_ready_records'], 1)
        self.assertEqual(result['tail_bytes'], 1)
        self.assertEqual(result['pending'], 'partial')
        self.assertEqual(result['status'], 'timeout')

    def test_complete_bad_json_and_wrong_schema_are_not_pending(self):
        rows = [(b'{bad}\n', 'malformed-json'), (b'\xff\n', 'malformed-json'),
                (b'[]\n', 'wrong-schema'), (line(READY | {'schema_version': True}), 'wrong-schema'),
                (line(READY | {'event': []}), 'wrong-schema'),
                (line(READY | {'elapsed_s': float('nan')}), 'wrong-schema'),
                (line(READY | {'run': 'other'}), 'wrong-schema'),
                (line(READY | {'pid': True}), 'wrong-schema'),
                (line(READY | {'network_namespace': 'guessed'}), 'wrong-schema'),
                (line(READY | {'uid': 0}), 'wrong-schema')]
        for data, expected in rows:
            with self.subTest(data=data):
                self.events.write_bytes(data)
                self.assertEqual(self.poll()['status'], expected)

    def test_late_bad_record_or_run_end_does_not_hide_behind_ready(self):
        for data, status in ((b'{bad}\n', 'malformed-json'),
                             (line(READY | {'event': 'run-end'}), 'worker-ended'),
                             (line(), 'wrong-schema')):
            self.events.write_bytes(line() + data)
            result = self.poll()
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['candidate'])

    def test_early_exit_before_and_after_read_and_process_check_error(self):
        self.events.write_bytes(line())
        self.assertEqual(self.poll(alive=lambda: False)['status'], 'early-exit')
        answers = iter([True, False])
        self.assertEqual(self.poll(alive=lambda: next(answers))['status'], 'early-exit')
        for error in (PermissionError('PRIVATE_SENTINEL'), RuntimeError('PRIVATE_SENTINEL')):
            with patch.object(ctl, 'record', side_effect=AssertionError('must not parse')):
                with patch.object(ctl, 'time'):
                    def broken():
                        raise error
                    result = self.poll(alive=broken)
            self.assertEqual(result['status'], 'process-error')
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertEqual(self.poll(alive=lambda: None)['status'], 'process-error')

    def test_unit_terminal_event_while_wrapper_still_alive(self):
        self.events.write_bytes(line(READY | {'event': 'run-end'}))
        self.assertEqual(self.poll()['status'], 'worker-ended')

    def test_permission_and_read_failures_are_distinct_from_missing(self):
        for error, status in ((PermissionError('SECRET'), 'permission-error'),
                              (OSError('SECRET'), 'read-error')):
            with patch.object(ctl, 'regular', side_effect=error):
                result = self.poll()
            self.assertEqual(result['status'], status)
            self.assertNotIn('SECRET', json.dumps(result))

    def test_truncation_replacement_and_disappearance(self):
        for change, status in (
                (lambda: self.events.write_bytes(b''), 'truncated'),
                (lambda: (self.events.unlink(), self.events.write_bytes(b'new')), 'replaced'),
                (lambda: self.events.unlink(), 'disappeared')):
            self.events.write_bytes(b'{"partial":')
            # Keep the old inode allocated so replacement is deterministic.
            with self.events.open('rb'):
                result = self.poll(action=lambda n: change() if n == 1 else None)
            self.assertEqual(result['status'], status)

    def test_byte_and_poll_limits(self):
        self.events.write_bytes(b' ' * 32)
        self.assertEqual(self.poll(max_bytes=16)['status'], 'byte-limit')
        self.assertEqual(self.poll(max_polls=1)['status'], 'poll-limit')
        with self.assertRaises(ValueError):
            self.poll(timeout=31)

    def test_refuse_symlinks_fifo_directory_and_hardlinks(self):
        target = self.root / 'target'
        target.write_bytes(line())
        for kind in ('symlink', 'fifo', 'directory', 'hardlink'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    self.events.symlink_to(target)
                elif kind == 'fifo':
                    os.mkfifo(self.events)
                elif kind == 'directory':
                    self.events.mkdir()
                else:
                    os.link(target, self.events)
                self.assertEqual(self.poll()['status'], 'unsafe-file')
                if kind == 'directory':
                    self.events.rmdir()
                else:
                    self.events.unlink()
        link = self.root / 'linked-runtime'
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(OSError):
            ctl.directory(link)

    def test_collection_allowlist_modes_no_invented_worker_outcome(self):
        self.artifacts()
        report = ctl.collect_artifacts(self.source, self.dest)
        self.assertEqual(report['status'], 'collected')
        self.assertEqual(report['worker_complete'], 'unknown')
        self.assertTrue(report['snapshot_only'])
        self.assertEqual(set(p.name for p in self.dest.iterdir()), set(ctl.ARTIFACTS) | {'collection.json'})
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o700)
        for path in self.dest.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn(b'SECRET_SENTINEL', path.read_bytes())
        self.assertEqual(json.loads((self.dest / 'collection.json').read_bytes()), report)

    def test_missing_and_no_terminal_files_remain_missing(self):
        self.events.write_bytes(b'{unfinished JSONL')
        report = ctl.collect_artifacts(self.source, self.dest)
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual((self.dest / 'events.jsonl').read_bytes(), b'{unfinished JSONL')
        for name in ('manifest.json', 'summary.json', 'SUMMARY.md'):
            self.assertEqual(report['files'][name]['status'], 'missing')
            self.assertFalse((self.dest / name).exists())
        self.assertEqual(report['worker_complete'], 'unknown')

    def test_collection_file_total_and_report_disk_bounds(self):
        for name in ctl.ARTIFACTS:
            (self.source / name).write_bytes(b'x' * 50)
        report = ctl.collect_artifacts(self.source, self.dest, file_limit=40,
                                       total_limit=ctl.REPORT_RESERVE + 65)
        self.assertEqual(sum(e['bytes'] for e in report['files'].values()), 65)
        self.assertEqual([report['files'][name]['bytes'] for name in ctl.ARTIFACTS], [40, 25, 0, 0])
        self.assertTrue(all(e['status'] == 'partial-limit' for e in report['files'].values()))
        self.assertLessEqual(sum(p.stat().st_size for p in self.dest.iterdir()), ctl.REPORT_RESERVE + 65)

    def test_collection_refuses_nonregular_and_ancestor_symlinks(self):
        outside = self.root / 'private'
        outside.write_bytes(b'SECRET_SENTINEL')
        (self.source / 'manifest.json').symlink_to(outside)
        os.mkfifo(self.events)
        (self.source / 'summary.json').mkdir()
        os.link(outside, self.source / 'SUMMARY.md')
        report = ctl.collect_artifacts(self.source, self.dest)
        self.assertTrue(all(e['status'] == 'unsafe-file' for e in report['files'].values()))
        self.assertEqual(set(p.name for p in self.dest.iterdir()), {'collection.json'})
        link = self.root / 'source-link'
        link.symlink_to(self.source, target_is_directory=True)
        result = ctl.collect_artifacts(link, self.root / 'second')
        self.assertEqual(result['status'], 'unsafe-file')

    def test_existing_or_public_destination_rejected_without_overwrite(self):
        self.dest.mkdir()
        marker = self.dest / 'keep'
        marker.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            ctl.collect_artifacts(self.source, self.dest)
        self.assertEqual(marker.read_bytes(), b'keep')
        os.chmod(self.root, 0o755)
        try:
            with self.assertRaises(ctl.UnsafeFile):
                ctl.collect_artifacts(self.source, self.root / 'new')
        finally:
            os.chmod(self.root, 0o700)

    def test_source_already_removed_is_explicit_evidence_loss(self):
        self.source.rmdir()
        report = ctl.collect_artifacts(self.source, self.dest)
        self.assertEqual(report['status'], 'source-missing')
        self.assertEqual(report['worker_complete'], 'unknown')

    def test_collection_permission_read_errors_do_not_stop_other_files(self):
        self.artifacts()
        original = ctl.regular

        def fail(parent, name):
            if name == 'manifest.json':
                raise PermissionError('SECRET')
            if name == 'events.jsonl':
                raise OSError('SECRET')
            return original(parent, name)

        with patch.object(ctl, 'regular', side_effect=fail):
            report = ctl.collect_artifacts(self.source, self.dest)
        self.assertEqual(report['files']['manifest.json']['status'], 'permission-error')
        self.assertEqual(report['files']['events.jsonl']['status'], 'read-error')
        self.assertEqual(report['files']['summary.json']['status'], 'copied-snapshot')
        self.assertNotIn('SECRET', json.dumps(report))

    def test_artifact_write_failure_is_explicit_and_still_tears_down(self):
        self.artifacts()
        original = ctl.os.open
        order = []

        def fail(name, flags, *args, **kwargs):
            if name == 'events.jsonl' and flags & os.O_WRONLY:
                raise OSError('PRIVATE_DISK_FAILURE')
            return original(name, flags, *args, **kwargs)

        with patch.object(ctl.os, 'open', side_effect=fail):
            report = ctl.collect_before_teardown(self.source, self.dest, lambda: order.append('teardown'))
        self.assertEqual(order, ['teardown'])
        self.assertEqual(report['files']['events.jsonl']['status'], 'write-error')
        self.assertEqual(report['files']['summary.json']['status'], 'copied-snapshot')
        self.assertNotIn('PRIVATE_DISK_FAILURE', json.dumps(report))

    def test_changed_source_during_copy_is_not_complete_snapshot(self):
        self.events.write_bytes(b'first')
        original = ctl.os.read

        def grow(fd, size):
            data = original(fd, size)
            with self.events.open('ab') as stream:
                stream.write(b'next')
            return data

        with patch.object(ctl.os, 'read', side_effect=grow):
            report = ctl.collect_artifacts(self.source, self.dest)
        self.assertEqual(report['files']['events.jsonl']['status'], 'changed-during-copy')
        self.assertEqual((self.dest / 'events.jsonl').read_bytes(), b'first')

    def test_hard_collection_timeout_preserves_partial_and_always_tears_down(self):
        order = []

        def blocked(source, dest, report, file_limit, total_limit):
            fd = os.open('events.jsonl', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dest)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(b'partial')
            while True:
                time.sleep(10)

        def teardown():
            order.append('teardown')
            self.assertEqual((self.dest / 'events.jsonl').read_bytes(), b'partial')
            self.source.rmdir()

        start = time.monotonic()
        with patch.object(ctl, 'copy_artifacts', blocked):
            report = ctl.collect_before_teardown(self.source, self.dest, teardown, timeout=.2)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(report['status'], 'collection-timeout')
        self.assertEqual(report['files']['events.jsonl'], {'status': 'partial-unknown', 'bytes': 7})
        self.assertEqual(order, ['teardown'])
        self.assertFalse(self.source.exists())

    def test_collect_before_removal_on_poll_startup_error_and_cancellation(self):
        for error in (ValueError('poll-failure'), KeyboardInterrupt(), RuntimeError('process-failure')):
            with self.subTest(error=type(error).__name__):
                self.artifacts()
                dest = self.root / type(error).__name__
                order = []

                def teardown():
                    order.append('teardown')
                    self.assertTrue((dest / 'events.jsonl').exists())
                    for path in self.source.iterdir():
                        path.unlink()

                with self.assertRaises(type(error)):
                    try:
                        raise error
                    finally:
                        ctl.collect_before_teardown(self.source, dest, teardown)
                self.assertEqual(order, ['teardown'])

    def test_copy_setup_process_and_cancellation_errors_always_teardown(self):
        for error in (OSError('copy-failure'), RuntimeError('process-start-failure'), KeyboardInterrupt()):
            order = []
            with patch.object(ctl, 'collect_artifacts', side_effect=error):
                with self.assertRaises(type(error)):
                    ctl.collect_before_teardown(self.source, self.dest, lambda: order.append('teardown'))
            self.assertEqual(order, ['teardown'])

    def test_collector_process_start_failure_and_crash_still_teardown(self):
        order = []
        with patch('multiprocessing.process.BaseProcess.start', side_effect=OSError('start')):
            with self.assertRaises(OSError):
                ctl.collect_before_teardown(self.source, self.dest, lambda: order.append('teardown'))
        self.assertEqual(order, ['teardown'])

        def crash(*args):
            raise SystemExit(7)

        with patch.object(ctl, 'copy_artifacts', crash):
            report = ctl.collect_before_teardown(self.source, self.root / 'crashed',
                                                 lambda: order.append('teardown'))
        self.assertEqual(report['status'], 'collector-error')
        self.assertEqual(order, ['teardown', 'teardown'])

    def test_revised_abort_procedure_verified_cancel_then_copy_then_removal(self):
        for verified in (True, False):
            with self.subTest(verified=verified):
                self.events.write_bytes(b'{bad}\n')
                dest = self.root / ('verified' if verified else 'unverified')
                order = []

                def cancel_verified_python():
                    # Fake ownership inspection, not the ready PID as signaling authority.
                    self.assertTrue(verified)
                    order.append('cancel-verified-python')
                    (self.source / 'summary.json').write_bytes(b'{"outcome":"cancelled"}')

                def remove_owned_runtime():
                    self.assertTrue((dest / 'events.jsonl').exists())
                    if verified:
                        self.assertEqual((dest / 'summary.json').read_bytes(), b'{"outcome":"cancelled"}')
                    order.append('stop-own-unit-and-remove-runtime')
                    for path in self.source.iterdir():
                        path.unlink()

                try:
                    try:
                        result = self.poll()
                        self.assertEqual(result['status'], 'malformed-json')
                    finally:
                        try:
                            if verified:
                                cancel_verified_python()
                        finally:
                            report = ctl.collect_before_teardown(self.source, dest, remove_owned_runtime)
                finally:
                    order.append('reference-teardown')
                self.assertEqual(order, (['cancel-verified-python'] if verified else []) + [
                    'stop-own-unit-and-remove-runtime', 'reference-teardown'])
                if not verified:
                    self.assertEqual(report['files']['summary.json']['status'], 'missing')
                self.assertEqual(report['worker_complete'], 'unknown')

    def test_teardown_error_propagates_and_outer_reference_cleanup_runs(self):
        order = []

        def broken_teardown():
            order.append('worker-stop-attempt')
            raise OSError('own-worker-stop-failed')

        with self.assertRaises(OSError):
            try:
                ctl.collect_before_teardown(self.source, self.dest, broken_teardown)
            finally:
                order.append('reference-teardown')
        self.assertEqual(order, ['worker-stop-attempt', 'reference-teardown'])
        self.assertTrue((self.dest / 'collection.json').exists())


if __name__ == '__main__':
    unittest.main()
