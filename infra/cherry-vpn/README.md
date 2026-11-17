# Dynamic VPN nodes (Cherry Servers adapter)

`dyn1`, `dyn2`, … identify dynamically provisioned VPN exits, not their provider.
Each node has its own state, host identity, DNS record, inventory, monitoring label
and `dynN-*` client choices. Cherry is the current provisioning adapter; the
shared [`vpn_node` role](../../roles/vpn_node/README.md) is provider-independent.
The directory and API token keep their provider names deliberately.

See **[LIFECYCLE.md](LIFECYCLE.md)** for creation, deletion and migration.
This change does not alter the running dyn1 connection or publish profiles.
Historical measurements are in [VLESS-REVIEW.md](VLESS-REVIEW.md); they are not
live account status or a guarantee of Discord voice connectivity.

## Services and checks

- Key-only `vpnadmin` with verified sudo before disabling root/password SSH.
- Restricted forwarding SSH container (`dynN-ssh`, TCP/2222).
- Naïve over verified HTTPS (`dynN-naive`, TCP/443).
- VLESS/REALITY with Vision and XUDP (`dynN-vless`, TCP/8443).
- Optional derived `dynN-ssh-via-workstation` when the shared hop is present.
- No dynamic Hysteria or VLESS-over-Naïve choices. A supervised deployment stops
  an old `vpn-hysteria2` Compose project and removes its configuration. Reusable
  role support for other setups is unchanged.

Provisioning checks authenticated HTTPS and the exit IPv4, plus VLESS UDP relay
against two STUN servers, before registration and again after publication.
STUN is a UDP smoke test, not an end-to-end Discord voice or stability test.
No active workstation client is switched. Existing enrollment URLs/tokens remain
unchanged; clients must refresh profiles. Defaults are preserved except retired
Hysteria/chain defaults, which migrate to the node's direct VLESS choice.

Host/container monitoring uses `dynN` as the node label, with separate managed
inventory blocks. VPN protocol monitoring is maintained separately in
`github.com/akorzunin/vpn-monitor`.

## Provider inputs and budget

Run `install.sh` to link existing shared inputs from `~/Dropbox/ssh/cherry-vpn/`
(or `$DROPBOX_SSH_DIR/cherry-vpn/`):

- `cherry-token.vault`: Vault-encrypted API token, or set `CHERRY_API_KEY`.
- `terraform.tfvars`: region, approved plan and public administrator-key path.
- `external_vars.yml` at repository root: shared project ID, administrator/probe
  keys (`CHERRY_PROJECT_ID`, `CHERRY_VPN_SSH_KEYS`) and DuckDNS credentials.
- `.ansible_pass`: Vault password file. Never commit plaintext secrets.

The provider adapter permits the smallest B1/B2 shared x86 plans (1 CPU, 1 GB,
20 GB), Debian 13 and hourly billing. New allocations require available regional
stock and a single EUR hourly catalogue quote no greater than 0.015. Existing-node
no-op plans and deletion skip allocation checks; the lifecycle reviewer rejects
any VM creation with those checks disabled. This is a **per-node
compute ceiling**, not an aggregate budget or all-inclusive bill: multiple nodes
multiply cost, and taxes/IP/storage/account pricing may differ. Check the portal.
No automatic upgrade, replacement, expiry or failover is implemented.

```sh
python infra/cherry-vpn/catalogue.py
bash infra/cherry-vpn/tofu.sh init -backend=false
bash infra/cherry-vpn/tofu.sh validate
bash infra/cherry-vpn/tofu.sh test
```

## Encrypted state and controller handoff

The original dyn1 files remain at this directory's root. Other nodes live in
ignored `nodes/dynN/`, with configuration symlinks to this adapter. Do not copy
state between nodes or initialize a node whose state was lost.

OpenTofu state/plans enforce PBKDF2/AES-GCM encryption. Each node's
`secrets.vault.yaml` holds its bootstrap passphrase and pinned host identity.
The shared root Vault also holds VPN credentials; new nodes reuse those VPN
credentials but get independent state passphrases and host keys. Administrator
and restricted probe keys remain separate. Inventory pins come from **applied**
cloud-init in encrypted state, never an unauthenticated network scan.

Use one active controller at a time. Local locks do not provide distributed
locking; use a locking remote backend before enabling concurrent controllers.
After operations, wait for Dropbox sync before switching controllers.

```sh
bash infra/cherry-vpn/tofu.sh --node dyn2 backup-state
# On another controller, after install.sh and Dropbox sync:
mkdir -p -m 700 infra/cherry-vpn/nodes/dyn2
bash infra/cherry-vpn/tofu.sh --node dyn2 restore-state
ansible-playbook --vault-password-file .ansible_pass \
  infra/cherry-vpn/restore-keys.yaml -e dyn_node=dyn2
```

New-node backups include the encrypted state, encrypted bootstrap Vault and
nonsecret node/tfvars inputs under Dropbox `cherry-vpn/nodes/dynN/`. The project
ID is regenerated from `external_vars.yml`. Restore refuses conflicting local
files rather than overwriting them. dyn1 retains the original state-only
backup/restore behavior: its root Vault and shared inputs must also be restored.
Never share plaintext state, plans, private keys or generated client exports.

## Lower-level recovery

Use the supported lifecycle for normal operations. Lower-level commands do not
perform the full registration/monitoring/publication workflow:

```sh
bash infra/cherry-vpn/tofu.sh --node dyn2 inventory
# Optional controller transport, retaining strict destination host verification:
bash infra/cherry-vpn/tofu.sh --node dyn2 inventory \
  --proxy-command 'nc -X connect -x 127.0.0.1:12334 %h %p'
ansible-playbook -i hosts -i infra/cherry-vpn/nodes/dyn2/private/inventory.yaml \
  --vault-password-file .ansible_pass infra/cherry-vpn/deploy.yaml -e dyn_node=dyn2
```

For legacy plaintext dyn1 state only, `tofu.sh migrate-state` archives plaintext
into Vault and verifies encrypted migration without a plaintext fallback. Retain
recovery backups and inspect existing locks before retrying interrupted actions.

## Offline tests

```sh
python -m unittest discover -s infra/cherry-vpn -p 'test_*.py'
python -m unittest discover -s roles/vpn_node/tests -p 'test_*.py'
python -m unittest discover -s playbooks/sing-box-configs -p 'test_*.py'
uvx prek run --all-files
```
