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
