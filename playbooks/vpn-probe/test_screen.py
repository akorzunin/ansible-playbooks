"""Offline + real curl/TLS tests. No Internet, privileged launch or active service.

Fixture trust/keys/output live in private TemporaryDirectory instances. Only
127.0.0.1 is bound; every server, process and directory is cleaned in finally.
"""
import argparse
import contextlib
import copy
import hashlib
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import select
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('screen', Path(__file__).with_name('screen.py'))
screen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(screen)


def args(root, **values):
    data = dict(route='direct', workload='fresh', duration=.8, concurrency=1,
                rate_limit=4194304, max_bytes=1048576, max_disk_bytes=1048576,
                output=str(root / 'output'), endpoint_file=None, preflight_endpoint_file=None,
                vault_file=None, vault_password_file=None, extra_outbounds_file=None,
                worker_input=None, prepare_worker=False, gate=None)
    return argparse.Namespace(**(data | values))


def descriptor(root, **values):
    ca = root / 'ca.pem'
    if not ca.exists():
        ca.write_text('fixture CA placeholder, validation-only test')
        ca.chmod(0o600)
    data = dict(schema_version=1, alias='reference-local', https_url='https://127.0.0.1:9443/objects/fresh',
                auth_header='Authorization: Bearer object-token', family='ipv4', expected_status=200,
                content_type='application/octet-stream', object_bytes=4096,
                sha256=hashlib.sha256(b'x' * 4096).hexdigest(), cache_policy='no-store, no-transform',
                receipt_url='https://127.0.0.1:9443/receipts/{request}',
                receipt_auth_header='Authorization: Bearer receipt-token', location='vpn-host',
                ca_file=str(ca), run_id='local-run', expires_at=int(time.time()) + 900)
    return data | values


def save(path, data):
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return str(path)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.obj = descriptor(self.root)

    def test_execute_startup_matches_controller_without_releasing_gate(self):
        spec = importlib.util.spec_from_file_location('controller', Path(__file__).with_name('controller.py'))
        controller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(controller)
        a = args(self.root, gate=str(self.root / 'go'))
        expected = dict(run=self.obj['run_id'], route=a.route, endpoint=self.obj['alias'])
        emit = screen.Artifacts.emit
        observed = []

        def inspect(art, event, **fields):
            emit(art, event, **fields)
            if event == 'route-evidence':
                observed.append(controller.poll_ready(art.root / 'events.jsonl', lambda: True, expected))
                raise screen.Stop('cancelled', 'route', 'offline-stop-before-gate')

        with patch.object(screen, 'read_inputs', return_value=(self.obj, self.obj, None)), \
                patch.object(screen.os, 'geteuid', return_value=1000), \
                patch.object(screen.Artifacts, 'emit', inspect), \
                patch('socket.socket', side_effect=AssertionError('no network')):
            summary = screen.execute(a)
        self.assertEqual(observed[0]['status'], 'ready-candidate')
        self.assertEqual(observed[0]['non_ready_records'], 1)
        self.assertEqual(summary['outcome'], 'cancelled')
        self.assertFalse((self.root / 'go').exists())
        rows = [json.loads(row) for row in (Path(a.output) / 'events.jsonl').read_text().splitlines()]
        self.assertTrue(all(all(row[k] == v for k, v in expected.items()) for row in rows))

    def test_pre_input_failure_retains_terminal_artifacts(self):
        a = args(self.root)
        with patch.object(screen, 'read_inputs', side_effect=screen.Stop('failed', 'input', 'invalid-input')):
            summary = screen.execute(a)
        self.assertEqual(summary['outcome'], 'failed')
        rows = [json.loads(row) for row in (Path(a.output) / 'events.jsonl').read_text().splitlines()]
        self.assertEqual([row['event'] for row in rows], ['run-end'])
        self.assertEqual(rows[0]['stage'], 'input')
        self.assertTrue(json.loads((Path(a.output) / 'manifest.json').read_text())['complete'])
        self.assertTrue((Path(a.output) / 'summary.json').is_file())

    def test_descriptor_strict_schema_and_injection(self):
        self.assertEqual(screen.endpoint(self.obj), self.obj)
        changes = [dict(unknown=True), dict(schema_version=True), dict(alias='../private'),
                   dict(https_url='http://127.0.0.1/'), dict(https_url='https://user:pass@localhost/'),
                   dict(https_url='https://localhost/#secret'), dict(https_url='https://localhost/"\nproxy=x'),
                   dict(auth_header='Authorization: Bearer token\r\nX-Bad: yes'),
                   dict(auth_header='X-Run-ID: evil'), dict(run_id='bad\nvalue'),
                   dict(object_bytes=True), dict(object_bytes=0), dict(object_bytes=4294967297),
                   dict(sha256='wrong'), dict(expires_at=1.5), dict(expected_status=302),
                   dict(cache_policy='public'), dict(content_type='text/html'), dict(family='any'),
                   dict(receipt_url='https://elsewhere/receipts/{request}'),
                   dict(receipt_url='https://127.0.0.1:9443/receipts/{request}?token=x'),
                   dict(receipt_url='https://127.0.0.1:9443/{run}/{request}'),
                   dict(receipt_url='https://127.0.0.1:9443/receipts/{request}/suffix')]
        for change in changes:
            with self.subTest(change=list(change)), self.assertRaises((screen.Stop, ValueError)):
                screen.endpoint(self.obj | change)

    def test_private_and_systemd_credential_loaders_are_distinct(self):
        path = self.root / 'worker.json'
        save(path, {'selected': True})
        self.assertEqual(screen.load_json(path), {'selected': True})
        path.chmod(0o440)
        with self.assertRaises(screen.Stop):
            screen.load_json(path)
        with patch.dict(os.environ, CREDENTIALS_DIRECTORY=str(self.root)):
            with patch.object(screen.os, 'statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                self.assertEqual(screen.load_json(path, True), {'selected': True})
                info = path.stat()
                root_acl_meta = dict(st_mode=info.st_mode, st_size=info.st_size, st_uid=0, st_gid=0)
                with patch.object(Path, 'stat', return_value=SimpleNamespace(**root_acl_meta)):
                    self.assertEqual(screen.load_json(path, True), {'selected': True})
                for changed in ({'st_uid': os.geteuid() + 1}, {'st_gid': os.getegid() + 1}):
                    with patch.object(Path, 'stat', return_value=SimpleNamespace(**(root_acl_meta | changed))):
                        with self.assertRaises(screen.Stop):
                            screen.load_json(path, True)
                path.chmod(0o644)
                with self.assertRaises(screen.Stop):
                    screen.load_json(path, True)
                path.chmod(0o440)
                save(self.root / 'unselected.json', {})
                with self.assertRaises(screen.Stop):
                    screen.load_json(self.root / 'unselected.json', True)
            with patch.object(screen.os, 'statvfs', return_value=SimpleNamespace(f_flag=0)):
                with self.assertRaises(screen.Stop):
                    screen.load_json(path, True)
        link = self.root / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(screen.Stop):
            screen.load_json(link / 'worker.json')

    def test_output_private_new_and_disk_limits(self):
        a = args(self.root)
        screen.validate_args(a)
        art = screen.Artifacts(a)
        try:
            self.assertEqual(art.root.stat().st_mode & 0o777, 0o700)
            art.used = a.max_disk_bytes - screen.RESERVE
            with self.assertRaises(screen.Stop):
                art.emit('progress', body_bytes_delta=0)
            art.emit('run-end', outcome='inconclusive')
            art.atomic('summary.json', {'outcome': 'inconclusive'})
            self.assertLess(sum(p.stat().st_size for p in art.root.iterdir()), a.max_disk_bytes)
        finally:
            art.close()
        with self.assertRaises(FileExistsError):
            screen.Artifacts(a)
        for p in art.root.iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        public = self.root / 'public'
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        with self.assertRaises(screen.Stop):
            screen.Artifacts(args(public))

    def test_argument_limits_before_network(self):
        for changes in (dict(duration=0), dict(duration=float('nan')), dict(duration=601),
                        dict(concurrency=4), dict(workload='continuous', concurrency=2),
                        dict(rate_limit=0), dict(rate_limit=4194305), dict(max_bytes=0),
                        dict(max_bytes=3221225473), dict(max_disk_bytes=0),
                        dict(max_disk_bytes=67108865), dict(route='selector'),
                        dict(worker_input='worker', vault_file='vault')):
            with self.subTest(changes=changes), self.assertRaises(screen.Stop):
                screen.validate_args(args(self.root, **changes))

    def test_lease_preflight_and_expiry_constraints(self):
        screen.same_lease(self.obj, self.obj)
        for key, value in (('run_id', 'another'), ('ca_file', '/tmp/different'),
                           ('expires_at', self.obj['expires_at'] + 1), ('auth_header', 'different'),
                           ('https_url', 'https://127.0.0.2:9443/objects/fresh'), ('object_bytes', 65537)):
            with self.subTest(key=key), self.assertRaises(screen.Stop):
                screen.same_lease(self.obj, self.obj | {key: value})
        now = self.obj['expires_at'] - 60
        self.assertEqual(screen.lifetime(self.obj, 50, now), 60)
        for now in (self.obj['expires_at'] - 54, self.obj['expires_at']):
            with self.assertRaises(screen.Stop) as caught:
                screen.lifetime(self.obj, 50, now)
            self.assertEqual(caught.exception.outcome, 'inconclusive')
            self.assertEqual(caught.exception.stage, 'budget')
        a = args(self.root, workload='continuous', endpoint_file=save(self.root / 'endpoint.json', self.obj))
        with self.assertRaises(screen.Stop) as caught:
            screen.read_inputs(a)
        self.assertEqual(caught.exception.code, 'missing-preflight-input')

    def test_outbound_sources_and_ambiguity(self):
        selected = dict(type='ssh', tag='cherry-ssh', server='192.0.2.1', server_port=22,
                        user='probe', password='never-print', host_key=['host-pin'])
        export = save(self.root / 'outbounds.json', [selected])
        a = args(self.root, route='cherry-ssh', extra_outbounds_file=export)
        self.assertEqual(screen.select_outbound(a), selected)
        for changed in ([selected, selected], [selected | {'tag': 'unknown'}],
                        [selected | {'detour': 'direct'}], [selected | {'type': 'selector'}]):
            save(Path(export), changed)
            with self.assertRaises(screen.Stop):
                screen.select_outbound(a)
        with self.assertRaises(screen.Stop) as caught:
            screen.select_outbound(args(self.root, route='cherry-ssh'))
        self.assertEqual(caught.exception.outcome, 'skipped')
        save(Path(export), [selected])
        vault_path = self.root / 'vault'
        vault_path.write_text('$ANSIBLE_VAULT;1.1;AES256\nfixture-ciphertext\n')
        vault_path.chmod(0o644)
        vault = str(vault_path)
        pw = save(self.root / 'pw', {})
        parsed = {'connections': {}, 'extra_outbounds': [selected]}
        with patch.object(screen, 'bounded_command', side_effect=[(0, b'private YAML'), (0, json.dumps(parsed).encode())]):
            with self.assertRaises(screen.Stop) as caught:
                screen.select_outbound(args(self.root, route='cherry-ssh', extra_outbounds_file=export,
                                            vault_file=vault, vault_password_file=pw))
        self.assertEqual(caught.exception.code, 'ambiguous-route-source')

    @unittest.skipUnless(shutil.which('ansible-vault'), 'existing Ansible required')
    def test_real_vault_selection_offline_without_token_export(self):
        pw = self.root / 'password'
        pw.write_text('fixture-password\n')
        pw.chmod(0o600)
        selected = dict(type='ssh', tag='ssh', server='192.0.2.1', server_port=22,
                        user='probe', password='fixture-probe-secret', host_key=['fixture-host-pin'])
        # JSON is a YAML subset. Encrypt/decrypt with real existing Ansible, no network.
        vault = self.root / 'fixture.vault'
        save(vault, {'sing_box_secrets': {'connections': {'ssh': selected},
                                        'tokens': {'never_export': 'profile-token'}}})
        (self.root / 'ansible.cfg').write_text('')
        subprocess.run(['ansible-vault', 'encrypt', str(vault), '--vault-password-file', str(pw)],
                       check=True, capture_output=True, timeout=10,
                       env=screen.clean_env() | {'HOME': str(self.root), 'ANSIBLE_LOCAL_TEMP': str(self.root / 'tmp'),
                                                 'ANSIBLE_CONFIG': str(self.root / 'ansible.cfg')})
        vault.chmod(0o644)  # Tracked ciphertext need not be private plaintext.
        result = screen.select_outbound(args(self.root, route='nt1-ssh', vault_file=str(vault),
                                              vault_password_file=str(pw)))
        self.assertEqual(result, selected)
        self.assertNotIn('profile-token', json.dumps(result))
        self.assertTrue(vault.read_text().startswith('$ANSIBLE_VAULT;'))

    def test_fingerprint_does_not_hash_secret_equality(self):
        one = dict(type='ssh', tag='ssh', password='a', server='one', host_key=['one'])
        two = one | dict(password='b', server='two', host_key=['two'])
        self.assertEqual(screen.fingerprint(one), screen.fingerprint(two))
        self.assertNotEqual(screen.fingerprint(one), screen.fingerprint(one | {'type': 'naive'}))

    def test_config_secret_serialization_and_environment(self):
        obj = self.obj | {'https_url': 'https://localhost/path?secret="quoted"'}
        config = screen.curl_config(obj, 'op-1', None, 100, 1, 10, 11).decode()
        self.assertIn('secret=\\"quoted\\"', config)
        self.assertIn('noproxy = "*"', config)
        self.assertIn('proxy = ""', config)
        self.assertNotIn('insecure', config)
        self.assertNotIn('location\n', config)
        tunneled = screen.curl_config(obj, 'op-2', 'http://127.0.0.1:10000', 25, 1, 10, 11).decode()
        self.assertIn('noproxy = ""', tunneled)
        self.assertIn('limit-rate = "25"', tunneled)
        with patch.dict(os.environ, HTTPS_PROXY='http://must-not-inherit'):
            self.assertNotIn('HTTPS_PROXY', screen.clean_env())
        for value in ('x\ny', 'x\ry', '\x00'):
            with self.assertRaises(screen.Stop):
                screen.curl_quote(value)

    def test_http_rejection_matrix_and_malformed_metrics(self):
        def headers(status=200, content_type='application/octet-stream', encoding='', length='4096'):
            return (f'HTTP/1.1 {status} Test\r\nContent-Type: {content_type}\r\nContent-Length: {length}\r\n'
                    'Cache-Control: no-store, no-transform\r\n' + encoding + '\r\n').encode()
        self.assertEqual(screen.content_check(self.obj, headers()), (None, 200))
        for raw, expected in ((headers(403), 'http-status'), (headers(401), 'authentication'),
                              (headers(302), 'redirect'), (headers(content_type='text/html'), 'content-type'),
                              (headers(encoding='Content-Encoding: gzip\r\n'), 'content-encoding'),
                              (headers(length='3'), 'unexpected-length'),
                              (headers().replace(b'no-store, no-transform', b'public'), 'cache-policy')):
            self.assertEqual(screen.content_check(self.obj, raw)[0], expected)
        with self.assertRaises(screen.Stop):
            screen.parse_headers(headers().replace(b'\r\n\r\n', b'\r\nContent-Length: 4096\r\n\r\n'))
        for raw in (b'', b'not json', b'{"url":"secret"}', b'null', b'[]'):
            with self.assertRaises((screen.Stop, TypeError)):
                screen.parse_metrics(raw)

    def test_planned_monotonic_windows_zeros_and_early_end(self):
        progress = [dict(workload_elapsed_s=i, interval_s=1, body_bytes_delta=2000000 if i < 21 else 0)
                    for i in range(1, 32)]
        view = screen.windows(progress, 600, 31)
        self.assertEqual(view['middle']['start_s'], 270)
        self.assertEqual(view['last']['start_s'], 540)
        self.assertEqual(view['middle']['coverage'], 'missing')
        self.assertIsNone(view['last']['goodput_mbit_s'])
        self.assertEqual(view['ten_second'][1]['goodput_mbit_s'], 0)
        self.assertEqual(view['ten_second'][2]['coverage'], 'partial')
        irregular = [dict(workload_elapsed_s=12, interval_s=2, body_bytes_delta=1000000)]
        self.assertEqual(screen.windows(irregular, 20, 20)['ten_second'][0]['goodput_mbit_s'], .8)

    def test_failed_preflight_still_has_private_terminal_artifacts(self):
        obj = self.obj | {'expires_at': int(time.time()) - 1, 'auth_header': 'Authorization: Bearer highly-secret'}
        a = args(self.root, endpoint_file=save(self.root / 'endpoint.json', obj))
        with patch.object(screen.subprocess, 'Popen') as popen:
            summary = screen.execute(a)
        popen.assert_not_called()
        self.assertEqual(summary['outcome'], 'inconclusive')
        self.assertIn('endpoint-expired', summary['error'])
        for name in ('events.jsonl', 'summary.json', 'SUMMARY.md', 'manifest.json'):
            content = (Path(a.output) / name).read_text()
            self.assertNotIn('highly-secret', content)
            self.assertNotIn('https://', content)
            self.assertEqual((Path(a.output) / name).stat().st_mode & 0o777, 0o600)
        self.assertTrue(json.loads((Path(a.output) / 'manifest.json').read_text())['complete'])

    def test_missing_input_and_no_gate_never_start_network(self):
        with patch.object(screen.subprocess, 'Popen') as popen:
            summary = screen.execute(args(self.root))
        self.assertEqual(summary['outcome'], 'skipped')
        popen.assert_not_called()
        a = args(self.root, output=str(self.root / 'no-gate'),
                 endpoint_file=save(self.root / 'endpoint.json', self.obj))
        with patch.object(screen.subprocess, 'Popen') as popen:
            summary = screen.execute(a)
        self.assertEqual(summary['outcome'], 'route-unverified')
        popen.assert_not_called()

    def test_offline_worker_handoff_contains_only_selected_material(self):
        a = args(self.root, endpoint_file=save(self.root / 'endpoint.json', self.obj), prepare_worker=True)
        with patch.object(screen.subprocess, 'Popen') as popen:
            summary = screen.execute(a)
        popen.assert_not_called()
        self.assertEqual(summary['error'], 'prepared-worker-no-network')
        bundle = json.loads((Path(a.output) / 'worker.json').read_text())
        self.assertIsNone(bundle['outbound'])
        self.assertEqual(bundle['endpoint']['ca_file'], '/run/credentials/vpn-screen.service/ca.pem')
        self.assertNotIn('tokens', bundle)
        self.assertNotIn('vault', json.dumps(bundle))

    def test_bounded_subprocess_buffer_timeout_and_group_cleanup(self):
        with self.assertRaises(screen.Stop) as caught:
            screen.bounded_command([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=.1)
        self.assertEqual(caught.exception.outcome, 'timeout')
        with patch.object(screen, 'BUFFER', 1024):
            with self.assertRaises(screen.Stop) as caught:
                screen.bounded_command([sys.executable, '-c', 'print("x"*8192)'])
        self.assertEqual(caught.exception.code, 'diagnostic-buffer-limit')
        code, raw = screen.bounded_command([sys.executable, '-c',
                                           'import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(d)'],
                                          payload=b'x' * 100000)
        self.assertEqual((code, len(raw)), (0, 100000))

    def test_real_core_check_minimal_profile_no_network(self):
        if not shutil.which('sing-box'):
            self.skipTest('sing-box unavailable')
        profile = {'log': {'level': 'info'},
                   'inbounds': [{'type': 'mixed', 'listen': '127.0.0.1', 'listen_port': 12000}],
                   'outbounds': [{'type': 'ssh', 'tag': 'ssh', 'server': '192.0.2.1', 'server_port': 22,
                                  'user': 'test', 'password': 'test',
                                  'domain_resolver': {'server': 'bootstrap', 'strategy': 'ipv4_only'}}],
                   'route': {'final': 'ssh'}, 'dns': {'servers': [{'type': 'local', 'tag': 'bootstrap'}]}}
        code, _ = screen.bounded_command(['sing-box', 'check', '-c', save(self.root / 'core.json', profile)])
        self.assertEqual(code, 0)

    def test_core_check_and_startup_failure_never_fallback(self):
        a = args(self.root, route='cherry-ssh')
        art = screen.Artifacts(a)
        runner = screen.Runner(a, art)
        selected = dict(type='ssh', tag='cherry-ssh', server='192.0.2.1', server_port=22,
                        user='probe', password='not-persisted-in-summary', host_key=['pin'])
        try:
            with patch.object(screen, 'bounded_command', return_value=(1, b'secret error')):
                with self.assertRaises(screen.Stop) as caught:
                    runner.core_start(selected, time.monotonic() + 1)
            self.assertEqual(caught.exception.stage, 'core-check')
            self.assertIsNone(runner.proxy)
            self.assertIsNone(runner.core)
        finally:
            runner.cleanup()
            art.close()
        art = screen.Artifacts(args(self.root, output=str(self.root / 'startup')))
        runner = screen.Runner(a, art)
        original = subprocess.Popen
        def no_network(_argv, **kw):
            return original([sys.executable, '-c', 'import time; time.sleep(10)'], **kw)
        try:
            with patch.object(screen, 'bounded_command', return_value=(0, b'')), patch.object(screen.subprocess, 'Popen', side_effect=no_network):
                with self.assertRaises(screen.Stop) as caught:
                    runner.core_start(selected, time.monotonic() + .15)
            self.assertEqual(caught.exception.stage, 'startup')
            self.assertIsNone(runner.proxy)
        finally:
            runner.cleanup()
            art.close()
        self.assertIsNotNone(runner.core.poll())
        self.assertFalse((art.root / 'core.json').exists())

    def test_malformed_metrics_and_noisy_pipes_keep_failed_sample(self):
        a = args(self.root)
        art = screen.Artifacts(a)
        runner = screen.Runner(a, art)
        original = subprocess.Popen
        script = ('import sys,os,re; c=sys.stdin.read(); '
                  'h=int(re.search(r\'dump-header = "/dev/fd/(\\d+)"\',c)[1]); '
                  'm=int(re.search(r\'%output\\{/dev/fd/(\\d+)\\}\',c)[1]); '
                  'os.write(h,b"HTTP/1.1 200 OK\\r\\nContent-Length: 4096\\r\\nContent-Type: application/octet-stream\\r\\nCache-Control: no-store, no-transform\\r\\n\\r\\n"); '
                  'os.write(m,b"not-json secret-url"); '
                  'sys.stderr.write("private-token"*10000); sys.stderr.flush(); '
                  'sys.stdout.buffer.write(b"x"*4096)')
        def fake_curl(argv, **kw):
            self.assertEqual(argv, ['curl', '--disable', '--config', '-'])
            return original([sys.executable, '-c', script], **kw)
        try:
            with patch.object(screen.subprocess, 'Popen', side_effect=fake_curl):
                _, row = runner.one(self.obj, 'workload', time.monotonic() + 2)
            self.assertEqual(row['error'], 'malformed-metrics')
            self.assertEqual(row['outcome'], 'failed')
            self.assertEqual(row['received_bytes'], 4096)
            self.assertNotIn('private-token', (art.root / 'events.jsonl').read_text())
            self.assertEqual(runner.transfers[0].buffers['stderr'], b'')
        finally:
            runner.cleanup()
            art.close()

    def test_owned_descendant_is_terminated_and_parent_reaped(self):
        a = args(self.root)
        art = screen.Artifacts(a)
        runner = screen.Runner(a, art)
        original = subprocess.Popen
        pidfile = self.root / 'descendant.pid'
        script = ('import subprocess,sys,signal,time; sys.stdin.read(); '
                  'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                  f'open({str(pidfile)!r},"w").write(str(p.pid)); '
                  'signal.signal(signal.SIGTERM,lambda *_:(p.wait(timeout=2),sys.exit(0))); '
                  'time.sleep(30)')
        def fake_curl(_argv, **kw):
            return original([sys.executable, '-c', script], **kw)
        try:
            with patch.object(screen.subprocess, 'Popen', side_effect=fake_curl):
                _, row = runner.one(self.obj, 'workload', time.monotonic() + .4)
            self.assertEqual(row['outcome'], 'timeout')
            self.assertTrue(pidfile.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)
        finally:
            runner.cleanup()
            art.close()
        self.assertIsNotNone(runner.transfers[0].proc.poll())


class DeadlineBoundaryTests(unittest.TestCase):
    """Real no-network children: wait/pipe barriers, not deadline-adjacent sleeps."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = 0

    @contextlib.contextmanager
    def transfer(self, code=18, body=b'xxx', workload='continuous', hold=False,
                 eof=False, queued=False, headers=None, metrics=None):
        root = self.root / str(self.runs)
        root.mkdir(mode=0o700)
        self.runs += 1
        a = args(root, workload=workload, duration=600)
        art = screen.Artifacts(a)
        runner = screen.Runner(a, art)
        obj = descriptor(root, object_bytes=100, sha256=hashlib.sha256(b'x' * 100).hexdigest())
        headers = headers if headers is not None else (
            b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\nContent-Type: application/octet-stream\r\n'
            b'Cache-Control: no-store, no-transform\r\n\r\n')
        metrics = metrics if metrics is not None else json.dumps(dict(
            http_status='200', http_version='1.1', ttfb_s=.01, time_total_s=.02,
            inner_new_connections=1)).encode()
        script = ('import sys,os,re,signal; c=sys.stdin.read(); '
                  'h=int(re.search(r\'dump-header = "/dev/fd/(\\d+)"\',c)[1]); '
                  'm=int(re.search(r\'%output\\{/dev/fd/(\\d+)\\}\',c)[1]); '
                  f'os.write(h,{headers!r}); os.write(m,{metrics!r}); os.write(1,{body!r}); '
                  + ('os.close(1); ' if eof else '')
                  + ('os.write(2,b"ready"); signal.pause()' if hold else f'sys.exit({code})'))
        original = subprocess.Popen
        try:
            with patch.object(screen.subprocess, 'Popen', side_effect=lambda _argv, **kw:
                              original([sys.executable, '-c', script], **kw)):
                task = screen.Transfer(runner, obj, 'workload', time.monotonic() + 5)
            task.drain(task.proc.stdin, 'config')
            if hold and queued:
                self.assertTrue(select.select([task.proc.stderr], [], [], 2)[0], 'child pipe barrier timed out')
                task.drain(task.proc.stderr, 'stderr')
            elif hold:
                end = time.monotonic() + 2
                while not task.stream_bytes.get('stderr'):
                    self.assertLess(time.monotonic(), end, 'child pipe barrier timed out')
                    for key, _ in runner.selector.select(.05):
                        task.drain(key.fileobj, key.data[1])
                # Drain all currently observable headers/body/EOF before cancellation.
                while events := runner.selector.select(0):
                    for key, _ in events:
                        task.drain(key.fileobj, key.data[1])
                self.assertIsNone(task.proc.poll())
            else:
                self.assertEqual(task.proc.wait(timeout=2), code)
            runner.work_start = runner.tick_at = time.monotonic() - 600
            runner.next_tick = 0
            yield runner, task
        finally:
            runner.cleanup()
            art.close()

    def finish_at_boundary(self, runner, task):
        end = runner.work_start + runner.args.duration
        while not task.ready():
            runner.pump([task], end)
        row = task.finish()
        runner.tick(force=True)
        runner.work_end = time.monotonic()
        summary = screen.summarize(runner, None)
        events = [json.loads(line) for line in (runner.art.root / 'events.jsonl').read_text().splitlines()]
        self.assertEqual([r['curl_exit'] for r in events if r['event'] == 'request-end'], [row['curl_exit']])
        self.assertEqual(summary['attempted'], 1)
        self.assertEqual(summary['bytes']['workload'], row['received_bytes'])
        self.assertEqual(summary['partial_bytes'], 0 if row['integrity'] == 'verified' else row['received_bytes'])
        self.assertEqual(summary['failed'], int(row['outcome'] not in ('passed', 'completed-window')))
        self.assertEqual(summary['completed_windows'], int(row['outcome'] == 'completed-window'))
        self.assertEqual(summary['windows']['last']['coverage'], 'full')
        self.assertLess(summary['windows']['last']['goodput_mbit_s'], 10)
        self.assertEqual(sum(p['body_bytes_delta'] for p in runner.progress), row['received_bytes'])
        return row, summary

    def test_already_exited_errors_at_planned_deadline(self):
        for code, outcome, error in ((18, 'failed', 'unexpected-length'),
                                      (56, 'failed', 'unexpected-length'),
                                      (28, 'timeout', 'curl-28'), (0, 'failed', 'unexpected-length')):
            with self.subTest(code=code), self.transfer(code=code) as (runner, task):
                # Force pump even if all child pipes are already ready to finish.
                runner.pump([task], runner.work_start + 600)
                self.assertIsNone(task.reason, 'a reaped natural exit is not runner cancellation')
                row, summary = self.finish_at_boundary(runner, task)
                self.assertEqual((row['outcome'], row['error'], row['curl_exit']), (outcome, error, code))
                self.assertEqual(row['termination'], 'natural-exit')
                self.assertIsNone(row['cancellation_reason'])
                self.assertEqual(summary['outcome'], outcome)
                if code:
                    self.assertEqual(summary['first_transport_failure'], row)

    def test_natural_error_racing_with_sigterm_is_not_planned_success(self):
        for code in (0, 18, 56, 28):
            with self.subTest(code=code), self.transfer(code=code) as (runner, task):
                # Model exit after poll but before signal delivery; retain the actual raw exit.
                with patch.object(task.proc, 'poll', return_value=None), patch.object(screen.os, 'killpg'):
                    task.abort('completed-window')
                row, _ = self.finish_at_boundary(runner, task)
                self.assertEqual(row['curl_exit'], code)
                self.assertIn(row['outcome'], ('failed', 'timeout'))
                self.assertEqual(row['termination'], 'exit-raced-with-cancellation')
                self.assertEqual(row['cancellation_reason'], 'completed-window')

    def test_parent_owned_cancellation_and_eof_before_signal(self):
        for eof in (False, True):
            with self.subTest(eof=eof), self.transfer(hold=True, eof=eof, metrics=b'') as (runner, task):
                row, summary = self.finish_at_boundary(runner, task)
                self.assertEqual(row['curl_exit'], -signal.SIGTERM)
                self.assertEqual(row['cancellation_reason'], 'completed-window')
                self.assertEqual(row['outcome'], 'failed' if eof else 'completed-window')
                self.assertEqual(row['error'], 'unexpected-length' if eof else None)
                self.assertEqual(row['termination'], 'eof-before-runner-sigterm' if eof else 'runner-sigterm')
                self.assertEqual(summary['first_transport_failure'] is None, not eof)

    def test_queued_eof_and_body_are_not_hidden_by_signal(self):
        with self.transfer(hold=True, eof=True, queued=True) as (runner, task):
            self.assertEqual(task.received, 0, 'leave body and EOF queued until the boundary')
            row, _ = self.finish_at_boundary(runner, task)
            self.assertEqual((row['outcome'], row['error']), ('failed', 'unexpected-length'))
            self.assertEqual(row['received_bytes'], 3)
            self.assertEqual(row['termination'], 'eof-before-runner-sigterm')

    def test_earlier_request_deadline_is_not_a_completed_workload_window(self):
        with self.transfer(hold=True, workload='segments', metrics=b'') as (runner, task):
            task.deadline = runner.work_start + 599
            row, summary = self.finish_at_boundary(runner, task)
            self.assertEqual((row['outcome'], row['error']), ('timeout', 'request-deadline'))
            self.assertEqual(row['cancellation_reason'], 'request-deadline')
            self.assertEqual(summary['first_transport_failure'], row)

    def test_error_and_malformed_response_survive_planned_cancellation(self):
        cases = [(dict(headers=b'HTTP/1.1 403 Forbidden\r\nContent-Length: 100\r\n\r\n'), 'http-status'),
                 (dict(headers=b'not-http\r\n\r\n'), 'malformed-response'),
                 (dict(metrics=b'not-json'), 'malformed-metrics')]
        for changes, error in cases:
            with self.subTest(error=error), self.transfer(hold=True, **changes) as (runner, task):
                row, summary = self.finish_at_boundary(runner, task)
                self.assertEqual((row['outcome'], row['error']), ('failed', error))
                self.assertEqual(row['curl_exit'], -signal.SIGTERM)
                self.assertIsNone(summary['first_transport_failure'], 'expected TERM is not a transport error')

    def test_complete_and_partial_segments_at_boundary(self):
        for hold, code, size, outcome, error in (
                (False, 0, 100, 'passed', None), (False, 0, 3, 'failed', 'unexpected-length'),
                (False, 18, 100, 'failed', 'curl-18'), (False, 56, 3, 'failed', 'unexpected-length'),
                (True, 0, 100, 'passed', None), (True, 0, 3, 'completed-window', None)):
            with self.subTest(hold=hold, code=code, size=size), self.transfer(
                    code=code, body=b'x' * size, workload='segments', hold=hold) as (runner, task):
                row, summary = self.finish_at_boundary(runner, task)
                self.assertEqual((row['outcome'], row['error']), (outcome, error))
                self.assertEqual(summary['completed'], int(outcome == 'passed'))
                self.assertEqual(row['integrity'], 'verified' if outcome == 'passed' else 'partial-unverified')


class TLSFixture:
    def __init__(self, root):
        self.root = root
        self.body = os.urandom(2 * 1024 * 1024)
        self.stop = threading.Event()
        self.seen, self.receipts, self.reads = set(), {}, {}
        self.active_receipt = False
        self.mismatch = False
        self.always_active = False
        self.requests = []
        self.lock = threading.Lock()
        ca = root / 'ca.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ed25519', '-noenc', '-days', '1',
                        '-subj', '/CN=local-test', '-addext', 'subjectAltName=IP:127.0.0.1',
                        '-keyout', str(root / 'key.pem'), '-out', str(ca)],
                       check=True, capture_output=True, timeout=10)
        for path in (ca, root / 'key.pem'):
            path.chmod(0o600)
        fixture = self
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.connection.settimeout(2)
                operation = self.headers.get('X-Request-ID')
                receipt_read = self.path.startswith('/receipts/')
                with fixture.lock:
                    if operation in fixture.seen:
                        status = 409
                    elif self.headers.get('X-Run-ID') != 'local-run' or not operation:
                        status = 400
                    elif self.headers.get('Authorization') != 'Bearer ' + ('receipt-token' if receipt_read else 'object-token'):
                        status = 401
                    else:
                        status = 200
                        fixture.seen.add(operation)
                    fixture.requests.append((operation, self.path, self.headers.get('Accept-Encoding')))
                if status != 200:
                    self.reply(status, b'')
                    return
                if receipt_read:
                    request = self.path.split('/')[-1]
                    with fixture.lock:
                        value = copy.copy(fixture.receipts[request])
                        fixture.reads[request] = fixture.reads.get(request, 0) + 1
                        count = fixture.reads[request]
                    if fixture.always_active or (fixture.active_receipt and count == 1):
                        value['outcome'] = 'active'
                    if fixture.mismatch:
                        value['run'] = 'wrong-run'
                    self.reply(200, json.dumps(value).encode(), content_type='application/json')
                    return
                name = self.path.split('/')[-1]
                size = 4096 if name in ('fresh', 'html', 'forbidden', 'redirect', 'gzip', 'wrong-hash', 'early') else (
                    16384 if name == 'segment' else len(fixture.body))
                receipt = dict(run='local-run', request=operation, source=self.client_address[0], object=name,
                               utc_start=time.time(), body_bytes_sent=size, elapsed_s=.01, outcome='complete')
                if name in ('continuous', 'no-body'):
                    receipt.update(body_bytes_sent=4096 if name == 'continuous' else 0, outcome='active')
                with fixture.lock:
                    fixture.receipts[operation] = receipt
                if name == 'forbidden':
                    self.reply(403, b'<html>policy</html>', content_type='text/html')
                elif name == 'redirect':
                    self.reply(302, b'', extra={'Location': 'https://must-not-follow.invalid/secret'})
                elif name == 'html':
                    self.reply(200, b'<html>not payload</html>', content_type='text/html')
                elif name == 'gzip':
                    self.reply(200, fixture.body[:size], extra={'Content-Encoding': 'gzip'})
                elif name == 'early':
                    self.reply(200, fixture.body[:1024], length=size)
                elif name in ('continuous', 'no-body'):
                    self.reply(200, fixture.body[:4096] if name == 'continuous' else b'', length=size, leave_open=True)
                    # Observe actual client close before finalizing this partial receipt.
                    self.connection.settimeout(.05)
                    end = time.monotonic() + 6
                    while not fixture.stop.is_set() and time.monotonic() < end:
                        try:
                            if not self.connection.recv(1):
                                break
                        except socket.timeout:
                            continue
                        except OSError:
                            break
                    self.close_connection = True
                    with fixture.lock:
                        fixture.receipts[operation] = receipt | {'outcome': 'interrupted',
                            'elapsed_s': max(0, time.time() - receipt['utc_start'])}
                else:
                    self.reply(200, fixture.body[:size])

            def reply(self, status, data, content_type='application/octet-stream', extra=None,
                      length=None, leave_open=False):
                try:
                    self.send_response(status)
                    self.send_header('Content-Length', len(data) if length is None else length)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Cache-Control', 'no-store, no-transform')
                    self.send_header('Connection', 'close')
                    for key, value in (extra or {}).items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(data)
                    self.wfile.flush()
                    self.close_connection = not leave_open
                except (OSError, ssl.SSLError):
                    pass
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(ca, root / 'key.pem')
        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = False

            def handle_error(self, *_args):
                pass  # Expected TLS/cancellation failures; no raw peer/exception logs.

            def get_request(self):
                sock, peer = self.socket.accept()
                sock.settimeout(2)
                try:
                    return tls.wrap_socket(sock, server_side=True), peer
                except BaseException:
                    sock.close()
                    raise
        self.server = Server(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02})
        self.thread.start()

    def obj(self, name='fresh'):
        size = 4096 if name in ('fresh', 'html', 'forbidden', 'redirect', 'gzip', 'wrong-hash', 'early') else (
            16384 if name == 'segment' else len(self.body))
        base = f'https://127.0.0.1:{self.server.server_port}'
        return descriptor(self.root, https_url=base + '/objects/' + name,
                          receipt_url=base + '/receipts/{request}', object_bytes=size,
                          sha256=('0' * 64 if name == 'wrong-hash' else hashlib.sha256(self.body[:size]).hexdigest()))

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise AssertionError('fixture server thread leaked')


@unittest.skipUnless(shutil.which('curl') and shutil.which('openssl'), 'local curl/openssl required')
class CurlIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = TLSFixture(self.root)
        self.addCleanup(self.fixture.close)
        self.runners = []

    @contextlib.contextmanager
    def runner(self, **values):
        a = args(self.root, output=str(self.root / ('run-' + str(len(self.runners)))), **values)
        screen.validate_args(a)
        art = screen.Artifacts(a)
        runner = screen.Runner(a, art)
        self.runners.append(runner)
        try:
            yield runner
        finally:
            runner.cleanup()
            summary = screen.summarize(runner, None)
            art.atomic('summary.json', summary)
            art.atomic('SUMMARY.md', screen.human(summary))
            art.emit('run-end', outcome=summary['outcome'])
            art.close()
            for task in runner.transfers:
                self.assertIsNotNone(task.proc.poll(), 'curl process leaked')
            self.assertFalse(art.root.joinpath('core.json').exists())

    def test_real_curl_fresh_headers_metrics_hash_and_auth_receipt(self):
        with self.runner(duration=.8) as runner:
            obj = screen.endpoint(self.fixture.obj())
            runner.preflight(obj, time.monotonic() + 2)
            runner.workload(obj)
            runner.collect(time.monotonic() + 4)
            self.assertGreater(len(runner.results), 1)
            self.assertLessEqual(len(runner.results), 12)
            self.assertTrue(all(r['outcome'] == 'passed' for r in runner.results))
            self.assertTrue(all(r['http_version'] == '1.1' for r in runner.results))
            self.assertTrue(all(r['integrity'] == 'verified' for r in runner.results))
            self.assertTrue(all(r['inner_new_connections'] == 1 for r in runner.results))
            self.assertTrue(all(r['outer_connections'] is None for r in runner.results))
            self.assertTrue(all(r['state'] == 'finalized' for r in runner.receipts))
            self.assertEqual(runner.bytes['preflight'], 4096)
            self.assertGreater(runner.bytes['receipt'], 0)
            self.assertEqual(screen.summarize(runner, None)['outcome'], 'route-unverified')
            public = (runner.art.root / 'events.jsonl').read_text()
            for private in ('object-token', 'receipt-token', 'https://', '127.0.0.1'):
                self.assertNotIn(private, public)
        ids = [row[0] for row in self.fixture.requests]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(row[2] == 'identity' for row in self.fixture.requests))

    def test_real_curl_error_matrix_never_counts_as_success(self):
        for name, error in (('forbidden', 'http-status'), ('redirect', 'redirect'), ('html', 'content-type'),
                            ('gzip', 'content-encoding'), ('wrong-hash', 'integrity'), ('early', 'unexpected-length')):
            with self.subTest(name=name), self.runner(duration=.15) as runner:
                _, row = runner.one(self.fixture.obj(name), 'workload', time.monotonic() + 2)
                self.assertEqual(row['outcome'], 'failed')
                self.assertEqual(row['error'], error)
                self.assertEqual(len(runner.results), 1)
        self.assertFalse(any('must-not-follow' in r[1] for r in self.fixture.requests))

    def test_real_curl_exited_before_boundary_keeps_failure_or_complete_segment(self):
        for name, workload, outcome, error in (
                ('early', 'continuous', 'failed', 'unexpected-length'),
                ('early', 'segments', 'failed', 'unexpected-length'),
                ('continuous', 'continuous', 'timeout', 'curl-28'),
                ('forbidden', 'continuous', 'failed', 'http-status'),
                ('segment', 'segments', 'passed', None)):
            with self.subTest(name=name, workload=workload), self.runner(workload=workload, duration=600) as runner:
                timeout = .2 if name == 'continuous' else 2
                task = runner.request(self.fixture.obj(name), 'workload', time.monotonic() + timeout)
                task.drain(task.proc.stdin, 'config')
                # Small fixture responses fit the pipes. wait(), not a sleep, establishes natural exit.
                code = task.proc.wait(timeout=3)
                if name == 'early':
                    self.assertIn(code, (18, 56))
                runner.work_start = runner.tick_at = time.monotonic() - 600
                runner.next_tick = 0
                runner.pump([task], runner.work_start + 600)
                while not task.ready():
                    runner.pump([task], runner.work_start + 600)
                row = task.finish()
                runner.tick(force=True)
                runner.work_end = time.monotonic()
                summary = screen.summarize(runner, None)
                self.assertEqual((row['outcome'], row['error']), (outcome, error))
                self.assertEqual(row['curl_exit'], code)
                self.assertEqual(row['termination'], 'natural-exit')
                self.assertIsNone(row['cancellation_reason'])
                self.assertEqual(summary['failed'], int(outcome != 'passed'))
                if outcome != 'passed':
                    self.assertEqual(summary['outcome'], outcome)
                self.assertEqual(summary['completed_windows'], 0)
                self.assertEqual(summary['partial_bytes'], row['received_bytes'] if error else 0)
                self.assertEqual(summary['windows']['last']['coverage'], 'full')
                self.assertEqual(sum(p['body_bytes_delta'] for p in runner.progress), row['received_bytes'])
                events = [json.loads(line) for line in (runner.art.root / 'events.jsonl').read_text().splitlines()]
                self.assertEqual([r['outcome'] for r in events if r['event'] == 'request-end'], [outcome])

    def test_real_curl_parent_cancellation_at_controlled_boundary(self):
        with self.runner(workload='continuous', duration=.3) as runner:
            task = runner.request(self.fixture.obj('continuous'), 'workload', time.monotonic() + 5)
            # The fixture sends one body chunk then waits for disconnect; curl's timeout is not due.
            barrier = time.monotonic() + 2
            while task.received < 4096:
                self.assertLess(time.monotonic(), barrier, 'loopback body barrier timed out')
                for key, _ in runner.selector.select(.05):
                    task.drain(key.fileobj, key.data[1])
            self.assertIsNone(task.proc.poll())
            runner.work_start = runner.tick_at = time.monotonic() - runner.args.duration
            runner.next_tick = 0
            while not task.ready():
                runner.pump([task], runner.work_start + runner.args.duration)
            row = task.finish()
            runner.tick(force=True)
            runner.work_end = time.monotonic()
            summary = screen.summarize(runner, None)
            self.assertEqual((row['outcome'], row['error']), ('completed-window', None))
            self.assertEqual(row['curl_exit'], -signal.SIGTERM)
            self.assertEqual(row['termination'], 'runner-sigterm')
            self.assertEqual(row['cancellation_reason'], 'completed-window')
            self.assertEqual(summary['failed'], 0)
            self.assertEqual(summary['completed_windows'], 1)
            self.assertEqual(summary['partial_bytes'], 4096)
            self.assertIsNone(summary['first_transport_failure'])

    def test_real_curl_preflight_two_failures_preserved_no_workload(self):
        with self.runner() as runner:
            with self.assertRaises(screen.Stop) as caught:
                runner.preflight(self.fixture.obj('forbidden'), time.monotonic() + 5)
            self.assertEqual(caught.exception.code, 'preflight-exhausted')
            self.assertEqual(len(runner.all_results), 2)
            self.assertEqual(len(runner.results), 0)
            self.assertEqual(screen.summarize(runner, caught.exception)['preflight_failed'], 2)

    def test_real_curl_continuous_deadline_zero_progress_and_open_stall(self):
        with self.runner(workload='continuous', duration=3.15, max_bytes=1048576) as runner:
            runner.workload(self.fixture.obj('continuous'))
            row = runner.results[0]
            self.assertEqual(row['outcome'], 'completed-window')
            self.assertEqual(row['integrity'], 'partial-unverified')
            self.assertEqual(row['received_bytes'], 4096)
            self.assertGreaterEqual(len(runner.progress), 3)
            self.assertGreaterEqual(sum(p['body_bytes_delta'] == 0 for p in runner.progress), 2)
            self.assertTrue(any(s['censored'] and s['duration_s'] >= 2 for s in row['stalls']))
            for p in runner.progress:
                self.assertAlmostEqual(p['goodput_mbit_s'], 8 * p['body_bytes_delta'] / p['interval_s'] / 1e6)

    def test_real_curl_no_body_and_unexpected_request_timeout_are_failures(self):
        with self.runner(workload='continuous', duration=.3) as runner:
            runner.workload(self.fixture.obj('no-body'))
            self.assertEqual(runner.results[0]['outcome'], 'timeout')
        with self.runner() as runner:
            _, row = runner.one(self.fixture.obj('continuous'), 'workload', time.monotonic() + .2)
            self.assertEqual(row['outcome'], 'timeout')
            self.assertNotEqual(row['outcome'], 'completed-window')

    def test_real_curl_segments_bounded_fanout_and_rate_division(self):
        with self.runner(workload='segments', duration=.35, concurrency=4, rate_limit=262144) as runner:
            runner.workload(self.fixture.obj('segment'))
            self.assertGreaterEqual(len(runner.results), 4)
            self.assertTrue(all(r['outcome'] in ('passed', 'completed-window') for r in runner.results))
            self.assertTrue(any(r['integrity'] == 'verified' for r in runner.results))
            self.assertEqual(len(runner.results), len(runner.objects))
            starts = [json.loads(line) for line in (runner.art.root / 'events.jsonl').read_text().splitlines()]
            active, peak = 0, 0
            for row in starts:
                if row['event'] == 'request-start':
                    active += 1
                elif row['event'] == 'request-end':
                    active -= 1
                peak = max(peak, active)
            self.assertLessEqual(peak, 4)

    def test_real_curl_byte_cap_preserves_partial_and_is_not_timeout(self):
        with self.runner(workload='continuous', duration=2, max_bytes=50000) as runner:
            runner.workload(self.fixture.obj('large'))
            self.assertEqual(runner.bytes['workload'], 50000)
            self.assertEqual(runner.stop_reason, 'byte-limit')
            summary = screen.summarize(runner, None)
            self.assertEqual(summary['outcome'], 'inconclusive')
            self.assertEqual(summary['partial_bytes'], 50000)
            self.assertNotEqual(runner.results[0]['outcome'], 'completed-window')

    def test_real_curl_scoped_trust_failure_no_insecure_fallback(self):
        with self.runner() as runner:
            obj = self.fixture.obj()
            # A real unrelated CA, not merely a mock SSLContext.
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ed25519', '-noenc', '-days', '1',
                            '-subj', '/CN=wrong-ca', '-keyout', str(self.root / 'wrong.key'),
                            '-out', str(self.root / 'wrong.pem')], check=True, capture_output=True, timeout=10)
            _, row = runner.one(obj | {'ca_file': str(self.root / 'wrong.pem')}, 'workload', time.monotonic() + 2)
            self.assertEqual(row['outcome'], 'failed')
            self.assertEqual(row['stage'], 'tls')
            self.assertEqual(row['curl_exit'], 60)
            self.assertEqual(row['received_bytes'], 0)

    def test_real_curl_receipt_active_then_final_and_still_active_and_mismatch(self):
        for setting, expected, reads in (('active_receipt', 'finalized', 2),
                                         ('always_active', 'incomplete', 2), ('mismatch', 'incomplete', 1)):
            self.fixture.active_receipt = self.fixture.always_active = self.fixture.mismatch = False
            setattr(self.fixture, setting, True)
            with self.subTest(setting=setting), self.runner() as runner:
                task, row = runner.one(self.fixture.obj(), 'workload', time.monotonic() + 2)
                runner.objects.append(task)
                runner.collect(time.monotonic() + 3)
                self.assertEqual(row['integrity'], 'verified')
                self.assertEqual(runner.receipts[0]['state'], expected)
                self.assertEqual(runner.receipts[0]['reads'], reads)
                self.assertEqual(runner.operations, reads + 1)
                self.assertEqual(len(runner.results), 1, 'must not redownload object for receipts')

    def test_receipt_expiry_and_finalization_deadline_do_not_redownload(self):
        with self.runner() as runner:
            task, _ = runner.one(self.fixture.obj(), 'workload', time.monotonic() + 2)
            runner.objects.append(task)
            task.obj['expires_at'] = int(time.time()) - 1
            runner.collect(time.monotonic() + 1)
            self.assertEqual(runner.receipts[0]['reason'], 'receipt-deadline-or-expiry')
            self.assertEqual(runner.operations, 1)

    def test_receipt_finalization_deadline_and_total_operation_ceiling(self):
        with self.runner() as runner:
            task, _ = runner.one(self.fixture.obj(), 'workload', time.monotonic() + 2)
            runner.objects.append(task)
            runner.collect(time.monotonic() - .01)
            self.assertEqual(runner.operations, 1)
            self.assertEqual(runner.receipts[0]['state'], 'incomplete')
            runner.operations = 1024
            with self.assertRaises(screen.Stop) as caught:
                runner.request(self.fixture.obj(), 'receipt', time.monotonic() + 1, task.operation)
            self.assertEqual(caught.exception.code, 'endpoint-operation-limit')
            self.assertEqual(len(runner.results), 1)

    def test_worker_credential_bundle_with_real_files_and_readonly_mount_check(self):
        obj = self.fixture.obj()
        obj['ca_file'] = str(self.root / 'ca.pem')
        (self.root / 'ca.pem').chmod(0o440)
        worker = self.root / 'worker.json'
        save(worker, dict(schema_version=1, route='direct', outbound=None, endpoint=obj, preflight=obj))
        worker.chmod(0o440)
        a = args(self.root, worker_input=str(worker))
        with patch.dict(os.environ, CREDENTIALS_DIRECTORY=str(self.root)):
            with patch.object(screen.os, 'statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                loaded, pre, selected = screen.read_inputs(a)
                self.assertIsNone(selected)
                self.assertEqual(loaded, pre)
            with patch.object(screen.os, 'statvfs', return_value=SimpleNamespace(f_flag=0)):
                with self.assertRaises(screen.Stop):
                    screen.read_inputs(a)

    def test_disk_exhaustion_aborts_and_reaps_curl_with_failed_sample(self):
        with self.runner(workload='continuous', duration=1) as runner:
            runner.art.used = runner.args.max_disk_bytes - screen.RESERVE
            with self.assertRaises(screen.Stop) as caught:
                runner.workload(self.fixture.obj('continuous'))
            self.assertEqual(caught.exception.code, 'disk-limit')
            runner.cleanup()
            self.assertEqual(len(runner.results), 1)
            self.assertEqual(runner.results[0]['outcome'], 'inconclusive')

    def test_environment_change_invalidates_without_changing_policy(self):
        with self.runner(workload='continuous', duration=2) as runner:
            runner.baseline = {'historic': True}
            with patch.object(screen, 'environment', return_value={'changed': True}):
                runner.workload(self.fixture.obj('continuous'))
            self.assertEqual(runner.stop_reason, 'environment-changed')
            self.assertEqual(screen.summarize(runner, None)['outcome'], 'inconclusive')

    def test_signal_preserves_terminal_files_and_no_curl_orphan(self):
        if os.geteuid() in (0, 946):
            self.skipTest('CLI deliberately refuses these network UIDs')
        endpoint_path = save(self.root / 'continuous.json', self.fixture.obj('continuous'))
        preflight_path = save(self.root / 'fresh.json', self.fixture.obj())
        output = self.root / 'signal-run'
        gate = self.root / 'go'
        command = [sys.executable, str(Path(screen.__file__)), '--route', 'direct', '--workload', 'continuous',
                   '--duration', '10', '--max-bytes', '1048576', '--rate-limit', '65536',
                   '--endpoint-file', endpoint_path, '--preflight-endpoint-file', preflight_path,
                   '--output', str(output), '--gate', str(gate)]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            end = time.monotonic() + 8
            while time.monotonic() < end:
                if (output / 'events.jsonl').exists():
                    content = (output / 'events.jsonl').read_text()
                    if '"ready": true' in content and not gate.exists():
                        gate.touch(mode=0o600)
                    if '"event": "progress"' in content:
                        break
                if proc.poll() is not None:
                    self.fail('worker exited before signal test')
                time.sleep(.02)
            else:
                self.fail('loopback test worker did not become active')
            proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=7)
            self.assertEqual(err, b'')
            self.assertNotIn(b'object-token', out)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(summary['outcome'], 'cancelled')
            self.assertEqual(summary['attempted'], 1)
            self.assertEqual(summary['bytes']['workload'], 4096)
            self.assertTrue(json.loads((output / 'manifest.json').read_text())['complete'])
            self.assertIn('"event": "run-end"', (output / 'events.jsonl').read_text())
            # Curl children have their own sessions: parent exit alone is insufficient.
            rows = [json.loads(line) for line in (output / 'events.jsonl').read_text().splitlines()]
            for row in rows:
                if row['event'] == 'request-start':
                    with self.assertRaises(ProcessLookupError):
                        os.kill(row['child_pid'], 0)
        finally:
            screen.kill_owned([proc])
            proc.stdout.close()
            proc.stderr.close()


if __name__ == '__main__':
    unittest.main()
