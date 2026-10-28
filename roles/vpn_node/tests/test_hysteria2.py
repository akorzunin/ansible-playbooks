"""Offline checks for the opt-in dyn1 Hysteria 2 trial."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT / "roles/vpn_node"
PLAYBOOK = ROOT / "infra/cherry-vpn/hysteria2.yaml"


class Hysteria2Tests(unittest.TestCase):
    def setUp(self):
        self.play = yaml.safe_load(PLAYBOOK.read_text())[0]
        self.tasks = yaml.safe_load((ROLE / "tasks/hysteria2.yaml").read_text())
        self.variables = {
            **yaml.safe_load((ROLE / "defaults/main.yaml").read_text()),
            **self.play["vars"],
            "vpn_node_public_address": "192.0.2.10",
            "vpn_node_hysteria2_password": "fixture-password-" * 4,
            "vpn_node_hysteria2_certificate_dir": "/fixture/domain-certificates",
            "ansible_facts": {"getent_passwd": {"vpnproxy": ["x", "1234", "1234"]}},
        }
        self.environment = Environment(loader=FileSystemLoader(ROLE / "templates"), undefined=StrictUndefined)
        self.environment.filters.update({"to_json": json.dumps, "to_nice_json": json.dumps})
        outbound = next(t["ansible.builtin.set_fact"]["vpn_node_hysteria2_outbound"]
                        for t in self.tasks if "vpn_node_hysteria2_outbound" in t.get("ansible.builtin.set_fact", {}))
        self.outbound = self.render_values(outbound)
        self.variables["vpn_node_hysteria2_outbound"] = self.outbound

    def render_values(self, value):
        if isinstance(value, dict):
            return {k: self.render_values(v) for k, v in value.items()}
        if isinstance(value, str):
            result = self.environment.from_string(value).render(**self.variables)
            return int(result) if result.isdigit() else result
        return value

    def render(self, name):
        return self.environment.get_template(name).render(**self.variables)

    def test_brutal_bandwidth_directions_authentication_and_verified_tls(self):
        inbound = json.loads(self.render("hysteria2.json.j2"))["inbounds"][0]
        self.assertEqual(inbound["type"], "hysteria2")
        self.assertFalse(inbound["ignore_client_bandwidth"])
        self.assertGreater(self.outbound["up_mbps"], 0)
        self.assertGreater(self.outbound["down_mbps"], 0)
        self.assertEqual(inbound["up_mbps"], self.outbound["down_mbps"])
        self.assertEqual(inbound["down_mbps"], self.outbound["up_mbps"])
        self.assertEqual(inbound["users"][0]["password"], self.outbound["password"])
        self.assertEqual(inbound["tls"]["server_name"], self.outbound["tls"]["server_name"])
        self.assertNotIn("insecure", self.outbound["tls"])

    def test_container_is_unprivileged_udp_only_and_mounts_only_domain_certificates(self):
        compose = yaml.safe_load(self.render("hysteria2-compose.yaml.j2"))
        self.assertEqual(list(compose["services"]), ["hysteria2"])
        service = compose["services"]["hysteria2"]
        self.assertEqual(service["ports"], ["0.0.0.0:443:8443/udp"])
        self.assertEqual(service["user"], "1234:1234")
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", service["security_opt"])
        self.assertTrue(all(v.endswith(":ro") for v in service["volumes"]))
        self.assertIn("/fixture/domain-certificates:/etc/vpn/certificate:ro", service["volumes"])
        self.assertNotIn("/var/lib/vpn-node:/var/lib/vpn-node:rw", service["volumes"])
        self.assertRegex(service["image"], r"@sha256:[0-9a-f]{64}$")

    def test_trial_never_changes_active_client_or_existing_compose_project(self):
        self.assertEqual(self.play["hosts"], "cherry_vpn_test")
        self.assertTrue(self.play["vars"]["ansible_host_key_checking"])
        client = json.loads(self.render("hysteria2-client.json.j2"))
        self.assertEqual(client["inbounds"], [{
            "type": "mixed", "tag": "trial", "listen": "127.0.0.1", "listen_port": 12343,
        }])
        self.assertEqual(client["route"]["default_mark"], 0x2024)
        self.assertEqual(client["outbounds"], [self.outbound])
        compose_task = next(t["community.docker.docker_compose_v2"] for t in self.tasks
                            if "community.docker.docker_compose_v2" in t)
        self.assertEqual(compose_task["project_name"], "vpn-hysteria2")
        self.assertEqual(compose_task["project_src"], "/srv/deploy/vpn-hysteria2")
        names = [t["name"] for t in self.tasks]
        self.assertLess(names.index("Validate the server candidate and certificate access before activation"),
                        names.index("Activate the validated Hysteria 2 server configuration"))
        credential = self.play["pre_tasks"][1]
        self.assertTrue(credential["no_log"])
        self.assertTrue(credential["ansible.builtin.include_vars"]["file"].endswith("/hysteria2.vault.yaml"))

    def test_full_flow_reuses_the_compose_deployment_after_certificate_issuance(self):
        main = yaml.safe_load((ROLE / "tasks/main.yaml").read_text())
        imports = [task["ansible.builtin.import_tasks"] for task in main]
        self.assertLess(imports.index("proxies.yaml"), imports.index("hysteria2.yaml"))
        self.assertLess(imports.index("hysteria2.yaml"), imports.index("clients.yaml"))
        full = yaml.safe_load((ROOT / "infra/cherry-vpn/deploy.yaml").read_text())[1]
        credential = next(task for task in full["pre_tasks"]
                          if task.get("ansible.builtin.include_vars", {}).get("file", "").endswith("/hysteria2.vault.yaml"))
        self.assertTrue(credential["no_log"])
        # Replacement consumes the shared Vault; it must never mint a new password.
        self.assertFalse(any("ansible.builtin.command" in task for task in full["pre_tasks"]))
        validate = yaml.safe_load((ROLE / "tasks/validate.yaml").read_text())
        self.assertIn("vpn_node_hysteria2_password | length >= 32", validate[1]["ansible.builtin.assert"]["that"])

    @unittest.skipUnless(shutil.which("sing-box") and shutil.which("openssl"), "sing-box/openssl unavailable")
    def test_rendered_server_and_client_pass_actual_core_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            certificate = directory / "cert.pem"
            key = directory / "key.pem"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                "-nodes", "-days", "1", "-subj", "/CN=fixture", "-out", str(certificate), "-keyout", str(key),
            ], check=True, capture_output=True)
            server = json.loads(self.render("hysteria2.json.j2"))
            server["inbounds"][0]["tls"].update(certificate_path=str(certificate), key_path=str(key))
            client = json.loads(self.render("hysteria2-client.json.j2"))
            for name, profile in (("server", server), ("client", client)):
                config = directory / f"{name}.json"
                config.write_text(json.dumps(profile))
                result = subprocess.run(["sing-box", "check", "-c", str(config)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
