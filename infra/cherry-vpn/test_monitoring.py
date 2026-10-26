"""Offline contracts for Cherry's workstation monitoring (no cloud operations)."""
import json
from pathlib import Path
import unittest

import jinja2
import yaml
from ansible.plugins.filter.core import to_bool

ROOT = Path(__file__).resolve().parents[2]
PROJECT = Path(__file__).resolve().parent
STACK = ROOT / "playbooks/ws-logs"


class CherryMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, lstrip_blocks=True)
        self.env.filters.update(to_json=json.dumps, to_nice_json=json.dumps, bool=to_bool)

    def rules(self, enabled):
        template = self.env.from_string((STACK / "grafana/provisioning/alerting/vpn-rules.yml.j2").read_text())
        return yaml.safe_load(template.render(monitoring_vpn_probe_enabled=enabled))

    def test_alerts_cover_path_controls_and_stalled_probe(self):
        rules = {rule["uid"]: rule for rule in self.rules(True)["groups"][0]["rules"]}
        self.assertEqual(set(rules), {"monitoring-vpn-path", "monitoring-vpn-controls", "monitoring-vpn-probe-stale"})
        path = rules["monitoring-vpn-path"]
        expr = path["data"][0]["model"]["expr"]
        self.assertIn("max by (protocol)", expr)  # Both destinations must fail.
        self.assertIn('min(vpn_probe_controls_ok{job="telegraf"}) == 1', expr)
        self.assertIn('< 180', expr)
        self.assertEqual(path["noDataState"], "OK")  # Controls/stale have separate alerts.
        self.assertEqual(path["for"], "2m")
        self.assertIn("{{ $labels.protocol }}", path["annotations"]["summary"])
        stale = rules["monitoring-vpn-probe-stale"]["data"][0]["model"]["expr"]
        self.assertIn("or vector(1000000000)", stale)  # Missing series still pages.
        for rule in rules.values():
            self.assertEqual(rule["execErrState"], "Error")
            self.assertEqual(rule["labels"]["node"], "cherry")

    def test_disabled_probe_removes_only_its_rules(self):
        disabled = self.rules(False)
        self.assertNotIn("groups", disabled)
        self.assertEqual({rule["uid"] for rule in disabled["deleteRules"]},
                         {rule["uid"] for rule in self.rules(True)["groups"][0]["rules"]})

    def test_isolated_core_cannot_change_routes_or_reuse_active_client_ports(self):
        template = self.env.from_string((ROOT / "playbooks/vpn-monitor/client.json.j2").read_text())
        outbounds = [{"tag": "cherry-" + name, "type": name} for name in ("ssh", "naive", "vless")]
        config = json.loads(template.render(cherry_monitor_outbounds=outbounds))
        self.assertEqual(config["outbounds"], outbounds)
        self.assertEqual([inbound["listen_port"] for inbound in config["inbounds"]], [22340, 22341, 22342])
        self.assertTrue(all(inbound["listen"] == "127.0.0.1" and inbound["type"] == "mixed"
                            for inbound in config["inbounds"]))
        self.assertEqual(len(config["route"]["rules"]), 3)
        self.assertNotIn("auto_route", json.dumps(config))

    def test_persisted_overlay_survives_normal_monitoring_deployment(self):
        plays = yaml.safe_load((PROJECT / "monitoring.yaml").read_text())
        task = next(task for task in plays[1]["post_tasks"] if "ansible.builtin.blockinfile" in task)
        block = task["ansible.builtin.blockinfile"]["block"]
        rendered = self.env.from_string(block).render(
            inventory_hostname="cherry_vpn_test", ansible_host="192.0.2.10",
            ansible_ssh_private_key_file="/private/admin", ansible_ssh_common_args="-o StrictHostKeyChecking=yes",
            monitoring_workstation_allowed_sources=["198.51.100.5/32"],
            groups={"monitoring_servers": ["remote_workstation"]},
        )
        overlay = yaml.safe_load((ROOT / "monitoring.inventory.yml.example").read_text() + "\n" + rendered)
        cherry = overlay["cherry_monitoring"]["children"]["monitored_nodes"]["hosts"]["cherry_vpn_test"]
        self.assertEqual(cherry["monitoring_node"], "cherry")
        self.assertTrue(cherry["monitoring_availability_alert"])
        self.assertEqual(cherry["ansible_user"], "vpnadmin")
        self.assertTrue(overlay["cherry_probe"]["hosts"]["remote_workstation"]["monitoring_vpn_probe_enabled"])

    def test_metrics_collection_is_opt_in_and_uses_read_only_host_mount(self):
        template = self.env.from_string((ROOT / "roles/monitoring_client/templates/telegraf.conf.j2").read_text())
        base = dict(inventory_hostname="workstation")
        self.assertNotIn("[[inputs.file]]", template.render(**base))
        enabled = template.render(**base, monitoring_vpn_probe_enabled=True)
        self.assertIn('/hostfs/var/lib/vpn-monitor/metrics.prom', enabled)
        self.assertIn('data_format = "prometheus"', enabled)

    def test_compose_shares_only_the_client_network_and_has_no_host_privileges(self):
        compose = yaml.safe_load((ROOT / "playbooks/vpn-monitor/compose.yaml").read_text())
        client, probe = compose["services"]["client"], compose["services"]["probe"]
        self.assertEqual(probe["network_mode"], "service:client")
        self.assertIn("--continuous", probe["command"])
        self.assertIn("/metrics/metrics.prom", probe["command"])
        self.assertIn("/var/lib/vpn-monitor:/metrics:rw", probe["volumes"])
        self.assertFalse(any("client.json" in volume for volume in probe["volumes"]))
        for service in (client, probe):
            self.assertNotIn("ports", service)
            self.assertNotIn("privileged", service)
            self.assertNotIn("devices", service)
            self.assertEqual(service["user"], "65534:65534")
            self.assertTrue(service["read_only"])
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertEqual(service["restart"], "unless-stopped")

    def test_workstation_reuses_compose_role_and_keeps_secrets_outside_its_directory(self):
        play = yaml.safe_load((ROOT / "playbooks/vpn-monitor/deploy.yaml").read_text())[0]
        self.assertTrue(any(task.get("ansible.builtin.include_role") == {"name": "deploy_compose"}
                            for task in play["tasks"]))
        self.assertFalse(any("ansible.builtin.systemd_service" in task for task in play["tasks"]))
        template = next(task["ansible.builtin.template"] for task in play["tasks"]
                        if "ansible.builtin.template" in task)
        self.assertEqual(template["dest"], "/etc/vpn-monitor/client.json")
        self.assertEqual(template["mode"], "0600")
        self.assertIn("docker run --rm --network=none", template["validate"])
        self.assertIn("sha256:", template["validate"])
        self.assertIn("sha256:", (ROOT / "playbooks/vpn-monitor/Dockerfile").read_text())

    def test_full_deployment_includes_monitoring(self):
        plays = yaml.safe_load((PROJECT / "deploy.yaml").read_text())
        self.assertEqual(plays[-1]["ansible.builtin.import_playbook"], "monitoring.yaml")


if __name__ == "__main__":
    unittest.main()
