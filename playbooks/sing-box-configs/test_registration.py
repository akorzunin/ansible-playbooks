"""Node registration preserves unrelated exits and enrollment credentials."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('register_node', Path(__file__).with_name('register-node.py'))
registration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registration)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.data = {'sing_box_secrets': {
            'connections': {}, 'tokens': {'android': 'unchanged'},
            'extra_outbounds': [{'tag': 'aurora-vless', 'type': 'vless'},
                                {'tag': 'workstation-hop', 'type': 'ssh'}],
            'default_outbound': 'aurora-vless',
        }}
        self.outbounds = [{'tag': 'ge2-' + kind, 'type': kind} for kind in ['ssh', 'naive', 'vless', 'hysteria2']]

    def test_merge_is_idempotent_and_preserves_tokens_and_other_nodes(self):
        before = copy.deepcopy(self.data)
        merged = registration.merge(self.data, 'ge2', self.outbounds, 'ge2-vless-via-naive')
        self.assertEqual(self.data, before)
        self.assertEqual(merged['sing_box_secrets']['tokens'], before['sing_box_secrets']['tokens'])
        self.assertEqual(merged['sing_box_secrets']['extra_outbounds'][:2], before['sing_box_secrets']['extra_outbounds'])
        self.assertEqual(registration.merge(merged, 'ge2', self.outbounds, 'ge2-vless-via-naive'), merged)
        replacement = copy.deepcopy(self.outbounds)
        replacement[0]['server'] = '192.0.2.2'
        refreshed = registration.merge(merged, 'ge2', replacement, 'ge2-ssh')
        self.assertEqual(len(refreshed['sing_box_secrets']['extra_outbounds']), 6)
        self.assertEqual(refreshed['sing_box_secrets']['extra_outbounds'][2]['server'], '192.0.2.2')

    def test_hyphenated_neighbor_node_is_not_replaced(self):
        self.data['sing_box_secrets']['extra_outbounds'].append({'type': 'vless', 'tag': 'ge2-other-vless'})
        merged = registration.merge(self.data, 'ge2', self.outbounds, 'ge2-vless-via-naive')
        self.assertIn({'type': 'vless', 'tag': 'ge2-other-vless'}, merged['sing_box_secrets']['extra_outbounds'])
        with self.assertRaises(ValueError):
            registration.merge(self.data, 'ge2', self.outbounds, 'ge2-other-vless')

    def test_retiring_hysteria_removes_stale_entries_and_preserves_other_exits(self):
        merged = registration.merge(self.data, 'ge2', self.outbounds, 'ge2-vless-via-naive')
        merged['sing_box_secrets']['extra_outbounds'].append({'tag': 'other-hysteria2', 'type': 'hysteria2'})
        retired = registration.merge(merged, 'ge2', self.outbounds[:3], 'ge2-vless-via-naive')
        tags = {o['tag'] for o in retired['sing_box_secrets']['extra_outbounds']}
        self.assertNotIn('ge2-hysteria2', tags)
        self.assertIn('other-hysteria2', tags)
        self.assertEqual(retired['sing_box_secrets']['tokens'], self.data['sing_box_secrets']['tokens'])
        self.assertEqual(registration.merge(retired, 'ge2', self.outbounds[:3], 'ge2-vless-via-naive'), retired)
        with self.assertRaises(ValueError):
            registration.merge(merged, 'ge2', self.outbounds[:3], 'ge2-hysteria2')

    def test_rejects_cross_node_tags_incomplete_exports_and_foreign_default(self):
        for outbounds, default in [(self.outbounds[:2], 'ge2-ssh'), (self.outbounds, 'aurora-vless'),
                                   ([*self.outbounds, self.outbounds[0]], 'ge2-ssh'),
                                   ([*self.outbounds[:3], {'type': 'hysteria2', 'tag': 'other-hysteria2'}], 'ge2-ssh')]:
            with self.subTest(default=default), self.assertRaises(ValueError):
                registration.merge(self.data, 'ge2', outbounds, default)
