#!/usr/bin/env python3
"""Bounded TCP screen. No privilege changes; see PACKAGE-3.md for launch gate.

--prepare-worker selects inputs offline. Network execution requires a separately
reviewed --gate release. Raw results remain route-unverified: a controller must
corroborate privileged underlay/policy/socket evidence, not trust a CLI assertion.
"""
import argparse
import datetime
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import select
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ALIASES = ('direct', 'nt1-ssh', 'nt1-naive', 'nt1-vless',
           'cherry-ssh', 'cherry-naive', 'cherry-vless')
ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
ALIAS = re.compile(r'[a-z0-9_-]{1,64}')
BUFFER = 8 * 1024 * 1024
RESERVE = 262144
SKEW = 5
MAX_OBJECTS = 338  # 3 operations/object + two preflights + their receipts <1024.
ENDPOINT_FIELDS = {'schema_version', 'alias', 'https_url', 'auth_header', 'family',
                   'expected_status', 'content_type', 'object_bytes', 'sha256',
                   'cache_policy', 'receipt_url', 'receipt_auth_header', 'location',
                   'ca_file', 'run_id', 'expires_at'}


class Stop(Exception):
    def __init__(self, outcome, stage, code):
        self.outcome, self.stage, self.code = outcome, stage, code


def require(condition, code='invalid-input'):
    if not condition:
        raise Stop('failed', 'input', code)


def clean_env():
    return {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/nonexistent'}


def safe_path(path):
    text(str(path))
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute-path-required')
    require(all(not p.is_symlink() for p in (path, *path.parents)), 'symlink-path')
    return path


def private_file(path, credential=False):
    path = safe_path(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= BUFFER, 'input-size-type')
    if credential:
        root = safe_path(os.environ.get('CREDENTIALS_DIRECTORY', '/nonexistent'))
        require(path.parent == root and path.name in ('worker.json', 'ca.pem'), 'credential-path')
        require(os.statvfs(root).f_flag & os.ST_RDONLY, 'credential-not-readonly')
        require(info.st_uid in (0, os.geteuid()) and info.st_gid in (0, os.getegid())
                and stat.S_IMODE(info.st_mode) in (0o400, 0o440), 'credential-permissions')
    else:
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, 'private-input-required')
        require(path.parent.stat().st_uid == os.geteuid()
                and not path.parent.stat().st_mode & 0o077, 'private-parent-required')
    return path


def load_json(path, credential=False):
    return json.loads(private_file(path, credential).read_text())


def text(value):
    require(isinstance(value, str) and 0 < len(value) <= 8192
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'unsafe-text')
    return value


def origin(url):
    text(url)
    parsed = urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.fragment and not parsed.netloc.endswith(':'), 'https-origin')
    require(not any(c in url for c in ('{', '}', '\\', ' ')), 'unsafe-url')
    return parsed.scheme, parsed.hostname.lower(), parsed.port or 443


def endpoint(data, credential=False):
    require(isinstance(data, dict) and not set(data) - ENDPOINT_FIELDS, 'endpoint-schema')
    required = ENDPOINT_FIELDS - {'auth_header', 'receipt_url', 'receipt_auth_header'}
    require(required <= set(data) and type(data['schema_version']) is int
            and data['schema_version'] == 1, 'endpoint-schema')
    require(isinstance(data['alias'], str) and ALIAS.fullmatch(data['alias']), 'endpoint-alias')
    require(isinstance(data['run_id'], str) and ID.fullmatch(data['run_id']), 'run-id')
    require(data['family'] in ('ipv4', 'ipv6'), 'endpoint-family')
    require(data['location'] in ('vpn-host', 'distinct-host'), 'endpoint-location')
    require(type(data['object_bytes']) is int and 1 <= data['object_bytes'] <= 4294967296, 'object-size')
    require(type(data['expires_at']) is int, 'endpoint-expiry')
    require(type(data['expected_status']) is int and data['expected_status'] == 200, 'expected-status')
    require(data['content_type'] == 'application/octet-stream'
            and data['cache_policy'] == 'no-store, no-transform', 'content-policy')
    require(isinstance(data['sha256'], str) and re.fullmatch('[0-9a-f]{64}', data['sha256']), 'digest')
    base = origin(data['https_url'])
    try:
        literal = ipaddress.ip_address(base[1])
    except ValueError:
        literal = None
    require(literal is None or data['family'] == 'ipv' + str(literal.version), 'url-family-mismatch')
    require(private_file(data['ca_file'], credential).stat().st_size <= 65536, 'ca-size')
    for key in ('auth_header', 'receipt_auth_header'):
        if key in data:
            require(re.fullmatch(r'Authorization: Bearer [A-Za-z0-9._~+/-]+=*', text(data[key])), 'auth-header')
    if 'receipt_url' in data:
        receipt = text(data['receipt_url'])
        require(receipt.endswith('/{request}') and receipt.count('{') == 1
                and receipt.count('}') == 1 and 'receipt_auth_header' in data, 'receipt-template')
        require(origin(receipt.replace('{request}', 'operation')) == base, 'receipt-origin')
        require(not urlsplit(receipt).query, 'receipt-query')
        require(data.get('auth_header') != data['receipt_auth_header'], 'separate-receipt-auth')
    else:
        require('receipt_auth_header' not in data, 'receipt-auth-without-url')
    return data


def same_lease(obj, preflight):
    require(origin(obj['https_url']) == origin(preflight['https_url']), 'preflight-origin')
    for key in ('run_id', 'expires_at', 'ca_file', 'auth_header', 'receipt_url',
                'receipt_auth_header', 'family', 'location'):
        require(obj.get(key) == preflight.get(key), 'preflight-lease-mismatch')
    require(preflight['object_bytes'] <= 65536, 'preflight-must-be-small-complete-object')


def lifetime(obj, needed, now=None):
    remaining = obj['expires_at'] - (time.time() if now is None else now)
    if remaining < needed + SKEW:
        raise Stop('inconclusive', 'budget', 'endpoint-expired-or-insufficient-lifetime')
    return remaining


def bounded_command(argv, payload=None, timeout=10, env=None):
    """No unbounded communicate(), raw stderr, inherited proxies or orphan groups."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=clean_env() if env is None else env, start_new_session=True)
    try:
        if payload:
            require(len(payload) <= BUFFER, 'command-input-limit')
            # Inputs here are <=8 MiB; concurrent nonblocking writes avoid pipe deadlock.
        streams = selectors.DefaultSelector()
        for file, kind in ((proc.stdout, 'out'), (proc.stderr, 'err')):
            os.set_blocking(file.fileno(), False)
            streams.register(file, selectors.EVENT_READ, kind)
        if payload:
            os.set_blocking(proc.stdin.fileno(), False)
            streams.register(proc.stdin, selectors.EVENT_WRITE, 'in')
        else:
            proc.stdin.close()
        output, used, written = bytearray(), 0, 0
        end = time.monotonic() + timeout
        while streams.get_map():
            if time.monotonic() >= end:
                raise Stop('timeout', 'process', 'command-timeout')
            for key, _ in streams.select(min(.1, max(0, end - time.monotonic()))):
                if key.data == 'in':
                    try:
                        written += os.write(key.fd, payload[written:written + 65536])
                    except BrokenPipeError:
                        written = len(payload)
                    if written == len(payload):
                        streams.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                data = os.read(key.fd, 65536)
                if not data:
                    streams.unregister(key.fileobj)
                    continue
                used += len(data)
                if used > BUFFER:
                    raise Stop('inconclusive', 'budget', 'diagnostic-buffer-limit')
                if key.data == 'out':
                    output.extend(data)
        proc.wait(timeout=max(.01, end - time.monotonic()))
        return proc.returncode, bytes(output)
    finally:
        kill_owned([proc])
        for file in (proc.stdin, proc.stdout, proc.stderr):
            file.close()
        if 'streams' in locals():
            streams.close()


def kill_owned(processes):
    # One shared grace period, not five seconds per child.
    for proc in processes:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    end = time.monotonic() + 5
    while any(p.poll() is None for p in processes) and time.monotonic() < end:
        time.sleep(.01)
    for proc in processes:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=1)


def outbound(data, route):
    require(isinstance(data, dict), 'outbound-object')
    kind = route.split('-')[-1]
    tag = route if route.startswith('cherry-') else kind
    require(data.get('type') == kind and data.get('tag') == tag, 'outbound-type-tag')
    common = {'type', 'tag', 'server', 'server_port', 'domain_resolver'}
    allowed = {'ssh': {'user', 'password', 'private_key', 'private_key_passphrase', 'host_key',
                       'host_key_algorithms', 'client_version'},
               'naive': {'username', 'password', 'tls'},
               'vless': {'uuid', 'flow', 'tls', 'packet_encoding'}}
    require(not set(data) - common - allowed[kind], 'unsafe-outbound-field')
    require(len(json.dumps(data).encode()) <= 65536, 'outbound-size')
    text(data.get('server'))
    try:
        server_ip = ipaddress.ip_address(data['server'])
    except ValueError:
        server_ip = None
    if server_ip is not None and server_ip.version != 4:
        raise Stop('unsupported', 'route', 'no-ipv6-underlay')
    require(type(data.get('server_port')) is int and 1 <= data['server_port'] <= 65535, 'server-port')
    require('domain_resolver' not in data, 'unreviewed-bootstrap-resolver')
    if kind == 'ssh':
        text(data.get('user'))
        require(bool(data.get('password') or data.get('private_key')), 'ssh-auth')
        require(isinstance(data.get('host_key'), list) and data['host_key']
                and all(isinstance(v, str) and v for v in data['host_key']), 'ssh-pin')
    elif kind == 'naive':
        text(data.get('username'))
        text(data.get('password'))
    else:
        require(isinstance(data.get('uuid'), str)
                and re.fullmatch('[0-9a-fA-F-]{36}', data['uuid']), 'vless-uuid')
    if kind != 'ssh':
        tls = data.get('tls')
        require(isinstance(tls, dict) and tls.get('enabled') is True and not tls.get('insecure'), 'tls-verification')
        require(not set(tls) - {'enabled', 'server_name', 'utls', 'reality', 'alpn', 'insecure'}, 'tls-field')
        text(tls.get('server_name'))
        if 'utls' in tls:
            require(set(tls['utls']) <= {'enabled', 'fingerprint'}, 'utls-field')
        if 'reality' in tls:
            require(set(tls['reality']) <= {'enabled', 'public_key', 'short_id'}, 'reality-field')
    return data


def select_outbound(args):
    if args.route == 'direct':
        require(not any((args.vault_file, args.vault_password_file, args.extra_outbounds_file)), 'direct-credential-input')
        return None
    candidates = []
    if args.vault_file or args.vault_password_file:
        require(args.vault_file and args.vault_password_file, 'vault-pair-required')
        # The tracked Vault ciphertext is 0644; it is not a plaintext credential.
        # Password, descriptors and private exports retain owner-only validation.
        vault = safe_path(args.vault_file)
        info = vault.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o022 and info.st_size <= BUFFER, 'unsafe-vault-ciphertext')
        with vault.open('rb') as file:
            require(file.read(32).startswith(b'$ANSIBLE_VAULT;'), 'vault-ciphertext-required')
        password = private_file(args.vault_password_file)
        with tempfile.TemporaryDirectory(prefix='vpn-screen-ansible-', dir=Path(args.output).parent) as temp:
            config = Path(temp) / 'ansible.cfg'
            config.write_text('')
            config.chmod(0o600)
            env = clean_env() | {'HOME': temp, 'ANSIBLE_LOCAL_TEMP': temp + '/tmp', 'ANSIBLE_CONFIG': str(config)}
            code, plain = bounded_command(['ansible-vault', 'view', str(vault),
                                           '--vault-password-file', str(password)], timeout=10, env=env)
            require(code == 0, 'vault-view-failed')
            # Existing Ansible dependency, isolated helper; never emit tokens or decrypted YAML.
            helper = ('import sys,json; from ansible.parsing.utils.yaml import from_yaml; '
                      'd=from_yaml(sys.stdin.read())["sing_box_secrets"]; '
                      'print(json.dumps({"connections":d["connections"],'
                      '"extra_outbounds":d.get("extra_outbounds",[])}))')
            code, raw = bounded_command([sys.executable, '-c', helper], plain, env=env)
            del plain
            require(code == 0, 'vault-parse-failed')
        parsed = json.loads(raw)
        require(isinstance(parsed['connections'], dict)
                and set(parsed['connections']) <= {'ssh', 'naive', 'vless'}, 'vault-connections')
        for kind, obj in parsed['connections'].items():
            candidates.append(outbound(obj, 'nt1-' + kind))
        require(isinstance(parsed['extra_outbounds'], list), 'vault-extras')
        for obj in parsed['extra_outbounds']:
            require(isinstance(obj, dict) and obj.get('tag') in (
                'cherry-ssh', 'cherry-naive', 'cherry-vless'), 'unknown-vault-extra-tag')
            candidates.append(outbound(obj, obj['tag']))
    if args.extra_outbounds_file:
        extra = load_json(args.extra_outbounds_file)
        require(isinstance(extra, list), 'extra-outbounds-list')
        # Strict export: only the three unnested Cherry routes, not workstation hops.
        tags = [o.get('tag') for o in extra if isinstance(o, dict)]
        require(len(tags) == len(extra) and len(set(tags)) == len(tags), 'duplicate-outbound')
        require(set(tags) <= {'cherry-ssh', 'cherry-naive', 'cherry-vless'}, 'unknown-extra-tag')
        for obj in extra:
            outbound(obj, obj['tag'])
        candidates.extend(extra)
    tag = args.route if args.route.startswith('cherry-') else args.route.split('-')[-1]
    selected = [obj for obj in candidates if obj.get('tag') == tag]
    if not selected:
        raise Stop('skipped', 'input', 'missing-input')
    require(len(selected) == 1, 'ambiguous-route-source')
    return outbound(selected[0], args.route)


def config_shape(value, key=''):
    if isinstance(value, dict):
        return {k: config_shape(v, k) for k, v in sorted(value.items())}
    if key in ('type', 'tag', 'flow', 'packet_encoding', 'enabled', 'insecure'):
        return value
    if isinstance(value, list):
        return [config_shape(v, key) for v in value]
    return '<' + type(value).__name__ + '-present>'


def fingerprint(value):
    return hashlib.sha256(json.dumps(config_shape(value), sort_keys=True).encode()).hexdigest()


def curl_quote(value):
    value = str(value)
    if value:
        text(value)
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def curl_config(obj, operation, proxy, rate, timeout, header_fd, metrics_fd, receipt=None):
    require(ID.fullmatch(operation), 'operation-id')
    url = obj['https_url'] if receipt is None else obj['receipt_url'].replace('{request}', receipt)
    if receipt is not None:
        require(ID.fullmatch(receipt), 'receipt-id')
    options = {'url': url, 'cacert': obj['ca_file'], 'proxy': proxy or '',
               'noproxy': '' if proxy else '*', 'proto': '=https', 'proto-redir': '=https',
               'connect-timeout': min(10, timeout), 'max-time': timeout,
               'limit-rate': max(1, rate), 'dump-header': f'/dev/fd/{header_fd}',
               'write-out': f'%output{{/dev/fd/{metrics_fd}}}' +
               '{"http_status":"%{http_code}","http_version":"%{http_version}",'
               '"ttfb_s":%{time_starttransfer},"time_total_s":%{time_total},'
               '"inner_new_connections":%{num_connects}}'}
    lines = ['silent', 'show-error', 'no-buffer', 'ipv4', 'http1.1', 'globoff', 'request = "GET"']
    lines.extend(k + ' = ' + curl_quote(v) for k, v in options.items())
    headers = ['X-Run-ID: ' + obj['run_id'], 'X-Request-ID: ' + operation,
               'Accept-Encoding: identity', 'Cache-Control: no-cache']
    auth = obj.get('auth_header' if receipt is None else 'receipt_auth_header')
    if auth:
        headers.append(auth)
    lines.extend('header = ' + curl_quote(h) for h in headers)
    return ('\n'.join(lines) + '\n').encode()


def parse_headers(raw):
    # CONNECT/1xx blocks are not the origin response. Never retain header values.
    blocks = raw.replace(b'\r\n', b'\n').strip().split(b'\n\n')
    final = blocks[-1].split(b'\n')
    require(final and re.fullmatch(rb'HTTP/\S+ [0-9]{3}(?: .*)?', final[0]), 'malformed-headers')
    status = int(final[0].split()[1])
    headers = {}
    for line in final[1:]:
        require(b':' in line and not line.startswith((b' ', b'\t')), 'malformed-headers')
        key, value = line.split(b':', 1)
        key = key.decode('ascii').lower()
        require(key not in headers, 'duplicate-response-header')
        headers[key] = value.strip().decode('ascii')
    return status, headers


def parse_metrics(raw):
    try:
        data = json.loads(raw)
        require(set(data) == {'http_status', 'http_version', 'ttfb_s', 'time_total_s',
                             'inner_new_connections'}, 'malformed-metrics')
        if isinstance(data['http_status'], str) and re.fullmatch('[0-9]{3}', data['http_status']):
            data['http_status'] = int(data['http_status'])
        for key in ('ttfb_s', 'time_total_s'):
            require(type(data[key]) in (float, int) and math.isfinite(data[key])
                    and data[key] >= 0, 'malformed-metrics')
        require(type(data['http_status']) is int and 0 <= data['http_status'] <= 599
                and data['http_version'] in ('0', '1', '1.0', '1.1', '2', '3')
                and type(data['inner_new_connections']) is int
                and data['inner_new_connections'] >= 0, 'malformed-metrics')
        return data
    except (ValueError, TypeError, Stop):
        raise Stop('failed', 'process', 'malformed-metrics') from None


def content_check(obj, raw, receipt=False):
    status, headers = parse_headers(raw)
    if 300 <= status < 400:
        return 'redirect', status
    if status != obj['expected_status']:
        return ('authentication' if status == 401 else 'http-status'), status
    if headers.get('content-type', '').lower() != ('application/json' if receipt else obj['content_type']):
        return 'content-type', status
    if 'content-encoding' in headers or 'transfer-encoding' in headers:
        return 'content-encoding', status
    if headers.get('cache-control') != obj['cache_policy'] or 'age' in headers:
        return 'cache-policy', status
    if not headers.get('content-length', '').isdigit():
        return 'unexpected-length', status
    size = int(headers['content-length'])
    if (receipt and size > 8192) or (not receipt and size != obj['object_bytes']):
        return 'unexpected-length', status
    return None, status


class Artifacts:
    def __init__(self, args):
        root = safe_path(args.output)
        parent = root.parent.stat()
        require(parent.st_uid == os.geteuid() and not parent.st_mode & 0o077, 'private-output-parent')
        root.mkdir(mode=0o700)  # New only; no following/replacing prior output.
        self.root, self.limit, self.used = root, args.max_disk_bytes, 0
        self.start = time.monotonic()
        self.envelope = {'schema_version': 1, 'run': 'unselected', 'route': args.route,
                         'endpoint': 'unselected'}
        self.stream = (root / 'events.jsonl').open('x', encoding='utf8')
        os.chmod(root / 'events.jsonl', 0o600)
        self.manifest = {'schema_version': 1, 'complete': False, 'route': args.route,
                         'workload': args.workload, 'duration_s': args.duration,
                         'budgets': {k: getattr(args, k) for k in ('rate_limit', 'max_bytes',
                                                                  'max_disk_bytes', 'concurrency')},
                         'route_proof': 'unverified', 'scope': 'controlled TCP screen only'}
        self.atomic('manifest.json', self.manifest)

    def atomic(self, name, data):
        content = (json.dumps(data, sort_keys=True, indent=2) + '\n') if not isinstance(data, str) else data
        encoded = content.encode()
        old = self.root / name
        prior = old.stat().st_size if old.exists() else 0
        total = sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())
        # Atomic replacement briefly needs both versions; reserve covers terminal files.
        if total + len(encoded) > self.limit:
            raise Stop('inconclusive', 'budget', 'disk-limit-finalization')
        temp = self.root / (name + '.tmp')
        with temp.open('x', encoding='utf8') as file:
            os.chmod(temp, 0o600)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        temp.replace(old)
        self.used += len(encoded) - prior

    def emit(self, event, **fields):
        row = self.envelope | {'event': event,
                              'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                              'elapsed_s': time.monotonic() - self.start} | fields
        data = json.dumps(row, sort_keys=True) + '\n'
        if self.used + len(data.encode()) > self.limit - RESERVE and event not in ('run-end', 'request-end'):
            raise Stop('inconclusive', 'budget', 'disk-limit')
        self.stream.write(data)
        self.stream.flush()
        self.used += len(data.encode())

    def close(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class Transfer:
    def __init__(self, runner, obj, phase, deadline, receipt=None):
        self.runner, self.obj, self.phase = runner, obj, phase
        self.operation = secrets.token_hex(16)
        self.receipt = receipt
        self.started = time.monotonic()
        self.deadline = deadline
        self.received = 0
        self.first = self.last = None
        self.stalls = []
        self.digest = hashlib.sha256()
        self.buffers = {'headers': bytearray(), 'metrics': bytearray(), 'stderr': bytearray(), 'control': bytearray()}
        self.stream_bytes = {}
        self.reason = None
        self.body_eof = self.eof_before_cancel = False
        self.terminated = False
        self.terminated_at = None
        self.finished = False
        header_r, header_w = os.pipe()
        metric_r, metric_w = os.pipe()
        try:
            config = curl_config(obj, self.operation, runner.proxy,
                                 runner.args.rate_limit // runner.args.concurrency,
                                 max(.001, deadline - self.started), header_w, metric_w, receipt)
            self.proc = subprocess.Popen(['curl', '--disable', '--config', '-'], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         pass_fds=(header_w, metric_w), env=clean_env(), start_new_session=True)
        except BaseException:
            os.close(header_r)
            os.close(metric_r)
            raise
        finally:
            os.close(header_w)
            os.close(metric_w)
        self.files = {self.proc.stdin: 'config', self.proc.stdout: 'body', self.proc.stderr: 'stderr',
                      os.fdopen(header_r, 'rb', buffering=0): 'headers',
                      os.fdopen(metric_r, 'rb', buffering=0): 'metrics'}
        runner.transfers.append(self)
        self.pending_config, self.config_offset = config, 0
        for file, kind in self.files.items():
            os.set_blocking(file.fileno(), False)
            runner.selector.register(file, selectors.EVENT_WRITE if kind == 'config' else selectors.EVENT_READ, (self, kind))
        runner.art.emit('request-start', request=self.operation, phase=phase, child_pid=self.proc.pid,
                        receipt_for=receipt, stage='process', outcome=None)

    def abort(self, reason):
        # A natural exit is evidence, not a cancellation just because observation was late.
        if self.proc.poll() is not None:
            return
        if self.reason is None:
            self.reason = reason
            if not self.proc.stdout.closed:
                # POLLHUP sees writer closure even with unread body bytes still in the pipe.
                eof = select.poll()
                eof.register(self.proc.stdout, select.POLLHUP)
                self.body_eof |= any(events & select.POLLHUP for _, events in eof.poll(0))
            self.eof_before_cancel = self.body_eof
        if not self.terminated:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.terminated = True
                self.terminated_at = time.monotonic()
            except ProcessLookupError:
                pass  # Exit raced with poll; finish must still preserve the raw status.

    def drain(self, file, kind):
        if kind == 'config':
            try:
                self.config_offset += os.write(file.fileno(), self.pending_config[self.config_offset:self.config_offset + 65536])
            except BrokenPipeError:
                self.config_offset = len(self.pending_config)
            if self.config_offset == len(self.pending_config):
                self.runner.selector.unregister(file)
                file.close()
                self.pending_config = b''
            return
        count = 65536
        if kind == 'body':
            count = min(count, max(0, self.runner.args.max_bytes - sum(self.runner.bytes.values())))
            if count == 0:
                self.runner.selector.unregister(file)
                file.close()
                self.abort('byte-limit')
                return
        data = os.read(file.fileno(), count)
        if not data:
            if kind == 'body':
                self.body_eof = True
            self.runner.selector.unregister(file)
            return
        now = time.monotonic()
        if kind == 'body':
            if self.first is None:
                self.first = now
            if self.last is not None and now - self.last >= 2:
                self.stalls.append({'duration_s': now - self.last, 'censored': False})
            self.last = now
            self.received += len(data)
            self.digest.update(data)
            self.runner.body(self.phase, len(data))
            if self.receipt is not None:
                self.buffers['control'].extend(data[:max(0, 8193 - len(self.buffers['control']))])
                if self.received > 8192:
                    self.abort('control-buffer-limit')
        else:
            self.stream_bytes[kind] = self.stream_bytes.get(kind, 0) + len(data)
            cap = BUFFER if kind == 'stderr' else 65536
            if self.stream_bytes[kind] > cap:
                self.abort('diagnostic-buffer-limit')
            if kind != 'stderr':
                self.buffers[kind].extend(data[:max(0, cap - len(self.buffers[kind]))])
            # stderr is drained but never stored: it may contain secrets/addresses.

    def ready(self):
        return self.proc.poll() is not None and not any(
            key.data[0] is self for key in self.runner.selector.get_map().values())

    def finish(self):
        now = time.monotonic()
        if self.last is not None and now - self.last >= 2:
            self.stalls.append({'duration_s': now - self.last, 'censored': True})
        metrics = {'http_status': None, 'http_version': None, 'ttfb_s': None,
                   'time_total_s': None, 'inner_new_connections': None}
        error, outcome, stage = self.reason, 'failed', 'response-body'
        integrity = 'partial-unverified'
        owned_sigterm = self.terminated and self.proc.returncode == -signal.SIGTERM
        planned_cancel = self.reason == 'completed-window' and owned_sigterm and not self.eof_before_cancel
        termination = 'natural-exit' if self.reason is None else 'exit-raced-with-cancellation'
        if owned_sigterm:
            termination = 'eof-before-runner-sigterm' if self.eof_before_cancel else 'runner-sigterm'
        metric_error = None
        try:
            metrics = parse_metrics(self.buffers['metrics'])
        except Stop:
            # TERM/error exits may omit write-out, but emitted malformed diagnostics are evidence.
            if self.buffers['metrics'] or not self.proc.returncode:
                metric_error = 'malformed-metrics'
        content_error = None
        if self.buffers['headers']:
            try:
                content_error, status = content_check(self.obj, self.buffers['headers'], self.receipt is not None)
                metrics['http_status'] = status
            except (Stop, ValueError, UnicodeError):
                content_error = 'malformed-response'
        elif not self.proc.returncode or (planned_cancel and self.received):
            content_error = 'malformed-response'
        if metric_error:
            error, stage = metric_error, 'process'
        elif content_error:
            error, stage = content_error, content_error
        elif self.reason and self.reason != 'completed-window':
            outcome = 'cancelled' if self.reason == 'cancelled' else 'inconclusive'
        elif self.proc.returncode and not owned_sigterm:
            outcome = 'timeout' if self.proc.returncode == 28 else 'failed'
            stage = {5: 'bootstrap-dns', 7: 'tcp', 18: 'unexpected-length', 35: 'tls',
                     60: 'tls', 67: 'authentication'}.get(self.proc.returncode, 'unknown')
            if self.proc.returncode == 6:
                stage = 'destination-dns' if not self.runner.proxy else 'unknown'
            # Proxy connect/TLS timings cannot identify the remote leg.
            short_eof = (self.proc.returncode in (18, 56) and self.first is not None
                         and self.received < self.obj['object_bytes'])
            error = 'unexpected-length' if short_eof else f'curl-{self.proc.returncode}'
            if short_eof:
                stage = 'unexpected-length'
        elif (planned_cancel and self.phase == 'workload'
              and self.runner.args.workload == 'segments' and self.received == self.obj['object_bytes']):
            if self.digest.hexdigest() == self.obj['sha256']:
                outcome, error, integrity = 'passed', None, 'verified'
            else:
                error, stage, integrity = 'integrity', 'integrity', 'failed'
        elif planned_cancel and (self.first is not None or self.runner.args.workload == 'segments'):
            outcome, error = 'completed-window', None
        elif planned_cancel:
            outcome, error, stage = 'timeout', 'no-body-before-deadline', 'response-body'
        elif self.receipt is not None:
            try:
                _, headers = parse_headers(self.buffers['headers'])
                require(self.received == int(headers['content-length']), 'receipt-length')
                outcome, error = 'passed', None
            except (Stop, ValueError, KeyError):
                error, stage = 'unexpected-length', 'unexpected-length'
        elif self.received != self.obj['object_bytes']:
            error, stage = 'unexpected-length', 'unexpected-length'
        elif self.digest.hexdigest() != self.obj['sha256']:
            error, stage, integrity = 'integrity', 'integrity', 'failed'
        elif self.phase == 'workload' and self.runner.args.workload == 'continuous':
            error, stage = 'unexpected-length', 'unexpected-length'
        else:
            outcome, error, integrity = 'passed', None, 'verified'
        if self.reason in ('cancelled', 'environment-changed', 'byte-limit', 'disk-limit',
                           'diagnostic-buffer-limit', 'control-buffer-limit', 'ttfb-deadline', 'request-deadline', 'endpoint-expired'):
            error = self.reason
            stage = 'budget' if 'limit' in error or error == 'endpoint-expired' else 'response-body'
            outcome = 'cancelled' if error == 'cancelled' else ('timeout' if 'deadline' in error else 'inconclusive')
        row = {'request': self.operation, 'phase': self.phase, 'outcome': outcome,
               'stage': stage, 'error': error, 'curl_exit': self.proc.returncode,
               'cancellation_reason': self.reason, 'termination': termination,
               'expected_bytes': None if self.receipt else self.obj['object_bytes'],
               'received_bytes': self.received, 'integrity': integrity,
               'stalls': self.stalls, 'outer_connections': None, 'outer_reuse': 'unknown',
               'timing_attribution': 'curl application timing; remote leg unknown',
               'unavailable_timing_reason': 'runner cancellation or missing metrics' if metrics['time_total_s'] is None else None,
               **metrics}
        row.update(content_checks='passed' if self.buffers['headers'] and not content_error else 'failed-or-unknown',
                   workload_elapsed_s=None if self.runner.work_start is None else now - self.runner.work_start,
                   workload_bytes_at_end=self.runner.bytes['workload'])
        self.finished = True
        kill_owned([self.proc])  # Retire this group now; never signal an old/reused PID at run cleanup.
        if self.phase == 'workload':
            self.runner.results.append(row)
        self.runner.all_results.append(row)
        self.runner.art.emit('request-end', **row)
        for file in self.files:
            file.close()
        return row


def host_sample():
    try:
        cpu = Path('/proc/stat').read_text().splitlines()[0].split()[1:]
        mem = dict((p[0].rstrip(':'), int(p[1])) for line in Path('/proc/meminfo').read_text().splitlines()
                   if len(p := line.split()) >= 2)
        interfaces = [line.split(':', 1)[1].split() for line in Path('/proc/net/dev').read_text().splitlines()[2:]]
        snmp = Path('/proc/net/snmp').read_text().splitlines()
        tcp = {}
        for a, b in zip(snmp[::2], snmp[1::2]):
            if a.startswith('Tcp:'):
                tcp = dict(zip(a.split()[1:], map(int, b.split()[1:])))
        return {'cpu_ticks': list(map(int, cpu)), 'mem_available_kib': mem.get('MemAvailable'),
                'network_rx_bytes': sum(int(v[0]) for v in interfaces),
                'network_tx_bytes': sum(int(v[8]) for v in interfaces),
                'network_drops': sum(int(v[3]) + int(v[11]) for v in interfaces),
                'tcp_retrans_segs': tcp.get('RetransSegs'),
                'attribution': 'shared host counters, not per-route loss', 'remote': 'unknown'}
    except (OSError, ValueError, IndexError):
        return {'client': 'unknown', 'remote': 'unknown'}


def environment():
    snapshot = {}
    for file in ('/proc/net/route', '/proc/net/ipv6_route', '/etc/resolv.conf', '/etc/nsswitch.conf'):
        try:
            snapshot[file] = hashlib.sha256(Path(file).read_bytes()).hexdigest()
        except OSError:
            snapshot[file] = 'unknown'
    for what in ('link', 'address', 'rule'):
        try:
            code, raw = bounded_command(['ip', '-j', what, 'show'], timeout=.5)
            rows = json.loads(raw) if code == 0 else None
            def stable(value):
                if isinstance(value, dict):
                    return {k: stable(v) for k, v in value.items()
                            if k not in ('valid_life_time', 'preferred_life_time', 'stats64', 'stats')}
                if isinstance(value, list):
                    return [stable(v) for v in value]
                return value
            snapshot[what] = 'unknown' if rows is None else hashlib.sha256(
                json.dumps(stable(rows), sort_keys=True).encode()).hexdigest()
        except (OSError, ValueError, Stop):
            snapshot[what] = 'unknown'
    # Privileged policy/process/config watcher remains mandatory in the controller.
    return snapshot


class Runner:
    def __init__(self, args, art):
        self.args, self.art = args, art
        self.selector = selectors.DefaultSelector()
        self.transfers, self.results, self.objects, self.progress = [], [], [], []
        self.all_results = []
        self.bytes = {'workload': 0, 'preflight': 0, 'receipt': 0}
        self.operations = 0
        self.proxy = None
        self.core = None
        self.core_log = None
        self.selected_log_seen = False
        self.cancelled = False
        self.work_start = self.work_end = None
        self.baseline = None
        self.next_tick = time.monotonic() + 1
        self.tick_at = time.monotonic()
        self.previous_bytes = 0
        self.stop_reason = None
        self.receipts = []
        self.next_operation = 0.0
        self.lease_expires = None
        self.cleaned = False

    def body(self, phase, count):
        self.bytes[phase] += count
        if sum(self.bytes.values()) >= self.args.max_bytes:
            self.stop_reason = 'byte-limit'

    def tick(self, force=False):
        now = time.monotonic()
        self.check_core()
        if not force and now < self.next_tick:
            return
        if self.work_start is not None and self.work_end is None:
            elapsed = now - self.tick_at
            delta = self.bytes['workload'] - self.previous_bytes
            row = {'workload_elapsed_s': now - self.work_start, 'interval_s': elapsed,
                   'body_bytes_total': self.bytes['workload'], 'body_bytes_delta': delta,
                   'goodput_mbit_s': 8 * delta / elapsed / 1e6 if elapsed else 0,
                   'request': None, 'stage': 'response-body', 'outcome': None}
            self.progress.append(row)
            self.art.emit('progress', **row)
            self.previous_bytes = self.bytes['workload']
        processes = []
        for pid in [os.getpid()] + [t.proc.pid for t in self.transfers if t.proc.poll() is None] + ([self.core.pid] if self.core else []):
            try:
                fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
                processes.append({'pid': pid, 'cpu_user_ticks': int(fields[11]),
                                  'cpu_system_ticks': int(fields[12]), 'rss_pages': int(fields[21])})
            except (OSError, ValueError, IndexError):
                processes.append({'pid': pid, 'state': 'unknown'})
        self.art.emit('host-sample', processes=processes, **host_sample())
        if self.baseline is not None and environment() != self.baseline:
            self.stop_reason = 'environment-changed'
        self.tick_at, self.next_tick = now, now + 1

    def check_core(self):
        if self.core is not None and self.core.poll() is not None:
            raise Stop('failed', 'process', 'isolated-core-exited')
        if self.core_log is not None:
            while True:
                try:
                    data = os.read(self.core_log.fileno(), 65536)
                except BlockingIOError:
                    break
                if not data:
                    break
                self.core_log_bytes += len(data)
                combined = getattr(self, 'core_tail', b'') + data
                self.selected_log_seen |= ('outbound/' + self.selected_kind + '[' + self.selected_tag + ']').encode() in combined
                self.core_tail = combined[-128:]
                if self.core_log_bytes > BUFFER:
                    raise Stop('inconclusive', 'budget', 'core-log-limit')

    def pump(self, tasks, end):
        # Observe queued response/EOF evidence first; wake at deadlines, not one poll later.
        pending = [t for t in tasks if not t.terminated]
        wake = min([self.next_tick] + ([end] if pending else []) + [t.deadline for t in pending]
                   + [t.started + 20 for t in pending if t.first is None])
        for key, _ in self.selector.select(max(0, min(.05, wake - time.monotonic()))):
            task, kind = key.data
            task.drain(key.fileobj, kind)
        now = time.monotonic()
        if self.lease_expires is not None and time.time() >= self.lease_expires - SKEW:
            self.stop_reason = 'endpoint-expired'
        for task in tasks:
            if self.cancelled:
                task.abort('cancelled')
            elif self.stop_reason and not (task.phase == 'receipt' and self.stop_reason in (
                    'workload-request-failed', 'endpoint-operation-reserve')):
                task.abort(self.stop_reason)
            elif now >= task.deadline and task.deadline < end:
                task.abort('request-deadline')
            elif now >= end:
                normal = task.phase == 'workload' and self.args.workload in ('continuous', 'segments')
                task.abort('completed-window' if normal else 'request-deadline')
            elif now >= task.deadline:
                task.abort('request-deadline')
            elif task.first is None and now - task.started >= 20:
                task.abort('ttfb-deadline')
            if task.terminated and now - task.terminated_at > 5:
                kill_owned([task.proc])
        self.tick()

    def request(self, obj, phase, end, receipt=None):
        self.lease_expires = obj['expires_at']
        if self.operations >= 1024:
            raise Stop('inconclusive', 'budget', 'endpoint-operation-limit')
        # <=20 HTTP operations/s: below the reference's 32/s admission ceiling.
        # Pump existing transfers while pacing; do not block their body pipes.
        while time.monotonic() < min(self.next_operation, end):
            active = [t for t in self.transfers if not t.finished and not t.ready()]
            self.pump(active, end)
            if self.cancelled:
                raise Stop('cancelled', 'process', 'signal')
        if time.monotonic() >= end:
            return None
        self.next_operation = time.monotonic() + .05
        self.operations += 1
        task = Transfer(self, obj, phase, end, receipt)
        return task

    def one(self, obj, phase, end, receipt=None):
        task = self.request(obj, phase, end, receipt)
        if task is None:
            raise Stop('timeout', phase, 'operation-deadline-before-launch')
        while not task.ready():
            self.pump([task], end)
        row = task.finish()
        if self.cancelled:
            raise Stop('cancelled', 'process', 'signal')
        if self.stop_reason and not (phase == 'receipt' and self.stop_reason in (
                'workload-request-failed', 'endpoint-operation-reserve')):
            raise Stop('inconclusive', 'budget', self.stop_reason)
        return task, row

    def core_start(self, selected, startup_end):
        if selected is None:
            return
        # Bind/close leaves a small port race; fail startup rather than retry/fallback.
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        config = {'log': {'level': 'info', 'timestamp': False},
                  'inbounds': [{'type': 'mixed', 'tag': 'screen-in', 'listen': '127.0.0.1', 'listen_port': port}],
                  'outbounds': [selected], 'route': {'final': selected['tag']}}
        # Explicit IPv4 outer bootstrap; no inherited rules/selectors/detours.
        config['outbounds'][0] = dict(selected, domain_resolver={'server': 'bootstrap', 'strategy': 'ipv4_only'})
        config['dns'] = {'servers': [{'type': 'local', 'tag': 'bootstrap'}]}
        self.art.manifest['config_fingerprint'] = fingerprint(config)
        path = self.art.root / 'core.json'
        with path.open('x') as file:
            os.chmod(path, 0o600)
            file.write(json.dumps(config))
        self.art.used += path.stat().st_size
        if self.art.used > self.args.max_disk_bytes - RESERVE:
            raise Stop('inconclusive', 'budget', 'disk-limit')
        code, _ = bounded_command(['sing-box', 'check', '-c', str(path)],
                                  timeout=max(.01, min(10, startup_end - time.monotonic())))
        if code:
            raise Stop('failed', 'core-check', 'core-check-failed')
        self.core = subprocess.Popen(['sing-box', 'run', '-c', str(path), '-D', str(self.art.root)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     env=clean_env(), start_new_session=True)
        self.core_log = self.core.stderr
        os.set_blocking(self.core_log.fileno(), False)
        self.core_log_bytes = 0
        self.selected_kind, self.selected_tag = selected['type'], selected['tag']
        while time.monotonic() < startup_end:
            self.tick()
            if self.core.poll() is not None:
                raise Stop('failed', 'startup', 'core-startup-exited')
            with socket.socket() as check:
                check.settimeout(.1)
                if check.connect_ex(('127.0.0.1', port)) == 0:
                    self.proxy = f'http://127.0.0.1:{port}'
                    return
            time.sleep(.05)
        raise Stop('timeout', 'startup', 'core-startup-deadline')

    def preflight(self, obj, end):
        for attempt in range(2):
            task, row = self.one(obj, 'preflight', min(end, time.monotonic() + 10))
            self.objects.append(task)
            self.art.emit('preflight', attempt=attempt + 1, request=task.operation,
                          outcome=row['outcome'], stage=row['stage'], error=row['error'])
            if row['outcome'] == 'passed':
                return
            if row['http_status'] == 429:
                raise Stop('inconclusive', 'budget', 'endpoint-budget-or-capacity')
            if attempt == 0 and time.monotonic() + 2 < end:
                idle = min(end, time.monotonic() + 2)
                while time.monotonic() < idle:
                    if self.cancelled:
                        raise Stop('cancelled', 'process', 'signal')
                    self.tick()
                    time.sleep(.05)
            else:
                break
        raise Stop('failed', 'response-body', 'preflight-exhausted')

    def workload(self, obj):
        self.work_start = self.tick_at = time.monotonic()
        self.next_tick = self.work_start + 1
        end = self.work_start + self.args.duration
        active, launched, next_fresh = [], 0, self.work_start
        try:
            while True:
                now = time.monotonic()
                if self.cancelled:
                    self.stop_reason = 'cancelled'
                if now < end and not self.stop_reason:
                    maximum = 12 if self.args.workload == 'fresh' else (1 if self.args.workload == 'continuous' else MAX_OBJECTS)
                    while (len(active) < self.args.concurrency and launched < maximum
                           and time.monotonic() < end
                           and (self.args.workload != 'fresh' or now >= next_fresh)):
                        limit = end if self.args.workload == 'continuous' else min(end, time.monotonic() + 30)
                        task = self.request(obj, 'workload', limit)
                        if task is None:
                            break
                        active.append(task)
                        launched += 1
                        next_fresh = self.work_start + launched * self.args.duration / 12
                    if launched >= maximum and not active:
                        if self.args.workload == 'segments':
                            self.stop_reason = 'endpoint-operation-reserve'
                        break
                if not active and (now >= end or self.stop_reason):
                    break
                self.pump(active, end)
                for task in list(active):
                    if task.ready():
                        row = task.finish()
                        self.objects.append(task)
                        active.remove(task)
                        if row['outcome'] not in ('passed', 'completed-window'):
                            # No invisible object retry/tight reconnect after degradation.
                            self.stop_reason = self.stop_reason or 'workload-request-failed'
                if not active and self.args.workload == 'continuous':
                    break
        finally:
            self.tick(force=True)
            self.work_end = time.monotonic()

    def collect(self, end):
        for task in self.objects:
            evidence = {'request': task.operation, 'state': 'incomplete', 'reason': 'missing-support'}
            if 'receipt_url' in task.obj and self.stop_reason not in ('byte-limit', 'disk-limit', 'environment-changed', 'endpoint-expired'):
                for attempt in range(2):
                    if self.cancelled or time.monotonic() >= end or task.obj['expires_at'] - time.time() <= SKEW:
                        evidence['reason'] = 'receipt-deadline-or-expiry'
                        break
                    before = self.operations
                    try:
                        control, row = self.one(task.obj, 'receipt', min(end, time.monotonic() + 4), task.operation)
                    except Stop as error:
                        evidence['reason'] = 'receipt-' + error.code
                        evidence['reads'] = attempt + int(self.operations > before)
                        break
                    evidence['reads'] = attempt + 1
                    if row['outcome'] != 'passed':
                        evidence['reason'] = 'receipt-read-failed'
                        break
                    try:
                        value = json.loads(control.buffers['control'])
                        require(set(value) == {'run', 'request', 'source', 'object', 'utc_start',
                                               'body_bytes_sent', 'elapsed_s', 'outcome'}, 'receipt-schema')
                        require(value['run'] == task.obj['run_id'] and value['request'] == task.operation
                                and value['object'] == urlsplit(task.obj['https_url']).path.split('/')[-1], 'receipt-binding')
                        ipaddress.IPv4Address(value['source'])
                        require(type(value['body_bytes_sent']) is int
                                and 0 <= value['body_bytes_sent'] <= task.obj['object_bytes'], 'receipt-bytes')
                        for key in ('utc_start', 'elapsed_s'):
                            require(type(value[key]) in (int, float) and math.isfinite(value[key])
                                    and value[key] >= 0, 'receipt-timing')
                        require(value['outcome'] in ('active', 'complete', 'interrupted', 'deadline',
                                                     'expired', 'budget-or-expiry'), 'receipt-outcome')
                        require(value['outcome'] != 'complete'
                                or value['body_bytes_sent'] == task.obj['object_bytes'], 'receipt-length')
                    except (Stop, ValueError, TypeError, KeyError):
                        evidence['reason'] = 'receipt-mismatch'
                        break
                    if value['outcome'] != 'active':
                        evidence.update(state='finalized', reason=None, server_outcome=value['outcome'],
                                        body_bytes_sent=value['body_bytes_sent'])
                        # Source mappings live only in the private manifest, never JSONL/summary.
                        self.art.manifest.setdefault('receipt_sources', {})[task.operation] = value['source']
                        break
                    evidence['reason'] = 'still-active'
                    if attempt == 0 and time.monotonic() + .2 < end:
                        time.sleep(.2)
            self.receipts.append(evidence)
            self.art.emit('route-evidence', receipt=evidence, selected_outbound_log=self.selected_log_seen,
                          underlay='unverified', outer_connections=None)

    def cleanup(self):
        if self.cleaned:
            return
        self.cleaned = True
        kill_owned([t.proc for t in self.transfers if not t.finished] + ([self.core] if self.core else []))
        for task in self.transfers:
            if not task.finished:
                task.reason = task.reason or ('cancelled' if self.cancelled else 'process-aborted')
                # Preserve partial counters for abrupt local/disk failures; never invent EOF.
                task.finish()
                if task.receipt is None and task not in self.objects:
                    self.objects.append(task)
            for file in task.files:
                file.close()
        if self.core_log:
            self.core_log.close()
        self.selector.close()
        path = self.art.root / 'core.json'
        if path.exists():
            self.art.used -= path.stat().st_size
            path.unlink()


def windows(progress, planned, observed):
    def window(start, end):
        start, end = max(10, start), min(planned, end)
        if end <= start:
            return {'start_s': start, 'end_s': end, 'coverage': 'missing', 'goodput_mbit_s': None}
        received = 0.0
        for row in progress:
            right = row['workload_elapsed_s']
            left = right - row['interval_s']
            overlap = max(0, min(right, end) - max(left, start))
            received += row['body_bytes_delta'] * overlap / row['interval_s']
        coverage = 'full' if observed >= end else ('missing' if observed <= start else 'partial')
        return {'start_s': start, 'end_s': end, 'coverage': coverage,
                'body_bytes': received if coverage != 'missing' else None,
                'goodput_mbit_s': (8 * received / (min(observed, end) - start) / 1e6)
                if coverage != 'missing' else None}
    ten = [window(s, s + 10) for s in range(10, math.ceil(planned), 10)]
    for row in ten:
        if row['end_s'] - row['start_s'] < 10 and row['coverage'] == 'full':
            row['coverage'] = 'partial'
    return {'ten_second': ten,
            'first': window(10, 70), 'middle': window(planned / 2 - 30, planned / 2 + 30),
            'last': window(planned - 60, planned),
            'estimator': 'overlap-weighted monotonic one-second samples; missing is not zero-fill'}


def summarize(runner, terminal):
    observed = 0 if runner.work_start is None else max(0, (runner.work_end or time.monotonic()) - runner.work_start)
    view = windows(runner.progress, runner.args.duration, observed)
    failed = [r for r in runner.results if r['outcome'] not in ('passed', 'completed-window')]
    breach = next((w for w in view['ten_second'] if w['coverage'] == 'full' and w['goodput_mbit_s'] < 10), None)
    if runner.args.workload == 'fresh':
        breach = None
    scope = 'fresh reachability only' if runner.args.workload == 'fresh' else 'controlled TCP, not services/DPI'
    if terminal is None:
        if runner.cancelled:
            terminal = Stop('cancelled', 'process', 'signal')
        elif runner.stop_reason and runner.stop_reason != 'workload-request-failed':
            terminal = Stop('cancelled' if runner.stop_reason == 'cancelled' else 'inconclusive',
                            'process' if runner.stop_reason == 'cancelled' else 'budget', runner.stop_reason)
        elif failed:
            first = failed[0]
            endpoint_constraint = first['http_status'] == 429
            terminal = Stop('inconclusive' if endpoint_constraint else first['outcome'],
                            'budget' if endpoint_constraint else first['stage'],
                            'endpoint-budget-or-capacity' if endpoint_constraint else first['error'])
        elif runner.stop_reason:
            terminal = Stop('cancelled' if runner.stop_reason == 'cancelled' else 'inconclusive',
                            'budget', runner.stop_reason)
        elif breach:
            terminal = Stop('failed', 'response-body', 'sustained-window-below-10-mbit')
        else:
            terminal = Stop('route-unverified', 'route', 'controller-underlay-proof-required')
    stalls = [s for r in runner.results for s in r['stalls']]
    tt = [r['ttfb_s'] for r in runner.results if r['ttfb_s'] is not None]
    return {'schema_version': 1, 'outcome': terminal.outcome, 'stage': terminal.stage,
            'error': terminal.code, 'scope': scope, 'route_proof': 'unverified',
            'workload': runner.args.workload, 'planned_s': runner.args.duration, 'observed_s': observed,
            'bytes': runner.bytes, 'attempted': len(runner.results),
            'completed': sum(r['outcome'] == 'passed' for r in runner.results),
            'completed_windows': sum(r['outcome'] == 'completed-window' for r in runner.results),
            'failed': len(failed),
            'preflight_attempted': sum(r['phase'] == 'preflight' for r in runner.all_results),
            'preflight_failed': sum(r['phase'] == 'preflight' and r['outcome'] != 'passed'
                                    for r in runner.all_results),
            'control_failed': sum(r['phase'] == 'receipt' and r['outcome'] != 'passed'
                                  for r in runner.all_results),
            'partial_bytes': sum(r['received_bytes'] for r in runner.results
                                                      if r['integrity'] != 'verified'),
            'ttfb_s': {'minimum': min(tt) if tt else None, 'maximum': max(tt) if tt else None},
            'longest_stall_s': max((s['duration_s'] for s in stalls), default=0),
            'open_stalls': sum(s['censored'] for s in stalls), 'stalls': stalls,
            'windows': view, 'first_threshold_breach': None if breach is None else breach | {
                'detected_at_s': breach['end_s'],
                'bytes_at_detection_estimate': sum(p['body_bytes_delta'] * max(0, min(1,
                    (breach['end_s'] - p['workload_elapsed_s'] + p['interval_s']) / p['interval_s']))
                    for p in runner.progress)},
            'first_transport_failure': next((r for r in failed if r['error'] and
                                             ((r['curl_exit'] not in (0, None) and r['termination'] != 'runner-sigterm')
                                              or 'deadline' in r['error'])), None),
            'reconnects': 'not automatically retried', 'outer_connection_reuse': 'unknown',
            'recovery': 'unknown/not run', 'receipts_finalized': sum(r['state'] == 'finalized' for r in runner.receipts),
            'receipts_incomplete': len(runner.objects) - sum(r['state'] == 'finalized' for r in runner.receipts),
            'operations': runner.operations, 'capacity_qualification': 'not qualified',
            'endpoint_capacity': 'uncalibrated', 'remote_resources': 'unknown'}


def human(summary):
    return ('# TCP screen\n\n'
            f"Outcome: **{summary['outcome']}** ({summary['stage']}/{summary['error']}).\n\n"
            f"Workload: {summary['workload']}; planned {summary['planned_s']} s; "
            f"observed {summary['observed_s']:.3f} s.\n"
            f"Requests: {summary['attempted']} attempted, {summary['completed']} complete, "
            f"{summary['completed_windows']} completed-window, {summary['failed']} failed.\n"
            f"Preflight: {summary['preflight_attempted']} attempts, {summary['preflight_failed']} failed. "
            f"Receipt evidence: {summary['receipts_finalized']} final, {summary['receipts_incomplete']} incomplete.\n"
            f"Body bytes: {summary['bytes']}. Longest stall: {summary['longest_stall_s']:.3f} s "
            f"({summary['open_stalls']} open/censored).\n\n"
            + ''.join(f"{name.title()} planned window: {summary['windows'][name]['coverage']}, "
                      f"{summary['windows'][name]['goodput_mbit_s']} Mbit/s.\n" for name in ('first', 'middle', 'last'))
            + f"\nFirst threshold breach: {summary['first_threshold_breach']}.\n"
            f"TTFB range: {summary['ttfb_s']}. Transport failure time/bytes: "
            + (f"{summary['first_transport_failure']['workload_elapsed_s']} s / "
               f"{summary['first_transport_failure']['workload_bytes_at_end']} bytes.\n\n"
               if summary['first_transport_failure'] else 'none observed.\n\n')
            + f"Scope: {summary['scope']}. Route unverified; capacity unqualified. "
            'Outer reuse/recovery and remote resources unknown. See summary.json for planned windows.\n')


def validate_args(args):
    require(args.route in ALIASES, 'route-alias')
    require(math.isfinite(args.duration) and 0 < args.duration <= 600, 'duration-limit')
    require(1 <= args.concurrency <= 4 and (args.workload == 'segments' or args.concurrency == 1), 'concurrency')
    require(1 <= args.rate_limit <= 4194304 and args.rate_limit >= args.concurrency, 'rate-limit')
    require(1 <= args.max_bytes <= 3221225472, 'byte-limit')
    require(2 * RESERVE <= args.max_disk_bytes <= 67108864, 'disk-limit')
    require(not (args.worker_input and any((args.endpoint_file, args.preflight_endpoint_file,
                                           args.vault_file, args.vault_password_file, args.extra_outbounds_file))),
            'worker-controller-input-mix')


def read_inputs(args):
    if args.worker_input:
        require(not args.prepare_worker, 'worker-prepare-conflict')
        data = load_json(args.worker_input, credential=True)
        require(set(data) == {'schema_version', 'route', 'outbound', 'endpoint', 'preflight'}
                and data['schema_version'] == 1 and data['route'] == args.route, 'worker-schema')
        selected = data['outbound']
        if args.route == 'direct':
            require(selected is None, 'direct-outbound')
        else:
            outbound(selected, args.route)
        obj = endpoint(data['endpoint'], credential=True)
        pre = endpoint(data['preflight'], credential=True)
    else:
        if not args.endpoint_file:
            raise Stop('skipped', 'input', 'missing-endpoint-input')
        obj = endpoint(load_json(args.endpoint_file))
        if args.workload != 'fresh' and not args.preflight_endpoint_file:
            raise Stop('skipped', 'input', 'missing-preflight-input')
        pre = endpoint(load_json(args.preflight_endpoint_file)) if args.preflight_endpoint_file else obj
        selected = select_outbound(args)
    same_lease(obj, pre)
    if args.workload == 'continuous':
        require(obj['object_bytes'] > args.max_bytes, 'continuous-object-must-exceed-byte-cap')
    elif args.workload == 'segments':
        require(obj['object_bytes'] + 2 * pre['object_bytes'] < args.max_bytes, 'segment-budget')
    return obj, pre, selected


def execute(args):
    os.umask(0o077)
    validate_args(args)
    art = Artifacts(args)
    runner = Runner(args, art)
    terminal = None
    old_signals = {}
    def cancel(_signum, _frame):
        runner.cancelled = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        old_signals[sig] = signal.signal(sig, cancel)
    try:
        obj, pre, selected = read_inputs(args)
        art.envelope.update(run=obj['run_id'], endpoint=obj['alias'])
        art.emit('run-start', outcome=None, stage='input')
        bootstrap_dns = 'not applicable (direct route)'
        if selected:
            try:
                ipaddress.ip_address(selected['server'])
                bootstrap_dns = 'not exercised (IP-literal server; verification names retained)'
            except ValueError:
                bootstrap_dns = 'local IPv4 resolver, independent of selected tunnel; upstream unknown'
        try:
            ipaddress.ip_address(origin(obj['https_url'])[1])
            destination_dns = 'not exercised (IP-literal HTTPS origin)'
        except ValueError:
            destination_dns = 'local resolver' if selected is None else 'CONNECT name to outbound; resolution location unknown'
        art.manifest.update(endpoint=obj['alias'], endpoint_location=obj['location'], family=obj['family'],
                            expires_at=obj['expires_at'], selected_config_shape=fingerprint(selected),
                            dns={'bootstrap': bootstrap_dns, 'destination': destination_dns},
                            outer_family='ipv4', inner_family='ipv4', proxy_environment_present=any(
                                k.lower().endswith('_proxy') for k in os.environ))
        remaining = lifetime(obj, 30 + args.duration + 20 + 10)
        art.manifest['lease_remaining_at_validation_s'] = remaining
        if args.prepare_worker:
            require(not args.worker_input, 'worker-prepare-conflict')
            # Controller-only handoff. CA path is explicit, not silently rewritten on read.
            bundle = {'schema_version': 1, 'route': args.route, 'outbound': selected,
                      'endpoint': dict(obj, ca_file='/run/credentials/vpn-screen.service/ca.pem'),
                      'preflight': dict(pre, ca_file='/run/credentials/vpn-screen.service/ca.pem')}
            art.atomic('worker.json', bundle)
            with (art.root / 'ca.pem').open('xb') as file:
                os.chmod(art.root / 'ca.pem', 0o600)
                file.write(private_file(obj['ca_file']).read_bytes())
            art.used += (art.root / 'ca.pem').stat().st_size
            terminal = Stop('skipped', 'input', 'prepared-worker-no-network')
        else:
            if obj['family'] == 'ipv6':
                raise Stop('unsupported', 'route', 'no-ipv6-underlay')
            if os.geteuid() in (0, 946):
                raise Stop('route-unverified', 'route', 'isolated-unprivileged-worker-required')
            if not args.gate:
                raise Stop('route-unverified', 'route', 'reviewed-controller-gate-required')
            gate = safe_path(args.gate)
            require(not gate.exists(), 'gate-must-start-absent')
            art.emit('route-evidence', ready=True, uid=os.geteuid(), gid=os.getegid(),
                     groups=os.getgroups(), pid=os.getpid(), network_namespace=os.readlink('/proc/self/ns/net'),
                     underlay='unverified', stage='route', outcome='route-unverified')
            # No packets before release; gate wait is part of the 30 s startup budget.
            startup_end = time.monotonic() + 30
            while not gate.exists():
                if runner.cancelled:
                    raise Stop('cancelled', 'route', 'signal-before-gate')
                if time.monotonic() >= startup_end:
                    raise Stop('route-unverified', 'route', 'gate-deadline')
                time.sleep(.05)
            require(not gate.is_symlink() and gate.is_file() and gate.stat().st_uid in (0, os.geteuid())
                    and not gate.stat().st_mode & 0o022, 'unsafe-gate')
            runner.baseline = environment()
            art.manifest['environment_baseline'] = runner.baseline
            art.manifest['baseline_host_sample'] = host_sample()
            for tool in ('curl', 'sing-box'):
                try:
                    code, raw = bounded_command([tool, '--version' if tool == 'curl' else 'version'], timeout=2)
                    art.manifest[tool + '_version'] = raw.decode().splitlines()[0] if code == 0 else 'unknown'
                except (OSError, Stop):
                    art.manifest[tool + '_version'] = 'unknown'
            runner.core_start(selected, startup_end)
            runner.preflight(pre, startup_end)
            art.manifest['lease_remaining_before_workload_s'] = lifetime(obj, args.duration + 20 + 10)
            runner.workload(obj)
            runner.collect(min(art.start + 650, time.monotonic() + 20,
                               time.monotonic() + obj['expires_at'] - time.time() - SKEW))
    except Stop as error:
        terminal = error
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        terminal = Stop('failed', 'input' if runner.work_start is None else 'process', 'redacted-local-error')
    finally:
        try:
            runner.cleanup()
        except (OSError, Stop, subprocess.SubprocessError):
            terminal = Stop('inconclusive', 'cleanup', 'owned-process-cleanup-failed')
        summary = summarize(runner, terminal)
        try:
            art.emit('run-end', outcome=summary['outcome'], stage=summary['stage'], error=summary['error'])
            art.atomic('summary.json', summary)
            art.atomic('SUMMARY.md', human(summary))
            art.manifest.update(complete=True, outcome=summary['outcome'], operations=runner.operations,
                                final_host_sample=host_sample(), selected_outbound_log=runner.selected_log_seen,
                                outer_connection_count=None, python_version=sys.version.split()[0])
            art.atomic('manifest.json', art.manifest)
        finally:
            art.close()
            for sig, previous in old_signals.items():
                signal.signal(sig, previous)
    return summary


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--route', required=True, choices=ALIASES)
    p.add_argument('--workload', required=True, choices=('fresh', 'continuous', 'segments'))
    p.add_argument('--endpoint-file')
    p.add_argument('--preflight-endpoint-file')
    p.add_argument('--vault-file')
    p.add_argument('--vault-password-file')
    p.add_argument('--extra-outbounds-file')
    p.add_argument('--worker-input')
    p.add_argument('--prepare-worker', action='store_true')
    p.add_argument('--gate')
    p.add_argument('--duration', type=float, required=True)
    p.add_argument('--concurrency', type=int, default=1)
    p.add_argument('--rate-limit', type=int, default=4194304)
    p.add_argument('--max-bytes', type=int, default=3221225472)
    p.add_argument('--max-disk-bytes', type=int, default=67108864)
    p.add_argument('--output', required=True)
    return p


def main():
    args = parser().parse_args()
    try:
        summary = execute(args)
    except (Stop, OSError, ValueError):
        print('screen: invalid limits or unsafe output; no network started', file=sys.stderr)
        return 2
    print(f"screen: {summary['outcome']} ({summary['stage']}/{summary['error']})")
    return 0 if summary['outcome'] in ('passed', 'route-unverified', 'skipped') else 1


if __name__ == '__main__':
    sys.exit(main())
