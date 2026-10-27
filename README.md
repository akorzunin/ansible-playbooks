# My collection of ansible playbooks

## Add a server

See [the automated node bootstrap](node/init.md). Run once, enter the node name,
address and root password; it sets up key-only sudo access, Docker, SSHGuard,
security updates and the existing monitoring stack, then saves inventory for later use.

```sh
ansible-playbook --vault-password-file=.ansible_pass \
  -i ./hosts -i ./monitoring.inventory.yml node/init_node.playbook.yaml
```

## Monitoring as code

See [the monitoring migration and deployment guide](playbooks/ws-logs/README.md).
Copy `monitoring.inventory.yml.example` to the ignored `monitoring.inventory.yml`
and configure your scraper source CIDRs. Load it alongside the private `hosts`
inventory to generate scrape targets, provision shared dashboards/alerts, and
configure Telegram routing.

## Budget VPN experiment

See [the Cherry Servers/OpenTofu trial guide](infra/cherry-vpn/README.md) for
credential setup, price guardrails, a disposable SSH proxy and regional probes.
One Debian 13 Cherry VM is running at `akorz-dyn1.duckdns.org`, with pre-pinned
SSH identity and encrypted OpenTofu state/plans. No password bootstrap is needed.
The [`vpn_node` role](roles/vpn_node/README.md) configures
non-root administration, unattended security updates, native SSH forwarding and
Dockerized Naïve/VLESS, with private Linux test and profile-publisher outputs.
The Amsterdam node passes direct Linux checks for all three protocols. Its
connections are published alongside nt1 at the existing private profile URLs;
nt1 defaults and this workstation's non-enrolled active configuration are unchanged.
See the [current status](infra/cherry-vpn/README.md#current-status)
and [controller handoff instructions](infra/cherry-vpn/README.md#dropbox-inputs-and-switching-controllers).
Further provisioning requires a fresh reviewed plan and explicit approval.

## Setup

Link private inputs from Dropbox (existing files are never overwritten):

    ./install.sh

The script checks `~/Dropbox/ssh` and the Termux path
`~/storage/shared/Dropbox/ssh`. Set `DROPBOX_SSH_DIR` to use another path.
It links `hosts` and `external_vars.yml` into the repository root. When the
Dropbox `cherry-vpn/` directory exists, it also links `cherry-token.vault` and
`terraform.tfvars` from there into `infra/cherry-vpn/`. Both Cherry files must be
present in that case; without that directory, Ansible-only setup still works.

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
