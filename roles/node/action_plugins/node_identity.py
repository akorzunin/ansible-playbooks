"""Create/reuse a node's Vault-backed identity without plaintext key files."""

from pathlib import Path

from ansible.plugins.action import ActionBase
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import yaml


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        result['_ansible_no_log'] = True
        try:
            args = self._task.args
            # BaseLoader preserves ciphertext and accepts unrelated !vault records.
            inventory = yaml.load(Path(args['inventory_file']).read_text(), Loader=yaml.BaseLoader)
            record = (inventory.get('bootstrap_' + args['node'], {}).get('hosts', {}).get(args['node']) or {})
            # Use the active --vault-password-file/--vault-id secrets, not a second password configuration.
            vault = self._loader._vault
            if not vault.secrets:
                raise ValueError('Supply Vault credentials to protect the node identity')
            ciphertext = record.get('ansible_private_key')
            if ciphertext:
                if not ciphertext.startswith('$ANSIBLE_VAULT;'):
                    raise ValueError('The stored node identity must be Vault encrypted')
                private = vault.decrypt(ciphertext)
                key = serialization.load_ssh_private_key(private, password=None)
            else:
                key = Ed25519PrivateKey.generate()
                private = key.private_bytes(serialization.Encoding.PEM,
                                            serialization.PrivateFormat.OpenSSH,
                                            serialization.NoEncryption())
                ciphertext = vault.encrypt(private).decode()
            legacy = record.get('node_bootstrap_legacy_key_file', '') if args['use_legacy_access'] else ''
            if not record.get('ansible_private_key') and args['use_legacy_access']:
                legacy = record.get('ansible_ssh_private_key_file') or args['legacy_key_file']
            result.update(
                changed=False,
                private_key=private.decode(),
                public_key=key.public_key().public_bytes(
                    serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode(),
                vaulted_key=ciphertext.strip(),
                legacy_key_file=legacy,
            )
        except Exception:
            # Parser/crypto exceptions can include input. Never echo them or key material.
            result.update(failed=True, msg='Cannot prepare node identity; check the YAML inventory and Vault credentials. Existing identities were not replaced.')
        return result
