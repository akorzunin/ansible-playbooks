"""Keep the publish-time SSH policy aligned with Cherry's generated profiles."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jinja2.nativetypes import NativeEnvironment
import yaml

import generate


class WorkstationHopTests(unittest.TestCase):
    def test_both_allowlists_follow_published_direct_ssh_exits(self):
        play = yaml.safe_load((Path(__file__).with_name("workstation-hop.yaml")).read_text())[0]
        environment = NativeEnvironment()
        environment.filters.update(from_json=json.loads, zip=zip)
        connections = {kind: {"type": kind, "tag": kind} for kind in ("ssh", "naive", "vless")}
        connections["ssh"].update(server="192.0.2.1", server_port=22, host_key=["nt1-pin"])
        hop = {"type": "ssh", "tag": "workstation-hop", "server": "192.0.2.3", "server_port": 22123}
        cherry = {"type": "ssh", "tag": "cherry-ssh", "server": "192.0.2.2",
                  "server_port": 22, "host_key": ["cherry-pin"]}
        tokens = {platform: str(i) * 64 for i, platform in enumerate(generate.ORDERS)}
        with tempfile.TemporaryDirectory() as work, patch.object(generate.subprocess, "run"):
            for exits in ([cherry], []):
                with self.subTest(cherry_published=bool(exits)):
                    generate.generate(Path(work), connections, tokens, [hop, *exits])
                    profile = (Path(work) / "linux.json").read_text()
                    variables = {"playbook_dir": str(generate.ROOT),
                                 "sing_box_secrets": {"workstation_ssh_public_key": "ssh-ed25519 test"},
                                 "lookup": lambda *_args: profile}
                    for name in ("hop_destinations", "hop_permit_open"):
                        variables[name] = environment.from_string(play["vars"][name]).render(**variables)
                    expected = [connections["ssh"], *exits]
                    self.assertEqual(variables["hop_destinations"], expected)
                    key_task = next(t for t in play["tasks"] if "ansible.builtin.copy" in t)
                    key = environment.from_string(key_task["ansible.builtin.copy"]["content"]).render(**variables)
                    policy_task = next(t for t in play["tasks"] if "ansible.builtin.blockinfile" in t)
                    policy = environment.from_string(policy_task["ansible.builtin.blockinfile"]["block"]).render(
                        **variables, hop_user="sing-box-hop")
                    destinations = [f"{exit['server']}:{exit['server_port']}" for exit in expected]
                    self.assertIn("PermitOpen " + " ".join(destinations) + "\n", policy)
                    for destination in destinations:
                        self.assertIn(f',permitopen="{destination}"', key)
                    self.assertNotIn("192.0.2.3", key + policy)
                    self.assertNotIn("permitopen=\"*", key)
                    self.assertIn("MaxSessions 0", policy)
