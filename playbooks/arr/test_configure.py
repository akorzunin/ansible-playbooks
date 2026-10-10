import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import configure


class ConfigureTests(unittest.TestCase):
    def test_fields_require_known_schema(self):
        obj = {"fields": [{"name": "port", "value": 1}]}
        self.assertIs(configure.fields(obj, {"port": 9092}), obj)
        self.assertEqual(obj["fields"][0]["value"], 9092)
        with self.assertRaises(ValueError):
            configure.fields(obj, {"unknown": True})

    def test_save_updates_named_object_only(self):
        with patch("configure.api", side_effect=[[{"name": "Managed", "id": 8}, {"name": "Unrelated", "id": 9}], {}]) as api:
            configure.save("sonarr", "qualityprofile", {"name": "Managed"})
        self.assertEqual(api.call_args.args, ("sonarr", "qualityprofile/8", {"name": "Managed", "id": 8}, "PUT"))

    def test_save_creates_without_template_id(self):
        with patch("configure.api", side_effect=[[], {"id": 10}]) as api:
            result = configure.save("radarr", "qualityprofile", {"name": "New", "id": 4})
        self.assertEqual(result["id"], 10)
        self.assertEqual(api.call_args.args, ("radarr", "qualityprofile", {"name": "New"}))

    def test_connection_test_uses_existing_id(self):
        with patch("configure.api", side_effect=[[{"name": "Managed", "id": 8}], {}]) as api:
            configure.test("radarr", "downloadclient", {"name": "Managed"})
        self.assertEqual(api.call_args.args, ("radarr", "downloadclient/test", {"name": "Managed", "id": 8}))

    def test_env_update_preserves_token_and_allowlist(self):
        cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                path = Path("bot.env")
                path.write_text("TELEGRAM_BOT_TOKEN=private\nTELEGRAM_ALLOWED_USERS=42\nRADARR_API_KEY=old\n")
                configure.set_env({"RADARR_API_KEY": "new", "RADARR_QUALITY_PROFILE_ID": 7})
                text = path.read_text()
                self.assertIn("TELEGRAM_BOT_TOKEN=private\n", text)
                self.assertIn("TELEGRAM_ALLOWED_USERS=42\n", text)
                self.assertEqual(text.count("RADARR_API_KEY="), 1)
                self.assertIn("RADARR_API_KEY=new\n", text)
                self.assertIn("RADARR_QUALITY_PROFILE_ID=7\n", text)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            finally:
                os.chdir(cwd)

    def test_managed_indexers_sync_seeder_threshold_and_magnets(self):
        names = ("Nyaa.si", "1337x", "RuTracker.org", "The Pirate Bay")
        schemas = [{"name": name, "fields": [{"name": field} for field in
                    ("baseUrl", "torrentBaseSettings.appMinimumSeeders", "torrentBaseSettings.preferMagnetUrl",
                     "cat-id", "prefer_magnet_links", "username", "password")]} for name in names]

        def api(app, path, data=None, method=None):
            if path == "tag":
                return [{"id": 7, "label": "arr-cloudflare"}]
            if path == "indexerproxy/schema":
                return [{"implementation": "FlareSolverr", "fields": [{"name": "host"}, {"name": "requestTimeout"}]}]
            if path == "indexer/schema":
                return schemas
            if path == "applications/schema":
                return [{"implementation": app_name, "fields": [{"name": "prowlarrUrl"}, {"name": "baseUrl"},
                         {"name": "apiKey"}, {"name": "syncCategories", "value": [2000]}]} for app_name in ("radarr", "sonarr")]
            return {}

        with patch("configure.api", side_effect=api) as mocked_api, patch("configure.test"), patch("configure.save") as save, \
                patch.dict(configure.KEYS, {"radarr": "rk", "sonarr": "sk"}), \
                patch.dict(os.environ, {"RUTRACKER_USER": "user", "RUTRACKER_PASS": "pass"}):
            configure.configure_indexers()
        indexers = [c.args[2] for c in save.call_args_list if c.args[1] == "indexer"]
        self.assertEqual([x["name"] for x in indexers], list(names))
        for indexer in indexers:
            values = {f["name"]: f.get("value") for f in indexer["fields"]}
            self.assertEqual(values["torrentBaseSettings.appMinimumSeeders"], 5)
            self.assertIs(values["torrentBaseSettings.preferMagnetUrl"], True)
            self.assertEqual(indexer["tags"], [7] if indexer["name"] in ("1337x", "RuTracker.org") else [])
        applications = [c.args[2] for c in save.call_args_list if c.args[1] == "applications"]
        self.assertTrue(all(x["syncLevel"] == "fullSync" for x in applications))
        mocked_api.assert_any_call("prowlarr", "command", {"name": "ApplicationIndexerSync"})
        # Templates are copied rather than mutated across reruns.
        self.assertNotIn("value", schemas[0]["fields"][0])

    def test_api_error_does_not_include_validation_secrets(self):
        from io import BytesIO
        from urllib.error import HTTPError
        error = HTTPError("http://localhost/", 400, "Bad request", {},
                          BytesIO(b'[{"propertyName":"Password","errorMessage":"private-token"}]'))
        with patch.dict(configure.KEYS, {"prowlarr": "private-key"}), patch("configure.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                configure.api("prowlarr", "indexer/test", {"password": "private"})
        self.assertIn("Password", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
