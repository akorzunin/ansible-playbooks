"""Offline contracts for Cherry host monitoring (no cloud operations)."""
import json
from pathlib import Path
import unittest

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[2]
PROJECT = Path(__file__).resolve().parent


class CherryMonitoringTests(unittest.TestCase):
    def test_persisted_overlay_survives_normal_monitoring_deployment(self):
        plays = yaml.safe_load((PROJECT / "monitoring.yaml").read_text())
        task = next(task for task in plays[1]["post_tasks"] if "ansible.builtin.blockinfile" in task)
        block = task["ansible.builtin.blockinfile"]["block"]
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        env.filters["to_json"] = json.dumps
        rendered = env.from_string(block).render(
            inventory_hostname="cherry_vpn_test", ansible_host="192.0.2.10",
            ansible_ssh_private_key_file="/private/admin", ansible_ssh_common_args="-o StrictHostKeyChecking=yes",
            monitoring_workstation_allowed_sources=["198.51.100.5/32"],
        )
        overlay = yaml.safe_load((ROOT / "monitoring.inventory.yml.example").read_text() + "\n" + rendered)
        cherry = overlay["cherry_monitoring"]["children"]["monitored_nodes"]["hosts"]["cherry_vpn_test"]
        self.assertEqual(cherry["monitoring_node"], "cherry")
        self.assertTrue(cherry["monitoring_availability_alert"])
        self.assertEqual(cherry["ansible_user"], "vpnadmin")
        self.assertNotIn("cherry_probe", overlay)

    def test_verification_requires_host_and_container_metrics(self):
        plays = yaml.safe_load((PROJECT / "monitoring.yaml").read_text())
        query = plays[-1]["tasks"][0]["vars"]["cherry_monitor_query"]
        self.assertIn('up{job="telegraf",node="cherry"}', query)
        self.assertIn('mem_total{job="telegraf"}', query)
        self.assertIn('docker_container_mem_usage{job="telegraf"}', query)
        self.assertNotIn("vpn_probe", query)

    def test_full_deployment_includes_monitoring(self):
        plays = yaml.safe_load((PROJECT / "deploy.yaml").read_text())
        self.assertEqual(plays[-1]["ansible.builtin.import_playbook"], "monitoring.yaml")


if __name__ == "__main__":
    unittest.main()
