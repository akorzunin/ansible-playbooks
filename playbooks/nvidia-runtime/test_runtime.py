"""Static contracts; the opt-in shell regression requires the GPU workstation."""
from pathlib import Path
import unittest

import yaml

HERE = Path(__file__).resolve().parent
DEVICES = {
    f"/dev/{name}:/dev/{name}:rw"
    for name in ("nvidia0", "nvidiactl", "nvidia-uvm", "nvidia-uvm-tools")
}


class NvidiaRuntimeTests(unittest.TestCase):
    def test_gpu_permissions_are_declared_to_docker(self):
        for stack, service in (("jellyfin", "jellyfin"), ("arr", "prepare")):
            with self.subTest(stack=stack):
                config = yaml.safe_load((HERE.parent / stack / "compose.yaml").read_text())
                gpu = config["services"][service]
                self.assertEqual(set(gpu["devices"]), DEVICES)
                self.assertEqual(gpu["runtime"], "nvidia")
                self.assertFalse(gpu.get("privileged", False))
                self.assertNotIn("device_cgroup_rules", gpu)
        arr = yaml.safe_load((HERE.parent / "arr/compose.yaml").read_text())
        self.assertNotIn("devices", arr["services"]["bot"])
        self.assertEqual(arr["services"]["prepare"]["cap_drop"], ["ALL"])
        self.assertTrue(arr["services"]["prepare"]["read_only"])

    def test_links_persist_without_docker_restart_or_driver_upgrade(self):
        play = yaml.safe_load((HERE / "deploy.yaml").read_text())[0]
        self.assertEqual(play["hosts"], "local_workstation,remote_workstation")
        tasks = play["tasks"]
        copies = {task["ansible.builtin.copy"]["dest"]: task["ansible.builtin.copy"]
                  for task in tasks if "ansible.builtin.copy" in task}
        unit = copies["/etc/systemd/system/nvidia-dev-char.service"]["content"]
        self.assertIn("Before=docker.service", unit)
        self.assertIn("After=systemd-udev-settle.service", unit)
        self.assertIn("ExecStartPre=/sbin/modprobe nvidia_uvm", unit)
        self.assertIn("ExecStart=/usr/bin/nvidia-ctk system create-dev-char-symlinks\n", unit)
        self.assertIn("WantedBy=multi-user.target", unit)
        rule = copies["/etc/udev/rules.d/71-nvidia-dev-char.rules"]["content"]
        self.assertIn('DEVPATH=="/bus/pci/drivers/nvidia"', rule)
        self.assertIn('RUN+="/usr/bin/nvidia-ctk system create-dev-char-symlinks"', rule)
        service = next(task["ansible.builtin.systemd_service"] for task in tasks
                       if "ansible.builtin.systemd_service" in task)
        self.assertEqual(service["name"], "nvidia-dev-char.service")
        self.assertEqual(service["state"], "started")
        self.assertTrue(service["enabled"])
        self.assertEqual(service["daemon_reload"], "{{ nvidia_dev_char_unit.changed }}")
        self.assertNotIn("ansible.builtin.apt", str(tasks))

    def test_regression_covers_updates_and_systemd_reload(self):
        script = (HERE / "test-gpu-access.sh").read_text()
        for device in DEVICES:
            self.assertIn(f"--device {device}", script)
        self.assertIn("docker update --cpus 1", script)
        self.assertIn("systemctl daemon-reload", script)
        self.assertIn("trap cleanup EXIT", script)
        self.assertIn("--network none", script)
        self.assertNotIn("--privileged", script)


if __name__ == "__main__":
    unittest.main()
