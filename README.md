# My collection of ansible playbooks

## Add a server

See [the automated node bootstrap](node/init.md). Run once, enter the node name,
address and root password; it sets up key-only sudo access, Docker, SSHGuard,
security updates and the existing monitoring stack. Each node gets a dedicated
Vault-encrypted SSH key in private `hosts`, usable from another trusted controller
with the inventory and Vault password (Ansible Core 2.19+ and OpenSSH required).
The updated dotfiles `ssh-sel.nu` also supports these portable identities.

```sh
ansible-playbook --vault-password-file=.ansible_pass \
  -i ./hosts node/init_node.playbook.yaml
```

## Monitoring as code

See [the monitoring migration and deployment guide](playbooks/ws-logs/README.md).
Monitoring membership and scraper allowlists live alongside SSH settings in the
private `hosts` inventory; `hosts.example.yml` shows the monitoring sections.
Grafana's public environment defaults are tracked in `playbooks/ws-logs/grafana.env.j2`;
credentials come from the existing `external_vars.yml`. No separate monitoring
inventory or controller-local `.env` is required.

## Workstation proxy

[sing-box with `aurora-vless`](playbooks/sing-box/README.md) replaces the blocked
NT1/V2RayA proxy, preserving port `20171` for existing app containers and clients.

## Budget VPN experiment

See [the Cherry Servers/OpenTofu trial guide](infra/cherry-vpn/README.md) for
credential setup, price guardrails, a disposable SSH proxy and regional probes.
The Cherry VM `dyn1` was destroyed on 2026-11-01. Its DNS, shared SSH inventory
entry, monitoring membership and published VPN connections were removed.
The Cherry project has no servers, IPs or storage; encrypted state and backups
are retained. Do not apply the provisioning configuration unless creating a new
VM is explicitly intended.
VPN services now run on the existing ge2 node through the reusable
[`vpn_node` role](roles/vpn_node/README.md). All platforms default to
`ge2-vless-via-naive`; ge2 SSH, Naïve, direct VLESS, Hysteria 2 and
SSH-via-workstation are also selectable, with Aurora retained. Private URLs/tokens
are unchanged; refresh enrolled clients. The dyn1 SSH hop to nt1 is no longer
available. Active local clients and the workstation Docker proxy were not changed.
See the [current status](infra/cherry-vpn/README.md#current-status)
and [controller handoff instructions](infra/cherry-vpn/README.md#dropbox-inputs-and-switching-controllers).
Further provisioning requires a fresh reviewed plan and explicit approval.

## Setup

**If upgrading an existing controller**, consolidate its old monitoring overlay
into shared `hosts` once (uses PyYAML from your Ansible installation):

    python3 playbooks/ws-logs/migrate-inventory.py

This preserves SSH records, Vault ciphertext and monitoring settings, keeps a
mode-0600 backup beside the shared inventory, and renames legacy monitoring block
markers so bootstrap cannot overwrite SSH identities. Overlapping top-level YAML
groups require a manual merge; the script refuses to drop settings. Verify the
result, archive the old `monitoring.inventory.yml`, and use only `-i ./hosts`.
The old `playbooks/ws-logs/.env` is no longer read: Grafana credentials are reused
from `MONITORING_GRAFANA_ADMIN_USER` / `MONITORING_GRAFANA_ADMIN_PASSWORD` in
`external_vars.yml`. Keep any customized non-secret defaults in the tracked
template instead.

**For existing local private service inputs**, migrate them into Dropbox once:

    ./install.sh --migrate

This moves local input files into Dropbox and replaces them with symlinks, so
subsequent changes are synced too. It checks all inputs first, refuses conflicting
shared copies, and only adopts an existing shared copy when byte-identical. It
never overwrites different files or replaces different/broken symlinks. Newly
migrated files are mode 0600 and new directories are mode 0700. Environment files
contain plaintext credentials: use only your trusted private Dropbox account.

**On another controller**, wait for Dropbox to finish syncing, then link the inputs:

    ./install.sh

The script checks `~/Dropbox/ssh` and the Termux path
`~/storage/shared/Dropbox/ssh`. Set `DROPBOX_SSH_DIR` to use another path (also
supported with `--migrate`). Default installation never moves existing local
files; it tells you to migrate or reconcile them instead.

| Repository input | Path relative to Dropbox `ssh/` |
| --- | --- |
| `hosts`, `external_vars.yml` | Same names (required) |
| `playbooks/3proxy/users.env` | `playbooks/3proxy/users.env` |
| `playbooks/duckdns-ui/.env` | `playbooks/duckdns-ui/.env` |
| `playbooks/firefly/.env`, `.db.env`, `.importer.env` | Same paths under `playbooks/firefly/` |
| `playbooks/wake-on-lan/computers.txt` | `playbooks/wake-on-lan/computers.txt` |
| `infra/cherry-vpn/cherry-token.vault`, `terraform.tfvars` | `cherry-vpn/cherry-token.vault`, `cherry-vpn/terraform.tfvars` |

Legacy service inputs are optional; missing ones are reported, not generated from
examples. Recover absent legacy inputs from your existing deployment/backups if
you use those services; the installer cannot reconstruct their credentials.
Node bootstrap and monitoring need only the shared `hosts`, `external_vars.yml`
and separately supplied Vault password.

When the Dropbox `cherry-vpn/` directory exists, both Cherry inputs must be present;
without that directory, Ansible-only setup still works. Migration can also create
it from existing local Cherry inputs. Tracked Vault ciphertext comes with the Git
checkout. Generated VPN profiles/keys, provider caches and plans remain local and
can be regenerated; none are copied by the installer. Use one active controller
at a time and wait for sync before switching.

For OpenTofu, also follow the [controller handoff checklist](infra/cherry-vpn/README.md#dropbox-inputs-and-switching-controllers):
install OpenTofu, regenerate local SSH keys/project inputs, then run
`bash infra/cherry-vpn/tofu.sh restore-state` to copy the synced encrypted Dropbox
snapshot locally. Run `bash infra/cherry-vpn/tofu.sh backup-state` after operations
on the old machine and wait for sync before switching. Use only one machine at a
time. The installer itself does not provision infrastructure or copy state.

Securely transfer the existing Vault password to `.ansible_pass` on each trusted
controller (plaintext password file, not a Vault-encrypted file). Keep it out of
Dropbox and Git, separate from the encrypted secrets:

    chmod 600 .ansible_pass

Check connection to all hosts

    ansible all -i ./hosts -m ping --vault-password-file=.ansible_pass

## Create new secret

    ansible-vault encrypt_string --vault-password-file .ansible_pass "amogus"

    caddy hash-password --algo=argon2 --plaintext=amogus

## Run playbook

    ansible-playbook --vault-password-file=.ansible_pass ./playbooks/playbook_name.yaml -i ./hosts -l host_name

Run playbook locally

    ```sh
    ansible-playbook --vault-password-file=.ansible_pass ./playbooks/playbook_name.yaml -i localhost, -c local
    ```

The local pre-commit hook lints only staged YAML files. CI runs the hooks against
all tracked files. Changed-file linting can miss issues caused by shared role or
configuration changes; use the full-repo check below when needed.

Ansible-lint runs offline, so install collections first:

```sh
python -m unittest discover -s tests -p 'test_*.py'
ansible-galaxy collection install -r requirements.yml
```

Run the ansible-lint hook against all tracked YAML files locally:

```sh
uvx prek run ansible-lint --all-files
```

Or run all hooks against the full repo, as CI does:

```sh
uvx prek run --all-files
```

The isolated hook uses collections in `~/.ansible/collections`, not the system
Python installation. If Galaxy skips a collection because it is installed only
system-wide, rerun the install command with `--force` to install a user-local copy.
