"""Offline dynamic-node isolation and lifecycle contracts; no provider calls."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

PROJECT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('dynamic_wrapper', PROJECT / 'tofu.py')
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


class DynamicNodesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.shared = self.root / 'dropbox/cherry-vpn'
        self.shared.mkdir(parents=True)
        self.env = {'DROPBOX_SSH_DIR': str(self.shared.parent)}
        for key, value in [('PROJECT', self.project), ('ROOT', self.project), ('NODE', 'dyn1')]:
            context = patch.object(wrapper, key, value)
            context.start()
            self.addCleanup(context.stop)

    def test_names_are_strict_and_legacy_dyn1_state_never_moves(self):
        wrapper.select_node('dyn1')
        self.assertEqual(wrapper.ROOT, self.project)
        wrapper.select_node('dyn2')
        self.assertEqual(wrapper.ROOT, self.project / 'nodes/dyn2')
        for name in ('cherry', 'dyn0', 'dyn01', '../dyn1', 'dyn2/other', 'dyn1\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                wrapper.select_node(name)
        wrapper.select_node('dyn1')
        with self.assertRaises(ValueError):
            wrapper.initialize_node('unused', self.env)

    def test_initialization_is_local_isolated_and_cannot_reinitialize(self):
        (self.project / 'terraform.tfvars').write_text('region = "inherited"\n')
        (self.project / 'main.tf').write_text('fixture')
        (self.project / '.terraform.lock.hcl').write_text('fixture lock')
        sentinel = self.project / 'terraform.tfstate'
        sentinel.write_text('existing dyn1 state')
        wrapper.select_node('dyn2')
        commands = []

        def run(argv, **kwargs):
            commands.append(argv)
            self.assertEqual(Path.cwd(), wrapper.ROOT)
            if argv[1:] == ['state', 'push', '-']:
                state = json.loads(kwargs['input'])
                self.assertEqual(state['resources'], [])
                self.assertTrue(state['lineage'])
                wrapper.private_write(wrapper.ROOT / 'terraform.tfstate',
                                      json.dumps({'encryption_version': 'v0', 'encrypted_data': 'ciphertext'}))

        def vault(path, password, data):
            self.assertGreaterEqual(len(data['vpn_bootstrap']['state_passphrase']), 32)
            wrapper.private_write(path, '$ANSIBLE_VAULT;fixture\n')

        cwd = Path.cwd()
        try:
            with patch.object(wrapper.subprocess, 'run', side_effect=run), \
                    patch.object(wrapper.bootstrap, 'host_key', return_value={'public': 'fixture', 'private': 'fixture'}), \
                    patch.object(wrapper.bootstrap, 'write_vault', side_effect=vault):
                wrapper.initialize_node('tofu', self.env, 'NL-Amsterdam')
        finally:
            os.chdir(cwd)
        self.assertEqual([command[1] for command in commands], ['init', 'state'])
        inputs = json.loads((wrapper.ROOT / 'node.auto.tfvars.json').read_text())
        self.assertEqual(inputs['node_name'], 'dyn2')
        self.assertEqual(inputs['region'], 'NL-Amsterdam')
        self.assertEqual(inputs['ssh_public_key_path'], 'private/ssh/admin.pub')
        self.assertEqual(sentinel.read_text(), 'existing dyn1 state')
        self.assertTrue((wrapper.ROOT / 'main.tf').is_symlink())
        backup = self.shared / 'nodes/dyn2'
        self.assertTrue((backup / 'secrets.vault.yaml').read_text().startswith('$ANSIBLE_VAULT;'))
        self.assertTrue(wrapper.encrypted(backup / 'terraform.tfstate'))
        with self.assertRaises(ValueError):
            wrapper.initialize_node('unused', self.env)

    @unittest.skipUnless(shutil.which('ansible-vault') and ((PROJECT / '.tools/tofu').is_file() or shutil.which('tofu')),
                         'OpenTofu and ansible-vault required')
    def test_real_tofu_initializes_encrypted_empty_state_without_provider_access(self):
        # Only the encryption block is used: no provider, network or live state.
        source = (PROJECT / 'main.tf').read_text().split('  required_providers {')[0] + '}\n'
        source += '''
variable "state_encryption_passphrase" { type = string }
variable "ssh_host_key" { type = object({ public = string, private = string }) }
variable "node_name" { type = string }
variable "ssh_public_key_path" { type = string }
variable "region" { type = string }
'''
        (self.project / 'main.tf').write_text(source)
        (self.project / '.terraform.lock.hcl').write_text('')
        (self.project / 'terraform.tfvars').write_text('region = "inherited"\n')
        password = self.root / 'password'
        password.write_text('offline-test-password\n')
        executable = str(PROJECT / '.tools/tofu') if (PROJECT / '.tools/tofu').is_file() else shutil.which('tofu')
        wrapper.select_node('dyn2')
        cwd = Path.cwd()
        try:
            with patch.object(wrapper, 'PASSWORD', password):
                wrapper.initialize_node(executable, self.env)
                state = wrapper.ROOT / 'terraform.tfstate'
                self.assertTrue(wrapper.encrypted(state))
                data = wrapper.bootstrap.read_vault(wrapper.ROOT / 'secrets.vault.yaml', password)
                env = {**self.env, 'TF_VAR_state_encryption_passphrase': data['vpn_bootstrap']['state_passphrase']}
                result = wrapper.subprocess.run([executable, 'state', 'list'], env=env, check=True, capture_output=True)
                self.assertEqual(result.stdout.strip(), b'')
        finally:
            os.chdir(cwd)

    def test_shared_node_marker_prevents_new_state_after_local_state_loss(self):
        wrapper.select_node('dyn2')
        (self.shared / 'nodes/dyn2').mkdir(parents=True)
        with self.assertRaises(ValueError):
            wrapper.initialize_node('unused', self.env)
        self.assertFalse(wrapper.ROOT.exists())

    def test_backup_restore_is_scoped_and_validates_all_files_before_writing(self):
        wrapper.select_node('dyn2')
        wrapper.ROOT.mkdir(parents=True)
        backup = self.shared / 'nodes/dyn2'
        backup.mkdir(parents=True)
        contents = {'secrets.vault.yaml': '$ANSIBLE_VAULT;fixture\n', 'terraform.tfvars': 'fixture',
                    'node.auto.tfvars.json': '{}',
                    'terraform.tfstate': json.dumps({'encryption_version': 'v0', 'encrypted_data': 'fixture'})}
        for name, content in contents.items():
            wrapper.private_write(wrapper.ROOT / name, content)
        wrapper.transfer_state('backup-state', self.env)
        self.assertFalse((self.shared / 'terraform.tfstate').exists())
        for name, content in contents.items():
            self.assertEqual((backup / name).read_text(), content)
        (wrapper.ROOT / 'terraform.tfvars').write_text('conflicting local input')
        with self.assertRaises(ValueError):
            wrapper.transfer_state('restore-state', self.env)
        self.assertEqual((wrapper.ROOT / 'terraform.tfvars').read_text(), 'conflicting local input')

    def test_plan_refuses_a_server_from_another_node(self):
        wrapper.select_node('dyn2')
        plan = {'resource_changes': [{'address': 'cherryservers_server.vpn', 'mode': 'managed',
                                     'change': {'actions': ['delete'], 'before': {'hostname': 'dyn1'}}}]}
        with self.assertRaises(ValueError):
            wrapper.review_plan(plan, 'destroy')
        plan['resource_changes'][0]['change']['before']['hostname'] = 'dyn2'
        self.assertEqual(wrapper.review_plan(plan, 'destroy')['resources'][0]['hostname'], 'dyn2')
        wrapper.select_node('dyn1')
        with self.assertRaises(ValueError):
            wrapper.review_plan(plan, 'destroy')

    def test_missing_client_export_reports_incomplete_deployment_not_udp_failure(self):
        checker = PROJECT.parents[1] / 'roles/vpn_node/files/check.py'
        result = subprocess.run(
            ['python3', str(checker), '--input', str(self.root / 'missing-outbounds.json'),
             '--node', 'dyn1', '--expected-ip', '8.8.8.8', '--udp'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Client export not found', result.stderr)
        self.assertIn('complete VPN deployment', result.stderr)

    def test_provision_checks_udp_and_never_uses_provider_profile_tags(self):
        plays = yaml.safe_load((PROJECT / 'provision.yaml').read_text())
        for play in (plays[4], plays[6]):
            argv = play['tasks'][0]['ansible.builtin.command']['argv']
            self.assertIn('--udp', argv)
            self.assertIn('{{ dyn_name }}', argv)
            self.assertNotIn('cherry', argv)
        preflight = (PROJECT / 'tasks/lifecycle-preflight.yaml').read_text()
        self.assertNotIn('hysteria2.vault', preflight)
        destroy = (PROJECT / 'destroy.yaml').read_text()
        self.assertNotIn('ge2', destroy)
        self.assertIn('domains=akorz-{{ dyn_name }}', destroy)


if __name__ == '__main__':
    unittest.main()
