# Add a server

Run from the repository root:

```sh
ansible-galaxy collection install -r requirements.yml
ansible-playbook --vault-password-file=.ansible_pass \
  -i ./hosts node/init_node.playbook.yaml
```

Enter the **new node name**, **IP/DNS address**, and **root password**. No inventory
entry or per-node services playbook is needed first. Supported images: official
Debian (including Debian 13 / trixie) and Ubuntu with root SSH available.
Custom SSH port: `-e node_port=2222`.
Do not use `--limit` or `--check`: this flow also updates the monitoring server.
Run only one bootstrap at a time against the same inventory files.

## One-time controller setup

- Link the private YAML `hosts` and `external_vars.yml` files (`./install.sh`).
  Bootstrap preserves existing records, Vault text, and the `hosts` symlink.
- Configure monitoring groups and scraper source CIDRs in `hosts`, using
  `hosts.example.yml` as a reference. Existing controllers can merge the old overlay
  once with `python3 playbooks/ws-logs/migrate-inventory.py` (see the monitoring guide).
  Existing block-style YAML inventories also work: no particular comments,
  indentation, or group ordering are required. Do not add the new node manually.
- Use Ansible Core **2.19+** and have OpenSSH's `ssh-agent` available. The repository
  enables Ansible's per-run managed agent in `ansible.cfg`. Supply Vault credentials
  with `--vault-password-file` or `--vault-id`; they also encrypt each new node's
  dedicated Ed25519 key. New nodes do not need a personal controller SSH key.
  Migrating older key-file nodes without root access requires their existing key
  once (`-e node_private_key_file=...` overrides the default `~/.ssh/id_ed25519`).
  For a passphrase-protected legacy key, load it into your existing agent and
  select that socket with `ANSIBLE_SSH_AGENT=$SSH_AUTH_SOCK` for the migration;
  unlike the default managed agent, that existing agent is not cleaned up by Ansible.
- In `external_vars.yml`, optionally set `NODE_USER` (default `ansible`). Bootstrap
  reuses `monitoring_workstation_allowed_sources` from `hosts`,
  the same allowlist used by `nk1` and other active VPS nodes. Override it with a
  non-empty YAML list in `NODE_MONITORING_ALLOWED_SOURCES` if needed. Prefer a stable VPN /32 rather
  than a dynamic ISP pool. Bootstrap only prompts if neither list is configured.
  Unrestricted `/0` sources are rejected. This is a Telegraf HTTP allowlist, not a
  network firewall.
- The existing workstation monitoring stack must be reachable via its inventory
  connection, with Docker permissions. Keep `MONITORING_TELEGRAM_BOT_TOKEN` and
  `MONITORING_TELEGRAM_CHAT_ID`, plus `MONITORING_GRAFANA_ADMIN_USER` and
  `MONITORING_GRAFANA_ADMIN_PASSWORD`, and Gmail fallback credentials `GF_SMTP_USER` /
  `GF_SMTP_PASSWORD`, configured in Vault-backed `external_vars.yml`.
  The remote Grafana environment is rendered from a tracked template; no local
  `.env` is needed (see the [monitoring guide](../playbooks/ws-logs/README.md)).
- Permit SSH from your controller and TCP 9273 from the scraper in your provider
  firewall. Bootstrap does not change provider/network firewall rules.

## What happens

1. Validate local inputs, Vault/monitoring credentials, and inventory layout;
   generate or reuse the node's dedicated Ed25519 key. Wait up to 30 seconds for
   the SSH banner, then save the key as `ansible_private_key: !vault |` in private
   `hosts` **before changing remote access**, so a failed run retains its recovery
   identity. Neither the personal key nor a plaintext node private-key file is saved.
2. Connect as root; install Python/sudo if missing, create the administrator,
   install the dedicated public key, and configure passwordless sudo. Older
   key-file nodes can instead install it using their existing administrator key;
   that migration remains resumable until the dedicated key passes verification.
   Existing authorized keys are retained. No user password, fixed UID, or local
   `passlib` dependency is needed.
3. Verify a **fresh, public-key-only sudo connection** before disabling root SSH,
   password authentication, and keyboard-interactive authentication. Reuse SSH
   connections for normal setup tasks to avoid connection churn, with three
   bounded SSH reconnect retries for administrator connections. Validate SSH
   configuration before reloading the service, then verify fresh key-only sudo
   again without reusing a connection.
4. Set the hostname, upgrade apt packages, install/enable SSHGuard and AppArmor,
   verify AppArmor is active in the running kernel, then install Docker
   Engine/Compose and the existing shared Docker networks. AppArmor confines
   applications with loaded profiles, including Docker's default container
   profile; it does not automatically confine every service.
5. Enable daily apt timers and unattended updates with an explicit security-only
   policy: Debian's release security repository, or Ubuntu security and enabled
   Ubuntu Pro ESM security repositories. This excludes routine release updates
   and third-party repositories (including Docker). **Automatic reboots are
   disabled**; report whether `/var/run/reboot-required` exists. Debian packages
   do not always create this marker: its absence does not guarantee no reboot
   is needed. Plan maintenance reboots after kernel/security updates.
6. Deploy Telegraf for host and Docker metrics, then save monitoring
   membership/allowlist in the same private `hosts`. Managed top-level blocks extend the existing
   `monitored_nodes` group without rewriting unrelated inventory text. Backups
   are made before inventory changes; reruns update the same managed blocks.
7. Redeploy the existing monitoring stack, including shared dashboards, alert
   rules and Telegram routing, without opting into destructive UI migration.
   Wait until Prometheus sees the new node's host and container metrics.

New nodes opt into availability alerts and the existing disk-space alert.
Dashboards discover them automatically. This flow does not test Telegram message
receipt, install application workloads, or automatically reboot the server.
The repository currently disables SSH host-key checking globally; independently
verify the server fingerprint before supplying its root password.

## Later deployments and retries

```sh
ansible new1 -i ./hosts -m ping --vault-password-file=.ansible_pass
ansible-playbook -i ./hosts -l new1 playbooks/your-app/deploy.yaml \
  --vault-password-file=.ansible_pass
```

To rerun bootstrap after root SSH has been disabled, enter the same node name and
address, and **leave the root password empty**. The existing administrator key
must work; it is decrypted from `hosts` into the managed SSH agent. Existing
unmanaged inventory names are deliberately refused to avoid
silently replacing another host; choose a new name for a new machine.

Failed root bootstrap blocks node setup; failed node setup blocks monitoring
updates, including when SSH reports the host as unreachable. The encrypted SSH
record is saved early for recovery, but monitoring membership is saved only after
successful node setup. Completed changes are not rolled back. If monitoring fails, the configured node and saved inventory remain usable; correct
connectivity/allowlist settings and retry. A failed initial key/sudo check leaves
root access unchanged. Keep provider-console access available during bootstrap.
If the image disables AppArmor in the kernel, bootstrap stops before installing
Docker. Enable AppArmor in the image's kernel boot configuration (or use a
supported kernel), reboot manually, and retry. Bootstrap does not change the
bootloader.
Keep `hosts` private and backed up: it contains SSH identities and monitoring
source CIDRs, and is already synced through Dropbox.

### Connect from another machine

Sync the private `hosts` file and securely transfer the Vault password separately.
Install Ansible Core 2.19+, OpenSSH, and the updated dotfiles selector. With this
repository's `ansible.cfg`, normal Ansible commands load the inventory key into
an automatically cleaned-up SSH agent. Outside this repository, set
`ANSIBLE_SSH_AGENT=auto` (or configure `[connection] ssh_agent=auto`).

```sh
ssh-sel.nu ./hosts --host ge2 --vault-password-file .ansible_pass
```

The selector automatically finds `.ansible_pass` beside the supplied inventory
if no flag is given; standard Ansible Vault configuration also works. It uses a
separate temporary agent and only a temporary **public** identity file, cleaning
both up when SSH exits. `--printcmd` copies a selector invocation, not an unusable
raw SSH command referencing an ephemeral key. No manual SSH key installation is
needed after bootstrap/migration succeeds. Anyone with both inventory and Vault
credentials can impersonate its administrators: protect them separately.

### SSH banner timeout

A timeout during banner exchange occurs before password authentication. Verify
SSH directly from the same controller:

```sh
ssh -vv -o ConnectTimeout=30 root@SERVER_IP
```

Check the provider's console, server power/IP, SSH service/port, and firewall
access from your controller. For a custom port, use `ssh -p PORT` and bootstrap
with `-e node_port=PORT`. Do not leave the root password empty on retry unless
administrator creation actually succeeded.

Older bootstrap runs could update Prometheus even after the new server was
unreachable. To remove an unsaved failed target, redeploy monitoring from the
persisted inventory (this updates the live workstation stack):

```sh
ansible-playbook --vault-password-file=.ansible_pass \
  -i ./hosts playbooks/ws-logs/deploy.yml
```

### Connection reset during SSH key exchange

`kex_exchange_identification: ... Connection reset by peer` happens before
user authentication or remote module execution. It can be caused by SSH
connection limits, source penalties, a firewall, or provider/network issues;
the client error alone does not identify which. Bootstrap reuses SSH connections
for normal tasks, but cannot repair an active server/provider block.

If administrator creation already succeeded, check access with
`ssh-sel.nu ./hosts --host ge2 --vault-password-file .ansible_pass`, then run
`sudo -n true` in that session. For an older, not-yet-migrated node, use its
existing controller key instead.

Once that works, rerun bootstrap with the same node name/address and leave the
root password empty. The dedicated encrypted identity is retained even when a
run fails before completing node setup.
If SSH still resets, inspect `journalctl -u ssh.service -u sshguard.service
--since '-10 minutes'` and `sshd -T | grep -Ei 'maxstartups|persource'` through the
provider console, plus provider firewall logs. Do not disable SSH protection
without identifying the cause. Monitoring remains gated on successful setup.

Offline checks (no server connections):

```sh
python -m unittest discover -s node/tests -v
python -m unittest discover -s playbooks/ws-logs/tests -v
ansible-playbook -i localhost, --syntax-check node/init_node.playbook.yaml
```
