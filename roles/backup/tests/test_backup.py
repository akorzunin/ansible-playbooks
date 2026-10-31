import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('backup_inventory', ROLE / 'files/inventory.py')
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def container(name, workdir, mounts=(), running=True):
    return {
        'Id': name,
        'Name': name,
        'Config': {'Labels': {'com.docker.compose.project.working_dir': str(workdir)}},
        'Mounts': [{'Source': str(path), 'RW': writable} for path, writable in mounts],
        'State': {'Running': running},
    }


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.external = self.root / 'external'
        self.external.mkdir()

    def inspect(self, containers, paths=None):
        return inventory.inspect([str(p) for p in (paths or [self.data])], containers)

    def test_preserves_initially_stopped_containers(self):
        result = self.inspect([container('main', self.data, running=False), container('test', self.data)])
        self.assertEqual(result['running_ids'], ['test'])
        self.assertEqual(len(result['containers']), 2)

    def test_selects_other_writers_of_shared_data(self):
        result = self.inspect([container('writer', '/elsewhere', [(self.data, True)])])
        self.assertEqual(result['running_ids'], ['writer'])

    def test_does_not_stop_unrelated_containers(self):
        result = self.inspect([container('unrelated', self.external)])
        self.assertEqual(result['running_ids'], [])

    def test_refuses_omitted_external_volume(self):
        with self.assertRaisesRegex(ValueError, 'Include external storage'):
            self.inspect([container('app', self.data, [(self.external, True)])])

    def test_accepts_explicit_external_volume(self):
        result = self.inspect([container('app', self.data, [(self.external, True)])], [self.data, self.external])
        self.assertEqual(result['running_ids'], ['app'])

    def test_read_only_external_mount_does_not_require_snapshot(self):
        result = self.inspect([container('app', self.data, [(self.external, False)])])
        self.assertEqual(result['running_ids'], ['app'])

    def test_path_prefix_is_not_ancestry(self):
        self.assertFalse(inventory.covered(str(self.data) + '-other', [str(self.data)]))

    def test_rejects_root_missing_and_relative_paths(self):
        for paths in (['/'], [str(self.root / 'missing')], ['relative'], []):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                inventory.inspect(paths, [])


class PlaybookSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = yaml.safe_load((ROLE / 'tasks/main.yaml').read_text())
        cls.outer = next(task for task in cls.tasks if 'block' in task)
        cls.steps = cls.outer['block']

    def test_recovery_is_in_always_and_uses_original_ids(self):
        snapshot = next(task for task in self.steps if 'always' in task)
        restart = snapshot['always'][0]
        self.assertEqual(restart['loop'], '{{ backup_inventory.running_ids }}')
        self.assertEqual(restart['ansible.builtin.command']['argv'][:2], ['docker', 'start'])

    def test_cloud_access_checked_before_downtime(self):
        preflight = next(i for i, task in enumerate(self.steps) if 'Check cloud access' in task['name'])
        snapshot = next(i for i, task in enumerate(self.steps) if 'always' in task)
        self.assertLess(preflight, snapshot)

    def test_verification_precedes_staging_deletion(self):
        verify = next(i for i, task in enumerate(self.steps) if 'Download and compare' in task['name'])
        args = self.steps[verify]['ansible.builtin.command']['argv']
        self.assertIn('--download', args)
        self.assertIn('--one-way', args)
        self.assertEqual(self.steps[-1]['ansible.builtin.file']['state'], 'absent')
        self.assertLess(verify, len(self.steps) - 1)
        self.assertNotIn('always', self.outer)

    def test_does_not_modify_existing_cloud_configuration(self):
        text = (ROLE / 'tasks/main.yaml').read_text()
        self.assertNotIn('config create', text)
        self.assertNotIn('config delete', text)
        self.assertNotIn('BACKUP_PASS', text)
        self.assertNotIn('systemd', text)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook is required')
    def test_actual_recovery_after_archive_and_partial_stop_failure(self):
        snapshot = next(task for task in self.steps if 'always' in task)
        for fail_stop in (False, True):
            with self.subTest(fail_stop=fail_stop), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'metadata').mkdir()
                (root / 'upload').mkdir()
                docker = root / 'docker'
                docker.write_text(
                    '#!/usr/bin/env python3\n'
                    'import json, sys\n'
                    f'with open({str(root / "calls")!r}, "a") as f:\n'
                    '    f.write(json.dumps(sys.argv[1:]) + "\\n")\n'
                    f'sys.exit(1 if sys.argv[1] == "stop" and {fail_stop!r} else 0)\n'
                )
                docker.chmod(0o700)
                playbook = root / 'failure.yaml'
                playbook.write_text(yaml.safe_dump([{
                    'name': 'Exercise real Ansible failure recovery',
                    'hosts': 'localhost',
                    'gather_facts': False,
                    'vars': {
                        'backup_work_dir': {'path': temp},
                        'backup_file_name': 'failure.tar.gz',
                        'backup_inventory': {
                            'paths': [str(root / 'missing-source')],
                            'running_ids': ['previously-running'],
                        },
                    },
                    'tasks': [snapshot],
                }]))
                result = subprocess.run(
                    ['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(playbook)],
                    env={**os.environ, 'PATH': temp + os.pathsep + os.environ['PATH']},
                    capture_output=True, text=True, timeout=60,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
                self.assertEqual(calls[-1], ['start', 'previously-running'])
                self.assertEqual(len(calls), 2)

    def test_unsafe_legacy_restore_is_disabled(self):
        restore = yaml.safe_load((ROLE / 'tasks/restore.yaml').read_text())
        self.assertEqual(len(restore), 1)
        self.assertIn('ansible.builtin.fail', restore[0])


if __name__ == '__main__':
    unittest.main()
