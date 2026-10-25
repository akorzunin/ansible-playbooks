#!/usr/bin/env python3
"""Run OpenTofu with Vault-backed authentication, encrypted state and pinned hosts."""
import base64
import fcntl
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
PASSWORD = ROOT.parent.parent / ".ansible_pass"
spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "prepare-bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def vault_bytes(path):
    return subprocess.run(
        ["ansible-vault", "view", "--vault-password-file", str(PASSWORD), str(path)],
        check=True, capture_output=True,
    ).stdout


def environment(command, args):
    env = dict(os.environ)
    token_path = ROOT / "cherry-token.vault"
    if not env.get("CHERRY_API_KEY") and token_path.is_file():
        token = vault_bytes(token_path).decode().strip()
        if not token or any(character.isspace() for character in token):
            raise ValueError("Invalid API token")
        env["CHERRY_API_KEY"] = token
    if env.get("TF_ENCRYPTION") or any(env.get(name) for name in ("TF_LOG", "TF_LOG_CORE", "TF_LOG_PROVIDER")):
        raise ValueError("Encryption overrides/debug logging are not permitted")
    offline = command in {"fmt", "validate", "test", "version", "-version", "--version", "-help", "--help"}
    offline |= command == "init" and "-backend=false" in args
    if offline:
        return env, None
    data = bootstrap.read_vault(ROOT / "secrets.vault.yaml", PASSWORD)["vpn_bootstrap"]
    if not isinstance(data["state_passphrase"], str) or len(data["state_passphrase"]) < 32:
        raise ValueError("Invalid encryption secret")
    bootstrap.fingerprint(data["ssh_host_key"]["public"])
    if not data["ssh_host_key"]["private"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----"):
        raise ValueError("Invalid private host key")
    # Set these from the shared source, not inherited controller-specific inputs.
    env["TF_VAR_state_encryption_passphrase"] = data["state_passphrase"]
    env["TF_VAR_ssh_host_key"] = json.dumps(data["ssh_host_key"])
    return env, data


def encrypted(path):
    data = json.loads(path.read_bytes())
    return bool(data.get("encryption_version") and data.get("encrypted_data")) and "resources" not in data


def archive_plaintext(path):
    if not path.exists() or encrypted(path):
        return
    content = path.read_bytes()
    target = ROOT / "private" / ("pre-encryption-" + path.name + ".vault")
    target.parent.mkdir(mode=0o700, exist_ok=True)
    if target.exists():
        if vault_bytes(target) != content:
            raise ValueError("An existing migration backup differs; refusing replacement")
        return
    subprocess.run(
        ["ansible-vault", "encrypt", "--vault-password-file", str(PASSWORD), "--output", str(target)],
        input=content, check=True, capture_output=True,
    )
    if not target.read_bytes().startswith(b"$ANSIBLE_VAULT;") or vault_bytes(target) != content:
        raise ValueError("Migration backup verification failed")


def migrate(executable, env):
    # This helper owns only the default local backend/workspace, not arbitrary
    # backend migrations. Refuse alternate state locations rather than guessing.
    if any(env.get(key) for key in ("TF_DATA_DIR", "TF_CLI_ARGS", "TF_CLI_ARGS_state")):
        raise ValueError("Migration requires the default local CLI/data paths")
    workspace_file = ROOT / ".terraform/environment"
    if env.get("TF_WORKSPACE", "default") != "default" or (
        workspace_file.exists() and workspace_file.read_text().strip() != "default"
    ):
        raise ValueError("Migration requires the default workspace")
    metadata_file = ROOT / ".terraform/terraform.tfstate"
    if metadata_file.exists():
        backend = json.loads(metadata_file.read_bytes()).get("backend") or {}
        if backend.get("type") not in (None, "local") or (backend.get("config") or {}).get("path") not in (None, "", "terraform.tfstate"):
            raise ValueError("Use a backend-specific migration for non-default state storage")
    state = ROOT / "terraform.tfstate"
    backup = ROOT / "terraform.tfstate.backup"
    pending = ROOT / "private/migration-original.tfstate"
    if pending.exists():
        raise ValueError("Inspect and recover the existing migration original before proceeding")
    if encrypted(state):
        subprocess.run([executable, "state", "list"], env=env, check=True)
        archive_plaintext(backup)
        if backup.exists() and not encrypted(backup):
            backup.unlink()
        print("State is already encrypted; strict encryption remains enabled.")
        return 0
    archive_plaintext(state)
    archive_plaintext(backup)
    original = state.read_bytes()
    if (ROOT / ".terraform.tfstate.lock.info").exists():
        raise ValueError("Resolve the existing migration/state lock before migrating")
    # Local-only migration: push the unchanged snapshot to an empty local backend.
    # Enforcement is NEVER disabled. The controller lock protects this rename
    # window; a locking remote backend needs its own migration, not this helper.
    os.replace(state, pending)
    try:
        result = subprocess.run([executable, "state", "push", "-"], input=original, env=env)
        if result.returncode:
            return result.returncode
        if not encrypted(state):
            raise ValueError("State migration did not produce ciphertext")
        subprocess.run([executable, "state", "list"], env=env, check=True)
        restored = json.loads(subprocess.run(
            [executable, "state", "pull"], env=env, check=True, capture_output=True,
        ).stdout)
        source = json.loads(original)
        if any(restored.get(key) != source.get(key) for key in ("lineage", "resources", "outputs")):
            raise ValueError("Migrated resources/outputs differ; original retained for recovery")
        pending.unlink()
    finally:
        if not state.exists() and pending.exists():
            os.replace(pending, state)
    if backup.exists() and not encrypted(backup):
        # The pre-existing backup was independently archived and verified above.
        archive_plaintext(backup)
        backup.unlink()
    print("State migrated and verified without cloud changes or a plaintext fallback. Retire old plans.")
    return 0


def private_write(path, content):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temporary:
        pending = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.flush()
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)


def inventory(executable, env, data, proxy_command=None):
    state = json.loads(subprocess.run([executable, "show", "-json"], env=env, check=True, capture_output=True).stdout)
    resources = state["values"]["root_module"]["resources"]
    server = next(resource["values"] for resource in resources if resource["address"] == "cherryservers_server.vpn")
    # Read the APPLIED cloud-init from authenticated encrypted state, not just
    # current variables: a pending host-key rotation must not repin the old VM.
    cloud = json.loads(base64.b64decode(server["user_data"]).decode().split("\n", 1)[1])
    public = cloud["ssh_keys"]["ed25519_public"].strip()
    if public.split()[:2] != data["ssh_host_key"]["public"].split()[:2]:
        raise ValueError("Applied host key differs from the prepared key; apply/reconcile first")
    addresses = [ip["address"] for ip in server["ip_addresses"] if ip["type"] == "primary-ip" and ip["address_family"] == 4]
    if len(addresses) != 1 or not ipaddress.IPv4Address(addresses[0]).is_global:
        raise ValueError("Expected one public primary IPv4")
    address = addresses[0]
    directory = ROOT / "private"
    directory.mkdir(mode=0o700, exist_ok=True)
    user = "root"
    inventory_path = directory / "inventory.yaml"
    try:
        old = json.loads(inventory_path.read_text())["all"]["children"]["vpn_test"]["hosts"]["cherry_vpn_test"]
        if old.get("cherry_server_id") == str(server["id"]):
            if old.get("ansible_user") == "vpnadmin":
                user = "vpnadmin"
            if proxy_command is None:
                proxy_command = next((arg.split("=", 1)[1] for arg in shlex.split(old["ansible_ssh_common_args"])
                                      if arg.startswith("ProxyCommand=")), None)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    host = {
        "ansible_host": address, "ansible_user": user, "cherry_server_id": str(server["id"]),
        "ansible_python_interpreter": "/usr/bin/python3",
        "ansible_ssh_private_key_file": str(directory / "ssh/admin"),
        "ansible_ssh_common_args": "-o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o UserKnownHostsFile=" + str(directory / "known_hosts"),
    }
    if proxy_command:
        host["ansible_ssh_common_args"] += " -o " + shlex.quote("ProxyCommand=" + proxy_command)
    private_write(directory / "known_hosts", f"{address},akorz-dyn1.duckdns.org {public}\n")
    private_write(inventory_path, json.dumps({"all": {"children": {"vpn_test": {"hosts": {"cherry_vpn_test": host}}}}}, indent=2) + "\n")
    print(f"Pinned applied server {server['id']} at {address}: {bootstrap.fingerprint(public)}")
    print("Private inventory and strict known_hosts written; no network scan was trusted.")
    return 0


def main(args):
    if not args:
        raise ValueError("An OpenTofu command is required")
    command = args[0]
    env, data = environment(command, args)
    if data is not None:
        # One local controller lock; use a locking remote backend before allowing
        # multiple controllers. Raw binary invocations must not bypass this lock.
        (ROOT / "private").mkdir(mode=0o700, exist_ok=True)
        lock = (ROOT / "private/controller.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.set_inheritable(lock.fileno(), True)
    executable = str(ROOT / ".tools/tofu") if (ROOT / ".tools/tofu").is_file() else shutil.which("tofu")
    if not executable:
        raise ValueError("Install OpenTofu first")
    if command == "migrate-state" and len(args) == 1:
        return migrate(executable, env)
    if command == "inventory":
        if len(args) == 1:
            return inventory(executable, env, data)
        if len(args) == 3 and args[1] == "--proxy-command":
            return inventory(executable, env, data, args[2])
        raise ValueError("Usage: inventory [--proxy-command command]")
    if command == "migrate-state":
        raise ValueError("migrate-state takes no arguments")
    os.execve(executable, [executable, *args], env)


if __name__ == "__main__":
    os.umask(0o077)
    os.chdir(ROOT)
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        print("OpenTofu wrapper failed. Check Vault/bootstrap inputs, encryption and local recovery files; no secret values were printed.", file=sys.stderr)
        raise SystemExit(1)
