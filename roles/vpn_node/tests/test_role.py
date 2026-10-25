"""Offline rendering checks for server/client agreement and container isolation."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT / "roles/vpn_node"
spec = importlib.util.spec_from_file_location("vpn_credentials", ROOT / "infra/cherry-vpn/prepare-secrets.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class RoleTests(unittest.TestCase):
    def setUp(self):
        self.environment = Environment(loader=FileSystemLoader(ROLE / "templates"), undefined=StrictUndefined)
        self.environment.filters["to_nice_json"] = lambda value: json.dumps(value, indent=2)
        self.credentials = prepare.credentials()
        self.variables = {
            "vpn_node_name": "cherry", "vpn_node_domain": "vpn.example.org",
            "vpn_node_public_address": "192.0.2.10", "vpn_node_reality_server_name": "www.google.com",
            "vpn_node_credentials": self.credentials,
            "ansible_facts": {"getent_passwd": {"vpnproxy": ["x", "1234", "1234"]}},
        }

    def render(self, name):
        return self.environment.get_template(name).render(**self.variables)

    def test_reality_configuration_and_unprivileged_containers(self):
        server = json.loads(self.render("vless.json.j2"))
        inbound = server["inbounds"][0]
        self.assertEqual(inbound["listen_port"], 8443)
        self.assertEqual(inbound["users"][0], {
            "uuid": self.credentials["vless_uuid"], "flow": "xtls-rprx-vision",
        })
        reality = inbound["tls"]["reality"]
        self.assertEqual(reality["private_key"], self.credentials["reality_private_key"])
        self.assertEqual(reality["short_id"], [self.credentials["reality_short_id"]])
        self.assertEqual(inbound["tls"]["server_name"], self.variables["vpn_node_reality_server_name"])
        compose = yaml.safe_load(self.render("compose.yaml.j2"))
        self.assertEqual(set(compose["services"]), {"naive", "vless"})
        for service in compose["services"].values():
            self.assertEqual(service["user"], "1234:1234")
            self.assertTrue(service["read_only"])
            self.assertEqual(service["tmpfs"], ["/tmp:size=16m,mode=1777"])
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertIn("no-new-privileges:true", service["security_opt"])
            self.assertNotIn("network_mode", service)
            self.assertNotIn("privileged", service)
            self.assertIn("mem_limit", service)
            self.assertEqual(service["logging"]["options"]["max-file"], "3")
        self.assertEqual(compose["services"]["naive"]["ports"], ["80:8080", "443:8443"])
        self.assertEqual(compose["services"]["vless"]["ports"], ["8443:8443"])
        caddy = self.render("Caddyfile.j2")
        self.assertIn("protocols h1 h2", caddy)
        self.assertIn("probe_resistance", caddy)
        self.assertIn(f"basic_auth vpn {self.credentials['naive_password']}", caddy)
        self.assertIn("admin off", caddy)

    def test_client_export_never_contains_admin_key_and_is_isolated_from_active_client(self):
        tasks = yaml.safe_load((ROLE / "tasks/clients.yaml").read_text())
        connections = next(t["ansible.builtin.set_fact"]["vpn_node_client_outbounds"] for t in tasks
                           if "ansible.builtin.set_fact" in t)
        self.assertEqual([o["type"] for o in connections], ["ssh", "naive", "vless"])
        self.assertIn("vpn_node_ssh_private_key_path", connections[0]["private_key"])
        self.assertIn("vpn_node_host_key", connections[0]["host_key"][0])
        self.assertEqual(connections[0]["user"], "vpnprobe")
        self.assertNotIn("admin", json.dumps(connections))
        self.assertNotIn("insecure", json.dumps(connections))
        self.variables["vpn_node_client_outbounds"] = [
            {"type": "ssh", "tag": "cherry-ssh"},
            {"type": "naive", "tag": "cherry-naive"},
            {"type": "vless", "tag": "cherry-vless"},
        ]
        client = json.loads(self.render("client-test.json.j2"))
        self.assertEqual([i["listen_port"] for i in client["inbounds"]], [12340, 12341, 12342])
        self.assertTrue(all(i["listen"] == "127.0.0.1" for i in client["inbounds"]))
        self.assertNotIn("experimental", client)
        self.assertNotIn("tun", json.dumps(client))
        self.assertEqual([r["outbound"] for r in client["route"]["rules"]],
                         ["cherry-ssh", "cherry-naive", "cherry-vless"])
        for task in tasks:
            if any(module in task for module in ("ansible.builtin.set_fact", "ansible.builtin.copy", "ansible.builtin.template")):
                self.assertTrue(task["no_log"])

    def test_preconditions_and_both_server_validations_precede_activation(self):
        main = yaml.safe_load((ROLE / "tasks/main.yaml").read_text())
        self.assertEqual(main[0]["ansible.builtin.import_tasks"], "validate.yaml")
        tasks = yaml.safe_load((ROLE / "tasks/proxies.yaml").read_text())
        names = [t["name"] for t in tasks]
        activation = names.index("Activate the validated proxy configuration files")
        self.assertLess(names.index("Validate Naive configuration in its pinned container before activation"), activation)
        self.assertLess(names.index("Validate VLESS configuration in its pinned container before activation"), activation)
        downloads = next(t for t in tasks if "ansible.builtin.get_url" in t)
        self.assertRegex(downloads["ansible.builtin.get_url"]["checksum"], r"^sha256:[0-9a-f]{64}$")
        build = next(t for t in tasks if "community.docker.docker_image" in t)
        self.assertIn("vpn_node_server_binary.changed", build["community.docker.docker_image"]["force_source"])
        pull = next(t["community.docker.docker_image"] for t in tasks
                    if t.get("community.docker.docker_image", {}).get("source") == "pull")
        compose = yaml.safe_load(self.render("compose.yaml.j2"))
        self.assertEqual(compose["services"]["vless"]["image"], pull["name"])
        self.assertRegex(pull["name"], r"@sha256:[0-9a-f]{64}$")
        self.assertEqual((ROLE / "files/Dockerfile").read_text().splitlines()[0], "FROM scratch")
        self.assertNotIn("RUN", (ROLE / "files/Dockerfile").read_text())
        self.assertTrue((ROLE / "files/.dockerignore").read_text().startswith("*\n"))

    def test_duckdns_update_is_scoped_private_and_handles_provider_responses(self):
        tasks = yaml.safe_load((ROLE / "tasks/dns.yaml").read_text())
        task = next(t for t in tasks if "ansible.builtin.uri" in t)
        request = task["ansible.builtin.uri"]
        self.assertTrue(task["no_log"])
        self.assertFalse(request["use_proxy"])
        self.assertEqual(request["follow_redirects"], "none")
        self.assertTrue(request["validate_certs"])
        self.assertEqual(request["method"], "GET")
        self.assertIn("https://www.duckdns.org/update?domains=", request["url"])
        self.assertIn("vpn_node_public_address | urlencode", request["url"])
        self.assertIn("vpn_node_duckdns_token | urlencode", request["url"])
        self.assertNotIn("clear=true", request["url"])
        self.environment.tests["search"] = lambda value, pattern: re.search(pattern, value) is not None
        guard = next(t for t in tasks if t["name"] == "Require a decrypted single-line DuckDNS token")
        self.assertTrue(guard["no_log"])
        token_checks = [self.environment.compile_expression(expression) for expression in
                        guard["ansible.builtin.assert"]["that"]]
        for token, expected in (("fixture-token", True), ("bad token", False),
                                ("$ANSIBLE_VAULT;ciphertext", False)):
            self.assertEqual(all(check(vpn_node_duckdns_token=token) for check in token_checks), expected)
        self.assertFalse(task["failed_when"])
        acceptance = next(t for t in tasks if t["name"].startswith("Require DuckDNS to accept"))
        checks = [self.environment.compile_expression(expression) for expression in
                  acceptance["ansible.builtin.assert"]["that"]]
        changed = self.environment.compile_expression(task["changed_when"])
        for status, content, expect_failure, expect_change in (
            (200, "OK\n192.0.2.10\n\nUPDATED\n", False, True),
            (200, "OK\n192.0.2.10\n\nNOCHANGE\n", False, False),
            (200, "KO", True, False),
            (200, "", True, False),
            (503, "OK\n", True, False),
        ):
            result = {"vpn_node_duckdns_result": {"status": status, "content": content}}
            self.assertEqual(not all(check(**result) for check in checks), expect_failure)
            self.assertEqual(changed(**result), expect_change)
        for domain, token, expected in (("akorz-dyn1.duckdns.org", "fixture", True),
                                        ("akorz-dyn1.duckdns.org", "", False),
                                        ("vpn.example.org", "fixture", False)):
            values = {"vpn_node_domain": domain, "vpn_node_duckdns_token": token}
            self.assertEqual(all(self.environment.compile_expression(condition)(**values)
                                 for condition in task["when"]), expected)
        self.assertLess(tasks.index(next(t for t in tasks if t["name"].startswith("Validate the public IPv4"))),
                        tasks.index(task))
        dns_check = tasks[-1]
        self.assertGreater(dns_check["retries"], 0)
        self.assertIn("stale A/AAAA", dns_check["ansible.builtin.command"]["argv"][2])

    @unittest.skipUnless(shutil.which("ansible-playbook") and shutil.which("sing-box") and shutil.which("ssh-keygen"),
                         "Ansible, sing-box or OpenSSH unavailable")
    def test_actual_ansible_client_export_passes_core_check_and_keeps_credentials_private(self):
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            key = directory / "probe"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            self.variables.update({
                "ansible_host": "192.0.2.10", "ansible_port": 22,
                "vpn_node_ssh_private_key_path": str(key),
                "vpn_node_client_dir": str(directory / "clients"),
                "vpn_node_host_key": {"content": base64.b64encode(key.with_suffix(".pub").read_bytes()).decode()},
            })
            inputs = directory / "inputs.json"
            inputs.write_text(json.dumps(self.variables))
            inputs.chmod(0o600)
            playbook = directory / "export.yaml"
            playbook.write_text(yaml.safe_dump([{
                "name": "Render only with fixture keys; no server connections",
                "hosts": "localhost", "connection": "local", "gather_facts": False,
                "tasks": [{"ansible.builtin.import_role": {"name": "vpn_node", "tasks_from": "clients"}}],
            }]))
            config = directory / "ansible.cfg"
            config.write_text("[defaults]\n")
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(playbook), "-e", "@" + str(inputs),
                 "--start-at-task", "vpn_node : Prepare private client connections without the administrator key"],
                env={**os.environ, "ANSIBLE_CONFIG": str(config), "ANSIBLE_ROLES_PATH": str(ROOT / "roles"),
                     "ANSIBLE_LOCAL_TEMP": str(directory / "local-tmp"), "ANSIBLE_NOCOLOR": "1"},
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn(self.credentials["naive_password"], result.stdout + result.stderr)
            clients = directory / "clients"
            outbounds = json.loads((clients / "cherry-outbounds.json").read_text())
            self.assertEqual(outbounds[0]["private_key"].strip(), key.read_text().strip())
            self.assertEqual(outbounds[0]["host_key"][0], key.with_suffix(".pub").read_text().strip())
            self.assertEqual(outbounds[1]["password"], self.credentials["naive_password"])
            self.assertEqual(outbounds[2]["tls"]["reality"]["public_key"], self.credentials["reality_public_key"])
            self.assertEqual(clients.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in clients.iterdir()))

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose unavailable")
    def test_compose_configuration_is_accepted_by_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            compose = Path(directory) / "compose.yaml"
            compose.write_text(self.render("compose.yaml.j2"))
            subprocess.run(["docker", "compose", "-f", str(compose), "config", "--quiet"], check=True,
                           capture_output=True)


if __name__ == "__main__":
    unittest.main()
