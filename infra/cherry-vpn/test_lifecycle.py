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
        return {'resource_changes': [{
            'address': 'cherryservers_server.vpn', 'mode': 'managed',
            'change': {'actions': actions, 'before': {'id': '123'}, 'after': {
                'project_id': 123, 'region': 'NL-Amsterdam', 'plan': 'smallest',
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
        self.assertIn('not in dyn1_tracked_resources.stdout_lines', provision[0]['when'])
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
    def test_plan_gate_aborts_noninteractive_runs_before_any_apply(self):
        # Exercise the real approval tasks against a harmless fake wrapper.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ansible.cfg').write_text('[defaults]\n')
            script = root / 'tofu.sh'
            script.write_text('#!/bin/sh\nprintf \'{}\\n\'\n')
            tasks = yaml.safe_load((PROJECT / 'tasks/lifecycle-plan.yaml').read_text())
            play = [{'name': 'Offline approval gate', 'hosts': 'localhost', 'connection': 'local',
                     'gather_facts': False, 'vars': {'dyn1_operation': 'deploy'}, 'tasks': tasks}]
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
