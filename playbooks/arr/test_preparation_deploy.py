"""Static deployment contract; never contacts Docker, ARR, or Jellyfin."""
from pathlib import Path
import unittest

import yaml

HERE = Path(__file__).resolve().parent


class PreparationDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.services = yaml.safe_load((HERE / "compose.yaml").read_text())["services"]

    def test_worker_is_opt_in_and_gpu_enabled(self):
        worker = self.services["prepare"]
        self.assertEqual(worker["profiles"], ["prepare"])
        self.assertEqual(worker["runtime"], "nvidia")
        self.assertEqual(worker["env_file"], "worker.env")
        self.assertTrue(worker["read_only"])
        self.assertNotIn("ports", worker)
        gpu = worker["deploy"]["resources"]["reservations"]["devices"][0]
        self.assertEqual(gpu["driver"], "nvidia")
        self.assertIn("video", gpu["capabilities"])

    def test_originals_read_only_and_state_shared(self):
        for name in ("bot", "prepare"):
            volumes = self.services[name]["volumes"]
            self.assertIn("/mnt/storage/jellyfin_media:/downloads:ro", volumes)
            self.assertIn("./config/preparation:/preparation", volumes)
        self.assertNotIn("runtime", self.services["bot"])
        self.assertEqual(self.services["bot"]["environment"]["PREPARATION_DIR"], "${ARR_PREPARATION_DIR:-}")

    def test_jellyfin_sees_matching_read_only_paths(self):
        jellyfin = yaml.safe_load((HERE.parent / "jellyfin" / "compose.yaml").read_text())["services"]["jellyfin"]
        worker_mount = next(v for v in self.services["prepare"]["volumes"] if isinstance(v, dict))
        jellyfin_mount = next(v for v in jellyfin["volumes"] if isinstance(v, dict) and v["target"] == "/optimized")
        self.assertEqual(worker_mount["source"], jellyfin_mount["source"])
        self.assertEqual(worker_mount["target"], jellyfin_mount["target"])
        self.assertTrue(jellyfin_mount["read_only"])
        self.assertFalse(worker_mount["bind"]["create_host_path"])
        self.assertFalse(jellyfin_mount["bind"]["create_host_path"])

    def test_deployment_remains_opt_in_and_secrets_private(self):
        deploy = yaml.safe_load((HERE / "deploy.yaml").read_text())[0]
        configure = yaml.safe_load((HERE / "configure.yaml").read_text())[0]
        self.assertFalse(deploy["vars"]["arr_prepare_enabled"])
        self.assertFalse(configure["vars"]["arr_prepare_enabled"])
        tasks = {task["name"]: task for task in deploy["tasks"]}
        self.assertTrue(tasks["Set worker Jellyfin credential"]["no_log"])
        self.assertEqual(tasks["Set worker Jellyfin credential"]["ansible.builtin.lineinfile"]["mode"], "0600")
        self.assertIn("Require the NVIDIA Container Toolkit Docker runtime", tasks)
        self.assertEqual(tasks["Enable or disable bot preparation discovery"]["ansible.builtin.lineinfile"]["regexp"], "^ARR_PREPARATION_DIR=")


if __name__ == "__main__":
    unittest.main()
