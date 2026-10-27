import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("discord_config", Path(__file__).with_name("discord-config.py"))
discord_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discord_config)


class DiscordTests(unittest.TestCase):
    def test_only_namespace_tun_and_required_carrier_are_installed(self):
        chain = {"type": "vless", "tag": "cherry-vless-via-naive", "detour": "cherry-naive"}
        carrier = {"type": "naive", "tag": "cherry-naive", "tls": {"enabled": True}}
        profile = {"outbounds": [chain, carrier, {"type": "direct", "tag": "direct"}]}
        config = discord_config.make_config(profile)
        self.assertEqual(config["outbounds"], [chain, {**carrier, "domain_resolver": "bootstrap"}])
        self.assertEqual(config["inbounds"][0]["netns"], "discord-vpn")
        self.assertTrue(config["inbounds"][0]["auto_route"])
        self.assertNotIn("auto_detect_interface", config["route"])
        self.assertEqual(config["route"]["final"], chain["tag"])
        self.assertEqual(config["dns"]["final"], "dns")
        self.assertEqual(config["dns"]["servers"][1]["detour"], chain["tag"])
        self.assertEqual(config["dns"]["servers"][0], {"type": "local", "tag": "bootstrap"})
        config["outbounds"][1]["tls"]["enabled"] = False
        self.assertTrue(carrier["tls"]["enabled"])

    def test_missing_or_wrong_carrier_is_rejected(self):
        for carrier in ({"type": "ssh", "tag": "cherry-naive"},
                        {"type": "naive", "tag": "cherry-naive", "detour": "other"}):
            with self.assertRaises(ValueError):
                discord_config.make_config({"outbounds": [
                    {"type": "vless", "tag": "cherry-vless-via-naive", "detour": "cherry-naive"}, carrier,
                ]})
        with self.assertRaises(KeyError):
            discord_config.make_config({"outbounds": []})


if __name__ == "__main__":
    unittest.main()
