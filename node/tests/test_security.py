"""Offline checks for Debian/Ubuntu security policy; never change host apt or services."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
TASKS = yaml.safe_load((ROOT / "roles/node/tasks/setup_node.yaml").read_text())


class SecurityTests(unittest.TestCase):
    def test_rendered_unattended_policy_for_debian_13_and_ubuntu(self):
        for distribution, release in (("Debian", "trixie"), ("Ubuntu", "noble")):
            with self.subTest(distribution=distribution), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                tasks = []
                for task in TASKS:
                    copy = task.get("ansible.builtin.copy", {})
                    if not copy.get("dest", "").startswith("/etc/apt/apt.conf.d/"):
                        continue
                    tasks.append({
                        "name": task["name"],
                        "ansible.builtin.copy": {
                            **copy, "dest": str(directory / Path(copy["dest"]).name),
                            "owner": str(os.getuid()), "group": str(os.getgid()),
                        },
                    })
                playbook = directory / "render.yml"
                playbook.write_text(yaml.safe_dump([{
                    "name": "Render security policy offline", "hosts": "localhost",
                    "connection": "local", "gather_facts": False,
                    "vars": {"ansible_facts": {
                        "distribution": distribution, "distribution_release": release,
                    }},
                    "tasks": tasks,
                }]))
                config = directory / "ansible.cfg"
                config.write_text("[defaults]\n")
                environment = {
                    **os.environ, "ANSIBLE_CONFIG": str(config), "ANSIBLE_NOCOLOR": "1",
                    "ANSIBLE_LOCAL_TEMP": str(directory / "local-tmp"),
                    "ANSIBLE_REMOTE_TEMP": str(directory / "remote-tmp"),
                }
                for run in range(2):
                    result = subprocess.run(
                        ["ansible-playbook", "-i", "localhost,", str(playbook)],
                        env=environment, capture_output=True, text=True, timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    if run == 1:
                        self.assertIn("changed=0", result.stdout)
                periodic = (directory / "20auto-upgrades").read_text()
                for setting in ("Enable", "Update-Package-Lists", "Unattended-Upgrade"):
                    self.assertIn(f'APT::Periodic::{setting} "1";', periodic)
                self.assertIn('Automatic-Reboot "false";', (directory / "99no-auto-reboot").read_text())
                policy = (directory / "99node-security").read_text()
                self.assertIn("#clear Unattended-Upgrade::Allowed-Origins;", policy)
                self.assertIn("#clear Unattended-Upgrade::Origins-Pattern;", policy)
                self.assertNotIn("{%", policy)
                # apt, not Jinja, must expand the running distribution's release.
                self.assertIn("${distro_codename}", policy)
                if distribution == "Debian":
                    self.assertIn('"origin=Debian,codename=${distro_codename}-security,label=Debian-Security";', policy)
                    self.assertNotIn("ESM", policy)
                else:
                    for origin in (
                        "${distro_id}:${distro_codename}-security",
                        "${distro_id}ESMApps:${distro_codename}-apps-security",
                        "${distro_id}ESM:${distro_codename}-infra-security",
                    ):
                        self.assertIn(f'"{origin}";', policy)
                    self.assertNotIn("Debian-Security", policy)
                self.assertNotIn("-updates", policy)
                self.assertNotIn("download.docker.com", policy)

    def test_docker_repository_uses_deb822_and_migrates_legacy_source(self):
        self.assertFalse(any("ansible.builtin.apt_repository" in task for task in TASKS))
        packages = next(task for task in TASKS if task["name"] == "Install prerequisite and security packages")
        self.assertIn("python3-debian", packages["ansible.builtin.apt"]["name"])
        legacy = next(task for task in TASKS if task["name"] == "Remove legacy Docker apt repository")
        self.assertEqual(legacy["ansible.builtin.file"], {
            "path": "/etc/apt/sources.list.d/docker.list", "state": "absent",
        })
        repository = next(task for task in TASKS if task["name"] == "Add Docker apt repository")
        self.assertEqual(repository["ansible.builtin.deb822_repository"], {
            "name": "docker", "types": ["deb"],
            "uris": "https://download.docker.com/linux/{{ ansible_facts.distribution | lower }}",
            "suites": ["{{ ansible_facts.distribution_release }}"],
            "components": ["stable"], "architectures": ["{{ node_dpkg_architecture.stdout }}"],
            "signed_by": "/etc/apt/keyrings/docker.asc", "state": "present",
        })
        install = next(task for task in TASKS if task["name"] == "Install Docker packages")
        self.assertTrue(install["ansible.builtin.apt"]["update_cache"])
        self.assertLess(TASKS.index(packages), TASKS.index(repository))
        self.assertLess(TASKS.index(legacy), TASKS.index(repository))
        self.assertLess(TASKS.index(repository), TASKS.index(install))

    def test_apparmor_is_installed_enabled_and_verified_before_docker(self):
        packages = next(task["ansible.builtin.apt"]["name"] for task in TASKS
                        if task["name"] == "Install prerequisite and security packages")
        self.assertIn("apparmor", packages)
        services = next(task for task in TASKS if task["name"] == "Enable security services and apt timers")
        self.assertEqual(services["ansible.builtin.systemd_service"]["state"], "started")
        self.assertTrue(services["ansible.builtin.systemd_service"]["enabled"])
        for service in ("apparmor", "sshguard", "apt-daily.timer", "apt-daily-upgrade.timer"):
            self.assertIn(service, services["loop"])
        check = next(task for task in TASKS if task.get("ansible.builtin.command") == "aa-enabled")
        assertion = next(task for task in TASKS if task["name"] == "Require active AppArmor before installing Docker")
        self.assertFalse(check["changed_when"])
        self.assertEqual(assertion["ansible.builtin.assert"]["that"], "node_apparmor_enabled.rc == 0")
        names = [task["name"] for task in TASKS]
        self.assertLess(names.index(services["name"]), names.index(check["name"]))
        self.assertLess(names.index(check["name"]), names.index(assertion["name"]))
        self.assertLess(names.index(assertion["name"]), names.index("Install Docker packages"))


if __name__ == "__main__":
    unittest.main()
