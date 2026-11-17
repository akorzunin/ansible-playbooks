"""Offline lifecycle safety tests. Never call Cherry or touch deployment state."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

PROJECT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lifecycle_wrapper', PROJECT / 'tofu.py')
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


class PlanReviewTests(unittest.TestCase):
    def plan(self, actions):
        return {'variables': {'allocation_checks': {'value': True}}, 'resource_changes': [{
            'address': 'cherryservers_server.vpn', 'mode': 'managed',
            'change': {'actions': actions, 'before': {'id': '123', 'hostname': 'vpn-test'}, 'after': {
                'hostname': 'vpn-test', 'project_id': 123, 'region': 'NL-Amsterdam', 'plan': 'smallest',
                'user_data': 'private-host-key-must-not-be-printed',
            }},
        }], 'output_changes': {'hourly_quote': {'after': {'price': 0.015, 'currency': 'EUR', 'unit': 'Hourly'}}}}

    def test_create_noop_and_destroy_summaries_never_disclose_cloud_init(self):
        for operation, actions in [('deploy', ['create']), ('deploy', ['no-op']), ('destroy', ['delete'])]:
            with self.subTest(operation=operation, actions=actions):
                summary = wrapper.review_plan(self.plan(actions), operation)
                self.assertEqual(summary['resources'][0]['actions'], actions)
                self.assertNotIn('private-host-key', json.dumps(summary))
                self.assertEqual(summary['catalogue_quote']['currency'], 'EUR')
        self.assertEqual(wrapper.review_plan({}, 'destroy')['resources'], [])

    def test_creation_requires_allocation_checks_but_noop_and_destroy_do_not(self):
        for value in (False, None, 'true'):
            plan = self.plan(['create'])
            plan['variables']['allocation_checks']['value'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                wrapper.review_plan(plan, 'deploy')
        plan = self.plan(['create'])
        del plan['variables']
        with self.assertRaises(ValueError):
            wrapper.review_plan(plan, 'deploy')
        for operation, actions in [('deploy', ['no-op']), ('destroy', ['delete'])]:
            plan = self.plan(actions)
            plan['variables']['allocation_checks']['value'] = False
            self.assertEqual(wrapper.review_plan(plan, operation)['resources'][0]['actions'], actions)

    def test_refuses_wrong_direction_updates_replacements_and_unrelated_resources(self):
        for operation, actions in [('deploy', ['delete']), ('destroy', ['create']),
                                   ('deploy', ['update']), ('destroy', ['update']),
                                   ('deploy', ['delete', 'create']), ('deploy', ['create', 'delete'])]:
            with self.subTest(operation=operation, actions=actions), self.assertRaises(ValueError):
                wrapper.review_plan(self.plan(actions), operation)
        plan = self.plan(['create'])
        plan['resource_changes'][0]['address'] = 'cherryservers_server.ge2'
        with self.assertRaises(ValueError):
            wrapper.review_plan(plan, 'deploy')
        for field, value in [('errored', True), ('complete', False), ('deferred_changes', [{}])]:
            plan = self.plan(['create'])
            plan[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                wrapper.review_plan(plan, 'deploy')
        plan = self.plan(['create'])
        plan['resource_changes'][0]['change']['importing'] = {'id': '123'}
        with self.assertRaises(ValueError):
            wrapper.review_plan(plan, 'deploy')
        with self.assertRaises(ValueError):
            wrapper.review_plan({}, 'deploy')


class LifecycleOrderingTests(unittest.TestCase):
    def assert_fatal_phases(self, path):
        for play in yaml.safe_load(path.read_text()):
            imported = play.get('ansible.builtin.import_playbook')
            if imported:
                self.assert_fatal_phases(path.parent / imported)
            else:
                self.assertTrue(play.get('any_errors_fatal'), f'{path}: {play["name"]}')

    def test_deploy_checks_before_registration_and_publication_and_aborts_all_plays_on_error(self):
        plays = yaml.safe_load((PROJECT / 'provision.yaml').read_text())
        self.assert_fatal_phases(PROJECT / 'provision.yaml')
        provision = plays[2]['tasks']
        self.assertIn('not in dyn_tracked_resources.stdout_lines', provision[0]['when'])
        self.assertEqual(provision[1]['ansible.builtin.import_tasks'], 'tasks/lifecycle-plan.yaml')
        self.assertEqual(provision[2]['ansible.builtin.import_tasks'], 'tasks/lifecycle-apply.yaml')
        checks = plays[4]['tasks']
        self.assertTrue(checks[0]['ansible.builtin.command']['argv'][1].endswith('/check.py'))
        self.assertNotIn('--default', checks[1]['ansible.builtin.command']['argv'])
        self.assertTrue(plays[5]['ansible.builtin.import_playbook'].endswith('/sing-box-configs/deploy.yaml'))

    def test_destroy_retires_profiles_and_monitoring_before_apply(self):
        plays = yaml.safe_load((PROJECT / 'destroy.yaml').read_text())
        self.assert_fatal_phases(PROJECT / 'destroy.yaml')
        self.assertIn('--remove', plays[2]['tasks'][1]['ansible.builtin.command']['argv'])
        self.assertTrue(plays[3]['ansible.builtin.import_playbook'].endswith('/sing-box-configs/deploy.yaml'))
        self.assertTrue(plays[5]['ansible.builtin.import_playbook'].endswith('/ws-logs/deploy.yml'))
        self.assertEqual(plays[6]['tasks'][0]['ansible.builtin.import_tasks'], 'tasks/lifecycle-apply.yaml')
        apply = yaml.safe_load((PROJECT / 'tasks/lifecycle-apply.yaml').read_text())[0]
        self.assertIn('backup-state', apply['always'][0]['ansible.builtin.command']['argv'])

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible required')
    def test_plan_checks_allocation_only_when_creating_a_new_vm(self):
        task = yaml.safe_load((PROJECT / 'tasks/lifecycle-plan.yaml').read_text())[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ansible.cfg').write_text('[defaults]\n')
            (root / 'tofu.sh').write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$(dirname "$0")/args"\n')
            for operation, tracked, expected in [('deploy', [], 'true'),
                                                  ('deploy', ['cherryservers_server.vpn'], 'false'),
                                                  ('destroy', [], 'false')]:
                play = [{'name': 'Offline plan arguments', 'hosts': 'localhost', 'connection': 'local',
                         'gather_facts': False, 'vars': {'dyn_operation': operation, 'dyn_name': 'dyn1',
                                                       'dyn_tracked_resources': {'stdout_lines': tracked}},
                         'tasks': [task]}]
                path = root / 'plan.yaml'
                path.write_text(yaml.safe_dump(play))
                result = subprocess.run(
                    ['ansible-playbook', '-i', 'localhost,', str(path)], stdin=subprocess.DEVNULL,
                    env={**os.environ, 'ANSIBLE_CONFIG': str(root / 'ansible.cfg')},
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('-var=allocation_checks=' + expected, (root / 'args').read_text().splitlines())

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible required')
    def test_plan_gate_aborts_noninteractive_runs_before_any_apply(self):
        # Exercise the real approval tasks against a harmless fake wrapper.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ansible.cfg').write_text('[defaults]\n')
            script = root / 'tofu.sh'
            script.write_text('#!/bin/sh\nprintf \'{}\\n\'\n')
            tasks = yaml.safe_load((PROJECT / 'tasks/lifecycle-plan.yaml').read_text())
            play = [{'name': 'Offline approval gate', 'hosts': 'localhost', 'connection': 'local',
                     'gather_facts': False, 'vars': {'dyn_operation': 'deploy', 'dyn_name': 'dyn2',
                                                     'dyn_tracked_resources': {'stdout_lines': []}}, 'tasks': tasks}]
            path = root / 'gate.yaml'
            path.write_text(yaml.safe_dump(play))
            result = subprocess.run(
                ['ansible-playbook', '-i', 'localhost,', str(path)], stdin=subprocess.DEVNULL,
                env={**os.environ, 'ANSIBLE_CONFIG': str(root / 'ansible.cfg')},
                capture_output=True, text=True, timeout=30,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('Not approved', result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible required')
    def test_failure_in_an_imported_phase_prevents_later_localhost_publication(self):
        # A failed VPN phase must stop later localhost phases too.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ansible.cfg').write_text('[defaults]\n')
            source = yaml.safe_load((PROJECT / 'deploy.yaml').read_text())[1]
            (root / 'fail.yaml').write_text(yaml.safe_dump([{
                'name': 'Offline failing phase', 'hosts': 'localhost', 'gather_facts': False,
                'any_errors_fatal': source['any_errors_fatal'],
                'tasks': [{'name': 'Simulated VPN failure', 'ansible.builtin.fail': {'msg': 'offline failure'}}],
            }]))
            plays = copy.deepcopy(yaml.safe_load((PROJECT / 'provision.yaml').read_text()))
            imported = plays[3]
            imported['ansible.builtin.import_playbook'] = 'fail.yaml'
            publication = {'name': 'Must never publish', 'hosts': 'localhost', 'gather_facts': False,
                           'tasks': [{'name': 'Unexpected publication', 'ansible.builtin.file': {
                               'path': str(root / 'published'), 'state': 'touch', 'mode': '0600',
                           }}]}
            path = root / 'failure.yaml'
            path.write_text(yaml.safe_dump([imported, publication]))
            result = subprocess.run(
                ['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(path)],
                env={**os.environ, 'ANSIBLE_CONFIG': str(root / 'ansible.cfg')},
                capture_output=True, text=True, timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'published').exists(), result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible required')
    def test_incomplete_or_unreachable_node_cannot_reach_monitoring_or_publication(self):
        bootstrap_gate = yaml.safe_load((PROJECT / 'bootstrap.yaml').read_text())[-1]
        deployment_gate = yaml.safe_load((PROJECT / 'deploy.yaml').read_text())[-2]
        for gate, verified in [(bootstrap_gate, False), (deployment_gate, True)]:
            for unreachable in (False, True):
                with self.subTest(gate=gate['name'], unreachable=unreachable), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / 'ansible.cfg').write_text('[defaults]\n')
                    inventory = {'all': {'hosts': {'dyn1_admin': {
                        'ansible_host': '127.0.0.1', 'ansible_port': 1, 'ansible_connection': 'ssh',
                        'ansible_ssh_args': '-o ConnectTimeout=1 -o ConnectionAttempts=1 -o BatchMode=yes',
                        'dyn_admin_verified': verified, 'dyn_vpn_deployed': False,
                    }}}}
                    (root / 'hosts').write_text(yaml.safe_dump(inventory))
                    checkpoint = copy.deepcopy(gate)
                    checkpoint.pop('vars_files')
                    checkpoint['vars'] = {'dyn_name': 'dyn1'}
                    plays = [{'name': 'Controller remains active', 'hosts': 'localhost', 'gather_facts': False,
                              'tasks': [{'name': 'Seed controller', 'ansible.builtin.debug': {'msg': 'offline'}}]}]
                    if unreachable:
                        plays.append({'name': 'Unreachable node phase', 'hosts': 'dyn1_admin', 'gather_facts': False,
                                      'any_errors_fatal': True,
                                      'tasks': [{'name': 'Closed local SSH port', 'ansible.builtin.command': 'id -u',
                                                 'changed_when': False}]})
                    plays.extend([checkpoint, {
                        'name': 'Monitoring or publication must not run', 'hosts': 'localhost', 'gather_facts': False,
                        'tasks': [{'name': 'Unexpected side effect', 'ansible.builtin.file': {
                            'path': str(root / 'side-effect'), 'state': 'touch', 'mode': '0600',
                        }}],
                    }])
                    path = root / 'gate.yaml'
                    path.write_text(yaml.safe_dump(plays))
                    result = subprocess.run(
                        ['ansible-playbook', '-i', str(root / 'hosts'), str(path)],
                        env={**os.environ, 'ANSIBLE_CONFIG': str(root / 'ansible.cfg')},
                        capture_output=True, text=True, timeout=30,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertFalse((root / 'side-effect').exists(), result.stdout + result.stderr)
                    if not unreachable:
                        self.assertIn('did not finish', result.stdout + result.stderr)


class PreflightGuardTests(unittest.TestCase):
    """Run the real first preflight task so version and inventory drift is caught."""

    def inventory(self, monitoring_server='remote_workstation', monitored=('remote_workstation', 'nk1')):
        return yaml.safe_dump({'all': {
            'hosts': {'ge2': None},
            'children': {
                'monitoring_servers': {'hosts': {monitoring_server: None}},
                'monitored_nodes': {'hosts': {name: None for name in monitored}},
            },
        }})

    def run_guard(self, *args, inventory=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ansible.cfg').write_text('[defaults]\n')
            inventory_path = root / 'hosts'
            inventory_path.write_text(inventory or self.inventory())
            tasks = yaml.safe_load((PROJECT / 'tasks/lifecycle-preflight.yaml').read_text())
            play = [{'name': 'Offline preflight guard', 'hosts': 'localhost', 'connection': 'local',
                     'gather_facts': False, 'tasks': tasks[:1]}]
            path = root / 'guard.yaml'
            path.write_text(yaml.safe_dump(play))
            return subprocess.run(
                ['ansible-playbook', '-i', str(inventory_path), *args, str(path)],
                stdin=subprocess.DEVNULL,
                env={**os.environ, 'ANSIBLE_CONFIG': str(root / 'ansible.cfg')},
                capture_output=True, text=True, timeout=30,
            )

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible required')
    def test_only_a_plain_supervised_run_passes_the_guard(self):
        accepted = self.run_guard()
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        rejected = [('--check',), ('--limit', 'localhost'),
                    ('--tags', 'all,extra'), ('--skip-tags', 'extra')]
        for args in rejected:
            with self.subTest(args=args):
                result = self.run_guard(*args)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible required')
    def test_the_shared_inventory_shape_is_enforced(self):
        wrong_server = self.run_guard(inventory=self.inventory(monitoring_server='other_host'))
        self.assertNotEqual(wrong_server.returncode, 0, wrong_server.stdout + wrong_server.stderr)
        no_monitored = self.run_guard(inventory=self.inventory(monitored=()))
        self.assertNotEqual(no_monitored.returncode, 0, no_monitored.stdout + no_monitored.stderr)
