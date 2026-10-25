"""Offline policy checks; never connect to or modify a server."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

import yaml


PLAYBOOK = pathlib.Path(__file__).with_name("deploy.yaml")


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap, self.secure = yaml.safe_load(PLAYBOOK.read_text())
        self.ssh_tasks = yaml.safe_load((PLAYBOOK.parents[1].parent / 'roles/vpn_node/tasks/ssh.yaml').read_text())

    def task(self, name):
        return next(task for task in self.ssh_tasks if task["name"] == name)

    def test_root_restriction_follows_fresh_nonroot_and_sudo_checks(self):
        connection = self.bootstrap["tasks"][-1]["ansible.builtin.add_host"]
        self.assertEqual(connection["groups"], "vpn_test_admin")
        self.assertTrue(connection["ansible_host_key_checking"])
        self.assertIn("ControlPath=none", connection["ansible_ssh_args"])
        self.assertIn("PreferredAuthentications=publickey", connection["ansible_ssh_args"])
        self.assertIn("BatchMode=yes", connection["ansible_ssh_args"])
        self.assertEqual(self.secure["hosts"], "vpn_test_admin")
        tasks = self.secure["tasks"]
        self.assertEqual(tasks[0]["ansible.builtin.command"], "id -u")
        self.assertFalse(tasks[0]["become"])
        self.assertIn("== 0", tasks[0]["failed_when"])
        self.assertEqual(tasks[1]["ansible.builtin.command"], "id -u")
        self.assertIn("!= '0'", tasks[1]["failed_when"])
        self.assertIn("ControlMaster=auto", tasks[2]["ansible.builtin.set_fact"]["ansible_ssh_args"])
        self.assertTrue(self.secure["become"])
        self.assertEqual(self.secure["become_flags"], "-n")
        self.assertEqual(tasks[-1]["ansible.builtin.import_role"], {"name": "vpn_node", "tasks_from": "ssh"})
        self.assertEqual(self.ssh_tasks[-2]["ansible.builtin.meta"], "reset_connection")
        self.assertEqual(self.ssh_tasks[-1]["ansible.builtin.command"], "id -u")

    def test_disabled_cloud_init_requires_both_provider_marker_and_python(self):
        task = next(t for t in self.bootstrap["tasks"] if "ansible.builtin.raw" in t)
        script = task["ansible.builtin.raw"]
        self.assertIn('[ "$rc" -eq 2 ]', script)
        self.assertIn('/etc/cloud/cloud-init.disabled', script)
        self.assertIn("[ \"$status\" = 'status: disabled' ]", script)
        self.assertIn('command -v python3', script)
        self.assertIn('exit "$rc"', script)

    def test_security_updates_are_periodic_security_only_and_never_reboot(self):
        periodic = self.task("Enable daily package indexes and unattended upgrades")["ansible.builtin.copy"]["content"]
        self.assertIn('APT::Periodic::Update-Package-Lists "1";', periodic)
        self.assertIn('APT::Periodic::Unattended-Upgrade "1";', periodic)
        policy = self.task("Limit unattended upgrades to Debian security without automatic reboots")["ansible.builtin.copy"]["content"]
        self.assertIn("#clear Unattended-Upgrade::Allowed-Origins;", policy)
        self.assertIn("#clear Unattended-Upgrade::Origins-Pattern;", policy)
        self.assertIn("codename=${distro_codename}-security,label=Debian-Security", policy)
        self.assertIn('Unattended-Upgrade::Automatic-Reboot "false";', policy)
        timers = self.task("Enable the daily apt timers")
        self.assertEqual(timers["loop"], ["apt-daily.timer", "apt-daily-upgrade.timer"])
        self.assertTrue(timers["ansible.builtin.systemd_service"]["enabled"])

    @unittest.skipUnless(shutil.which("sshd") and shutil.which("ssh-keygen"), "OpenSSH server tools unavailable")
    def test_effective_ssh_policy_overrides_provider_defaults_and_limits_tunnel(self):
        policy = self.task("Disable root SSH and restrict the tunnel account after verifying sudo")["ansible.builtin.blockinfile"]
        self.assertEqual(policy["insertbefore"], "BOF")
        self.assertIn("sshd -t", policy["validate"])
        with tempfile.TemporaryDirectory() as directory:
            key = pathlib.Path(directory) / "hostkey"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            config = pathlib.Path(directory) / "sshd_config"
            tunnel = self.task("Restrict tunnel sessions after all global SSH configuration")["ansible.builtin.blockinfile"]
            self.assertEqual(tunnel["insertafter"], "EOF")
            config.write_text(policy["block"] + f"\nHostKey {key}\nPermitRootLogin yes\nPasswordAuthentication yes\n"
                              + tunnel["block"])
            for user in ("vpnprobe", "vpnadmin"):
                result = subprocess.run(
                    [shutil.which("sshd"), "-T", "-f", str(config),
                     "-C", f"user={user},host=localhost,addr=127.0.0.1"],
                    check=True, capture_output=True, text=True,
                )
                effective = dict((key.lower(), value) for key, value in
                                 (line.split(" ", 1) for line in result.stdout.splitlines()))
                self.assertEqual(effective["permitrootlogin"], "no")
                self.assertEqual(effective["passwordauthentication"], "no")
                self.assertEqual(effective["kbdinteractiveauthentication"], "no")
                self.assertEqual(effective["pubkeyauthentication"], "yes")
                if user == "vpnprobe":
                    self.assertEqual(effective["allowtcpforwarding"], "local")
                    self.assertEqual(effective["allowstreamlocalforwarding"], "no")
                    self.assertEqual(effective["maxsessions"], "0")
                    self.assertEqual(effective["permittty"], "no")
                    self.assertEqual(effective["allowagentforwarding"], "no")
                    self.assertEqual(effective["forcecommand"], "/usr/sbin/nologin")
                else:
                    self.assertEqual(effective["forcecommand"], "none")
                    self.assertNotEqual(effective["maxsessions"], "0")


if __name__ == "__main__":
    unittest.main()
