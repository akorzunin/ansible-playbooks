#!/usr/bin/env python3
"""Exercise the macOS updater with OS/network commands replaced by local fakes."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

import generate


@unittest.skipIf(os.geteuid() == 0, "macOS setup deliberately rejects root")
class MacSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        for name in ("mkdir", "chmod", "mktemp", "rm", "rmdir", "cp", "mv", "tar", "gzip", "shasum", "awk", "id", "touch"):
            (self.bin / name).symlink_to(shutil.which(name))
        self.root = self.home / "Library/Application Support/sing-box-remote"
        self.root.mkdir(parents=True)
        self.agent = self.home / "Library/LaunchAgents/io.github.akorzunin.sing-box-remote.plist"
        self.profile = self.home / "download.json"
        self.profile.write_text('{"outbounds": [{"type": "direct"}], "route": {"final": "direct"}}')
        self.core_script = '#!/bin/sh\n[ "${CHECK_FAIL:-0}" = 0 ]\n'
        self.fake("sing-box", self.core_script)
        self.fake("uname", '#!/bin/sh\nif [ "$1" = -s ]; then echo Darwin; else echo arm64; fi\n')
        self.fake("pgrep", '#!/bin/sh\nexit "${EXISTING_CORE:-1}"\n')
        self.fake("sleep", '#!/bin/sh\nexit 0\n')
        self.fake("plutil", '#!/bin/sh\nexit 0\n')
        self.fake("curl", '''#!/bin/bash
out=''
url=''
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) out=$2; shift ;;
        https://*) url=$1 ;;
    esac
    shift
done
[[ ${DOWNLOAD_FAIL:-0} == 0 ]] || exit 1
if [[ $url == *github.com* ]]; then
    cp "$HOME/archive.tar.gz" "$out"
else
    cp "$HOME/download.json" "$out"
    printf '%s' "${HTTP_STATUS:-200}"
fi
''')
        self.fake("launchctl", '''#!/bin/bash
state="$HOME/loaded"
case "$1" in
    print) test -f "$state" ;;
    bootout) rm -f "$state" ;;
    bootstrap)
        if [[ -f $HOME/fail-start ]]; then rm "$HOME/fail-start"; exit 1; fi
        touch "$state" ;;
    list) if [[ -f $state ]]; then echo '1234 0 io.github.akorzunin.sing-box-remote'; fi ;;
esac
''')
        self.environment = {**os.environ, "HOME": str(self.home), "PATH": str(self.bin)}
        self.script = self.home / "setup.sh"
        self.script.write_text((generate.ROOT / "setup-macos.sh").read_text().replace(
            "__PROFILE_URL__", "https://profiles.example/PRIVATE_TOKEN/linux.json"))

    def fake(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o700)

    def run_setup(self, **environment):
        return subprocess.run(["/bin/bash", str(self.script)], env={**self.environment, **environment},
                              capture_output=True, text=True, timeout=10)

    def test_enroll_and_refresh_reuses_existing_core_and_private_config(self):
        for content in ('{"new": 1}', '{"new": 2}'):
            self.profile.write_text(content)
            result = self.run_setup()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.root / "config.json").read_text(), content)
            self.assertEqual((self.root / "config.json").stat().st_mode & 0o777, 0o600)
            self.assertTrue(self.agent.exists())
            self.assertTrue((self.home / "loaded").exists())
            self.assertFalse((self.root / "core").exists())
            self.assertFalse((self.root / ".update-lock").exists())
            self.assertNotIn("PRIVATE_TOKEN", result.stdout + result.stderr)

    def test_download_validation_redirect_and_competing_core_fail_before_activation(self):
        config = self.root / "config.json"
        config.write_text("previous")
        for environment in ({"DOWNLOAD_FAIL": "1"}, {"CHECK_FAIL": "1"},
                            {"HTTP_STATUS": "302"}, {"EXISTING_CORE": "0"}):
            with self.subTest(environment=environment):
                result = self.run_setup(**environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(config.read_text(), "previous")
                self.assertFalse(self.agent.exists())
                self.assertFalse((self.root / ".update-lock").exists())
                self.assertNotIn("PRIVATE_TOKEN", result.stdout + result.stderr)

    def test_failed_start_restores_previous_config_and_agent(self):
        config = self.root / "config.json"
        config.write_text("previous config")
        self.agent.parent.mkdir(parents=True)
        self.agent.write_text("previous agent")
        (self.home / "loaded").touch()
        (self.home / "fail-start").touch()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(config.read_text(), "previous config")
        self.assertEqual(self.agent.read_text(), "previous agent")
        self.assertTrue((self.home / "loaded").exists())

    def test_failed_first_start_removes_new_files(self):
        (self.home / "fail-start").touch()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "config.json").exists())
        self.assertFalse(self.agent.exists())

    def test_install_missing_core_with_verified_archive(self):
        (self.bin / "sing-box").unlink()
        content = self.core_script.encode()
        archive = self.home / "archive.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            entry = tarfile.TarInfo("sing-box-1.14.2-darwin-arm64/sing-box")
            entry.size = len(content)
            entry.mode = 0o700
            tar.addfile(entry, io.BytesIO(content))
        script = self.script.read_text()
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.script.write_text(script.replace(
            "925c5382eca8492b0150f868a6db20b18290a38700e621724b3703fd453e032d", digest))
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "core/sing-box").exists())

    def test_bad_archive_hash_does_not_install_or_activate(self):
        (self.bin / "sing-box").unlink()
        (self.home / "archive.tar.gz").write_bytes(b"not a trusted release")
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse((self.root / "core").exists())
        self.assertFalse(self.agent.exists())


if __name__ == "__main__":
    unittest.main()
