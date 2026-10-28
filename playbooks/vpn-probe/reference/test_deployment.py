"""Static deployment policy tests. Never invoke Ansible, systemd or nft."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).parent


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.play, = yaml.safe_load((ROOT.parent / "reference-deploy.yaml").read_text())

    def test_exact_host_explicit_opt_in_and_pinned_administration(self):
        self.assertEqual(self.play["hosts"], "cherry_vpn_test")
        variables = self.play["vars"]
        self.assertFalse(variables["reference_approved"])
        self.assertTrue(variables["ansible_host_key_checking"])
        self.assertIn("StrictHostKeyChecking=yes", variables["ansible_ssh_common_args"])
        self.assertIn("private/known_hosts", variables["ansible_ssh_common_args"])
        self.assertIn("reference_approved | bool", self.play["tasks"][0]["ansible.builtin.assert"]["that"])

    def test_no_bootstrap_production_roles_package_installs_or_service_restarts(self):
        text = (ROOT.parent / "reference-deploy.yaml").read_text()
        for forbidden in ("import_playbook", "import_role", "ansible.builtin.apt", "state: restarted", "docker", "8443"):
            self.assertNotIn(forbidden, text)
        install = self.play["tasks"][1]["block"]
        names = [task["name"] for task in install]
        self.assertLess(names.index("Require teardown before changing an active lease"),
                        names.index("Install only the reviewed endpoint files"))
        preview = next(task for task in install if task["name"] == "Preview managed files without changing a running lease")
        self.assertEqual(preview["when"], "reference_running")
        self.assertTrue(preview["check_mode"])
        self.assertFalse(install[-1]["ansible.builtin.systemd_service"]["enabled"])

    def test_worker_limits_credentials_and_fail_closed_restart(self):
        text = (ROOT / "reference.service").read_text()
        for setting in ("DynamicUser=yes", "NoNewPrivileges=yes", "CapabilityBoundingSet=\n",
                        "MemoryMax=192M", "CPUQuota=75%", "TasksMax=24", "RuntimeMaxSec=900",
                        "Restart=no", "ProtectHome=yes", "StateDirectoryMode=0700",
                        "Requires=vpn-reference-firewall.service", "BindsTo=vpn-reference-firewall.service"):
            self.assertIn(setting, text)
        self.assertNotIn("WantedBy=", text)
        self.assertNotIn("ca.key", text)

    def test_teardown_endpoint_precedes_guard_and_only_own_paths(self):
        teardown = self.play["tasks"][2]["block"]
        self.assertEqual(teardown[0]["loop"], ["vpn-reference.service", "vpn-reference-firewall.service"])
        removal = next(task for task in teardown if task["name"] == "Remove only reference installation and replay state")
        for path in removal["loop"]:
            self.assertIn("vpn-reference", path)
        reset = next(task for task in teardown if task["name"] == "Clear retained failure state only for removed reference units")
        self.assertIn("for unit in vpn-reference.service vpn-reference-firewall.service; do", reset["ansible.builtin.shell"])
        self.assertIn('systemctl reset-failed "$unit"', reset["ansible.builtin.shell"])
        self.assertNotIn("*", reset["ansible.builtin.shell"])
        guard = (ROOT / "firewall.service").read_text()
        self.assertIn("ExecStop=/usr/bin/python3 -E -s /opt/vpn-reference/firewall.py remove", guard)
        self.assertIn("CapabilityBoundingSet=CAP_NET_ADMIN", guard)


if __name__ == "__main__":
    unittest.main()
