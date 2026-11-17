"""Offline dynamic-profile naming, retirement and legacy migration contracts."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import generate

PROJECT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('dynamic_registration', PROJECT / 'register-node.py')
registration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registration)
spec = importlib.util.spec_from_file_location('dynamic_checks', PROJECT.parents[1] / 'roles/vpn_node/files/check.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def outbounds(node):
    return [{'type': kind, 'tag': node + '-' + kind} for kind in ('ssh', 'naive', 'vless')]


class DynamicProfilesTests(unittest.TestCase):
    def setUp(self):
        self.tokens = {platform: 'a' * 64 for platform in generate.ORDERS}
        self.data = {'sing_box_secrets': {
            'connections': {}, 'tokens': self.tokens,
            'extra_outbounds': outbounds('cherry') + outbounds('dyn2'),
            'default_outbound': 'cherry-vless',
        }}

    def test_atomic_dyn1_migration_preserves_other_nodes_tokens_and_defaults(self):
        original = copy.deepcopy(self.data)
        for suffix, expected in [('vless', 'vless'), ('naive', 'naive'), ('ssh', 'ssh'),
                                 ('hysteria2', 'vless'), ('vless-via-naive', 'vless')]:
            data = copy.deepcopy(original)
            data['sing_box_secrets']['default_outbound'] = 'cherry-' + suffix
            merged = registration.merge(registration.migrate_cherry(data, 'dyn1'), 'dyn1', outbounds('dyn1'))
            secrets = merged['sing_box_secrets']
            self.assertEqual(secrets['default_outbound'], 'dyn1-' + expected)
            self.assertEqual(secrets['tokens'], self.tokens)
            self.assertEqual(secrets['extra_outbounds'], outbounds('dyn2') + outbounds('dyn1'))
            self.assertEqual(registration.merge(registration.migrate_cherry(merged, 'dyn1'), 'dyn1', outbounds('dyn1')), merged)
        self.assertEqual(self.data, original)
        self.assertEqual(registration.migrate_cherry(self.data, 'dyn2'), self.data)
        data = copy.deepcopy(original)
        data['sing_box_secrets']['default_outbound'] = 'dyn2-vless'
        merged = registration.merge(registration.migrate_cherry(data, 'dyn1'), 'dyn1', outbounds('dyn1'))
        self.assertEqual(merged['sing_box_secrets']['default_outbound'], 'dyn2-vless')

    def test_dynamic_retired_choices_are_rejected_and_old_default_is_repaired(self):
        for suffix in ('hysteria2', 'vless-via-naive'):
            data = copy.deepcopy(self.data)
            data['sing_box_secrets']['default_outbound'] = 'dyn2-' + suffix
            merged = registration.merge(data, 'dyn2', outbounds('dyn2'))
            self.assertEqual(merged['sing_box_secrets']['default_outbound'], 'dyn2-vless')
            with self.assertRaises(ValueError):
                registration.merge(data, 'dyn2', outbounds('dyn2'), 'dyn2-' + suffix)
        with self.assertRaises(ValueError):
            registration.merge(self.data, 'dyn2', outbounds('dyn2') + [{'type': 'hysteria2', 'tag': 'dyn2-hysteria2'}])

    def test_generator_and_checker_do_not_recreate_dynamic_naive_chain(self):
        dynamic = outbounds('dyn2')
        self.assertEqual(checks.connections(dynamic, 'dyn2'), dynamic)
        self.assertIn('ge2-vless-via-naive', [o['tag'] for o in checks.connections(outbounds('ge2'), 'ge2')])
        with tempfile.TemporaryDirectory() as directory, patch.object(generate.subprocess, 'run'):
            target = Path(directory)
            generate.generate(target, {}, self.tokens, dynamic, 'dyn2-vless')
            for platform in generate.ORDERS:
                profile = json.loads((target / (platform + '.json')).read_text())
                self.assertEqual(profile['outbounds'][0]['outbounds'], [o['tag'] for o in dynamic])
                self.assertNotIn('via-naive', json.dumps(profile))
            for suffix in ('hysteria2', 'vless-via-naive'):
                with self.assertRaises(ValueError):
                    generate.generate(target, {}, self.tokens, dynamic + [{'type': 'vless', 'tag': 'dyn2-' + suffix}])

    def test_removing_one_node_preserves_surviving_node_and_requires_fallback(self):
        data = registration.merge(registration.migrate_cherry(self.data, 'dyn1'), 'dyn1', outbounds('dyn1'))
        with self.assertRaises(ValueError):
            registration.remove(data, 'dyn1')
        retired = registration.remove(data, 'dyn1', 'dyn2-vless')
        self.assertEqual(retired['sing_box_secrets']['extra_outbounds'], outbounds('dyn2'))
        self.assertEqual(retired['sing_box_secrets']['default_outbound'], 'dyn2-vless')
        self.assertEqual(retired['sing_box_secrets']['tokens'], self.tokens)


if __name__ == '__main__':
    unittest.main()
