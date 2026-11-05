"""Static-node sharing must not take over application or administrator services."""
import importlib.util
import json
from pathlib import Path
import socket
import struct
import unittest
from unittest.mock import MagicMock, patch

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

ROLE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vpn_check', ROLE / 'files/check.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ReusableTests(unittest.TestCase):
    def test_shared_mode_keeps_tcp_and_udp_application_ports_free(self):
        environment = Environment(loader=FileSystemLoader(ROLE / 'templates'), undefined=StrictUndefined)
        environment.filters['bool'] = bool
        variables = {
            'vpn_node_shared_https': True, 'vpn_node_ssh_port': 2222, 'vpn_node_hysteria2_port': 8443,
            'vpn_node_hysteria2_image': 'fixture@sha256:' + 'a' * 64,
            'vpn_node_hysteria2_certificate_dir': '/fixture/certificates',
            'ansible_facts': {'getent_passwd': {'vpnproxy': ['x', '1234', '1234']}},
        }
        render = lambda name: yaml.safe_load(environment.get_template(name).render(**variables))['services']
        proxies = render('compose.yaml.j2')
        self.assertEqual(proxies['naive']['ports'], ['127.0.0.1:8089:8080', '127.0.0.1:8444:8443'])
        self.assertEqual(render('hysteria2-compose.yaml.j2')['hysteria2']['ports'], ['0.0.0.0:8443:8443/udp'])
        ssh = render('ssh-compose.yaml.j2')['ssh']
        self.assertEqual(ssh['ports'], ['2222:2222'])
        self.assertEqual(ssh['user'], '1234:1234')
        self.assertEqual(ssh['cap_drop'], ['ALL'])
        self.assertTrue(ssh['read_only'])
        main = (ROLE / 'tasks/main.yaml').read_text()
        self.assertNotIn('import_tasks: ssh.yaml', main)

    def test_ssh_policy_is_forwarding_only_with_a_separate_identity(self):
        policy = (ROLE / 'templates/sshd_config.j2').read_text()
        for line in ['AllowUsers vpnprobe', 'PasswordAuthentication no', 'PermitRootLogin no',
                     'MaxSessions 0', 'AllowTcpForwarding local', 'AllowAgentForwarding no',
                     'AllowStreamLocalForwarding no', 'PermitTTY no', 'PermitTunnel no']:
            self.assertIn(line + '\n', policy)
        self.assertIn('HostKey /etc/vpn/ssh_host_ed25519_key', policy)
        clients = yaml.safe_load((ROLE / 'tasks/clients.yaml').read_text())
        self.assertEqual(clients[0]['ansible.builtin.slurp']['src'], '/srv/deploy/vpn-ssh/ssh_host_ed25519_key.pub')
        tasks = (ROLE / 'tasks/container-ssh.yaml').read_text()
        self.assertNotIn('/etc/ssh/', tasks)
        self.assertIn('creates: /srv/deploy/vpn-ssh/ssh_host_ed25519_key', tasks)

    def test_sni_router_preserves_sites_and_builds_off_node(self):
        environment = Environment(loader=FileSystemLoader(ROLE / 'templates'), undefined=StrictUndefined)
        source = 'test-dwman.example.org {\n reverse_proxy localhost:8088\n}'
        config = environment.get_template('shared-Caddyfile.j2').render(
            vpn_node_domain='vpn.example.org', vpn_node_caddyfile='fixture',
            vpn_node_vless_port=8443, lookup=lambda *_: source)
        self.assertIn(source, config)
        self.assertIn('tls sni vpn.example.org', config)
        self.assertIn('proxy 127.0.0.1:8444', config)
        self.assertNotIn('@vpn_vless', config)
        tasks = yaml.safe_load((ROLE / 'tasks/shared-https.yaml').read_text())
        build = next(t for t in tasks if 'community.docker.docker_image' in t)
        self.assertEqual(build['delegate_to'], 'localhost')
        names = [t['name'] for t in tasks]
        self.assertLess(names.index('Validate the combined router before replacing the existing configuration'),
                        names.index('Activate the validated combined HTTPS routing'))

    def test_ge2_cloudflare_sni_routes_to_reality_without_changing_backend(self):
        environment = Environment(loader=FileSystemLoader(ROLE / 'templates'), undefined=StrictUndefined)
        environment.filters['to_nice_json'] = json.dumps
        settings = yaml.safe_load((ROLE.parents[1] / 'node/ge2/vpn.yaml').read_text())
        source = 'test-dwman.example.org {\n reverse_proxy localhost:8088\n}'
        config = environment.get_template('shared-Caddyfile.j2').render(**settings, lookup=lambda *_: source)
        self.assertIn('tls sni www.cloudflare.com', config)
        self.assertIn('proxy 127.0.0.1:8443', config)
        self.assertIn('tls sni akorz-ge2.duckdns.org', config)
        self.assertIn('proxy 127.0.0.1:8444', config)
        self.assertIn(source, config)
        server = json.loads(environment.get_template('vless.json.j2').render(
            **settings, vpn_node_credentials={
                'vless_uuid': 'fixture', 'reality_private_key': 'fixture', 'reality_short_id': 'fixture',
            }))['inbounds'][0]
        self.assertEqual(server['listen_port'], 8443)
        self.assertEqual(server['tls']['server_name'], 'www.cloudflare.com')
        self.assertEqual(server['tls']['reality']['handshake'], {'server': 'www.cloudflare.com', 'server_port': 443})
        self.assertEqual(settings['vpn_node_vless_port'], 443)
        self.assertEqual(settings['vpn_node_vless_fingerprint'], 'firefox')

    def test_vless_port_443_requires_shared_https_and_distinct_sni(self):
        environment = Environment()
        environment.filters['bool'] = bool
        checks = yaml.safe_load((ROLE / 'tasks/validate.yaml').read_text())[0]['ansible.builtin.assert']['that']
        checks = [environment.compile_expression(check) for check in checks if 'vpn_node_vless_port' in check]
        for port, shared, sni, target, expected in [
            (8443, False, 'vpn.example.org', '192.0.2.10', True),
            (443, True, 'www.cloudflare.com', 'www.cloudflare.com', True),
            (443, False, 'www.cloudflare.com', 'www.cloudflare.com', False),
            (443, True, 'vpn.example.org', 'www.cloudflare.com', False),
            (443, True, 'www.cloudflare.com', '192.0.2.10', False),
            (443, True, 'www.cloudflare.com', 'vpn.example.org', False),
            (1234, True, 'www.cloudflare.com', 'www.cloudflare.com', False),
        ]:
            self.assertEqual(all(check(vpn_node_vless_port=port, vpn_node_shared_https=shared,
                                      vpn_node_reality_server_name=sni, vpn_node_domain='vpn.example.org',
                                      vpn_node_reality_handshake_address=target, vpn_node_public_address='192.0.2.10')
                                 for check in checks), expected)

    def test_hysteria_retirement_follows_publication_and_only_removes_its_project(self):
        playbook = yaml.safe_load((ROLE.parents[1] / 'playbooks/vpn-node/deploy.yaml').read_text())
        self.assertIn('ansible.builtin.import_playbook', playbook[-3])
        self.assertTrue(playbook[-2]['any_errors_fatal'])
        retire = playbook[-1]['tasks'][0]
        self.assertIn('not vpn_node_hysteria2_enabled', retire['when'])
        tasks = retire['block']
        compose = next(t['community.docker.docker_compose_v2'] for t in tasks
                       if 'community.docker.docker_compose_v2' in t)
        self.assertEqual(compose['project_src'], '/srv/deploy/vpn-hysteria2')
        self.assertEqual(compose['project_name'], 'vpn-hysteria2')
        self.assertEqual(compose['state'], 'absent')
        self.assertNotIn('/var/lib/vpn-node', json.dumps(tasks))

    def test_stun_checks_transaction_and_egress_without_network(self):
        transaction = b'transaction1'
        cookie = bytes.fromhex('2112a442')
        expected = '192.0.2.10'
        encoded = bytes(a ^ b for a, b in zip(socket.inet_aton(expected), cookie))
        value = b'\x00\x01' + b'\x00\x00' + encoded
        body = struct.pack('!HHI', 0x0101, 12, 0x2112a442) + transaction + struct.pack('!HH', 0x0020, 8) + value
        packet = b'\x00\x00\x00\x01' + socket.inet_aton('192.0.2.1') + struct.pack('!H', 3478) + body
        for response, ip, result in [(packet, expected, True), (packet, '192.0.2.11', False),
                                     (packet.replace(transaction, b'wrong-txn-id'), expected, False)]:
            control = MagicMock()
            control.recv.side_effect = [b'\x05\x00', b'\x05\x00\x00\x01', socket.inet_aton('127.0.0.1'), struct.pack('!H', 12345)]
            udp = MagicMock()
            udp.recv.return_value = response
            with patch.object(checker.socket, 'create_connection') as connect, \
                    patch.object(checker.socket, 'socket') as udp_socket, \
                    patch.object(checker.os, 'urandom', return_value=transaction):
                connect.return_value.__enter__.return_value = control
                udp_socket.return_value.__enter__.return_value = udp
                self.assertEqual(checker.stun(12340, 'stun.example.org', 3478, ip), result)

    def test_checker_derives_chain_without_mutating_export(self):
        original = [{'type': kind, 'tag': 'ge2-' + kind} for kind in ['ssh', 'naive', 'vless', 'hysteria2']]
        before = json.dumps(original)
        outbounds = checker.connections(original, 'ge2')
        self.assertEqual(outbounds[-1]['tag'], 'ge2-vless-via-naive')
        self.assertEqual(outbounds[-1]['detour'], 'ge2-naive')
        self.assertEqual(json.dumps(original), before)
        self.assertEqual(checker.connections({'outbounds': outbounds}, 'ge2'), outbounds)
