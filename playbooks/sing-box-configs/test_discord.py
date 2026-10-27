import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("discord_config", Path(__file__).with_name("discord-config.py"))
discord_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discord_config)


class DiscordTests(unittest.TestCase):
    def test_only_namespace_tun_and_wifi_bound_vless_are_installed(self):
        outbound = {"type": "vless", "tag": "cherry-vless", "flow": "xtls-rprx-vision",
                    "tls": {"enabled": True}}
        profile = {"outbounds": [outbound, {"type": "direct", "tag": "direct"}]}
        original = copy.deepcopy(profile)
        config = discord_config.make_config(profile)
        self.assertEqual(config["outbounds"], [{
            **outbound, "domain_resolver": "bootstrap", "bind_interface": "wlan0",
            "routing_mark": 0x2024, "packet_encoding": "xudp",
        }])
        self.assertEqual(profile, original)
        self.assertEqual(config["inbounds"][0]["netns"], "discord-vpn")
        self.assertEqual(config["inbounds"][0]["stack"], "gvisor")
        self.assertTrue(config["inbounds"][0]["auto_route"])
        self.assertNotIn("auto_detect_interface", config["route"])
        self.assertEqual(config["route"]["final"], outbound["tag"])
        self.assertEqual(config["dns"]["final"], "dns")
        self.assertEqual(config["dns"]["strategy"], "ipv4_only")
        self.assertEqual(config["dns"]["servers"][1], {
            "type": "tcp", "tag": "dns", "server": "1.1.1.1", "detour": outbound["tag"],
        })
        self.assertEqual(config["dns"]["servers"][0], {
            "type": "udp", "tag": "bootstrap", "server": "1.1.1.1",
            "bind_interface": "wlan0", "routing_mark": 0x2024,
        })
        config["outbounds"][0]["tls"]["enabled"] = False
        self.assertTrue(outbound["tls"]["enabled"])

    def test_missing_wrong_or_chained_vless_is_rejected(self):
        for outbound in ({"type": "ssh", "tag": "cherry-vless"},
                         {"type": "vless", "tag": "cherry-vless", "detour": "other"}):
            with self.assertRaises(ValueError):
                discord_config.make_config({"outbounds": [outbound]})
        with self.assertRaises(KeyError):
            discord_config.make_config({"outbounds": []})


if __name__ == "__main__":
    unittest.main()
