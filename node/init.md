# Add a server

Run from the repository root:

```sh
ansible-galaxy collection install -r requirements.yml
ansible-playbook --vault-password-file=.ansible_pass \
  -i ./hosts -i ./monitoring.inventory.yml node/init_node.playbook.yaml
```

Enter the **new node name**, **IP/DNS address**, and **root password**. No inventory
entry or per-node services playbook is needed first. Supported images: official
Debian and Ubuntu with root SSH available. Custom SSH port: `-e node_port=2222`.
Do not use `--limit` or `--check`: this flow also updates the monitoring server.

## One-time controller setup

- Link the private YAML `hosts` and `external_vars.yml` files (`./install.sh`).
  Bootstrap preserves existing records, Vault text, and the `hosts` symlink.
- Copy `monitoring.inventory.yml.example` to the ignored `monitoring.inventory.yml`
  if not already present. Configure its scraper source CIDRs before deployment.
- Have `~/.ssh/id_ed25519` and its `.pub` file available. Load an encrypted private
  key into `ssh-agent` first. Override paths with `-e node_public_key_file=...`
  and, if needed, `-e node_private_key_file=...`.
- In `external_vars.yml`, optionally set `NODE_USER` (default `ansible`). Bootstrap
  reuses `monitoring_workstation_allowed_sources` from `monitoring.inventory.yml`,
  the same allowlist used by `nk1` and `nt1`. Override it with a non-empty YAML list
  in `NODE_MONITORING_ALLOWED_SOURCES` if needed. Prefer a stable VPN /32 rather
  than a dynamic ISP pool. Bootstrap only prompts if neither list is configured.
  Unrestricted `/0` sources are rejected. This is a Telegraf HTTP allowlist, not a
  network firewall.
- The existing workstation monitoring stack must be reachable via its inventory
  connection, with Docker permissions. Keep `MONITORING_TELEGRAM_BOT_TOKEN` and
  `MONITORING_TELEGRAM_CHAT_ID` configured in Vault-backed `external_vars.yml`, and
  `playbooks/ws-logs/.env` present (see the [monitoring guide](../playbooks/ws-logs/README.md)).
- Permit SSH from your controller and TCP 9273 from the scraper in your provider
  firewall. Bootstrap does not change provider/network firewall rules.

## What happens

1. Validate local inputs, keys, monitoring credentials, and inventory layout;
   wait up to 30 seconds for the server's SSH banner before starting bootstrap.
2. Connect as root; install Python/sudo if missing, create the administrator,
   install your public key, and configure passwordless sudo. No user password,
   fixed UID, or local `passlib` dependency is needed.
3. Verify a **fresh, public-key-only sudo connection** before disabling root SSH,
   password authentication, and keyboard-interactive authentication. Validate
   SSH configuration before reloading the service.
4. Set the hostname, upgrade apt packages, install/enable SSHGuard, install
   Docker Engine/Compose and the existing shared Docker networks.
5. Enable daily unattended security updates using the distribution's default
   allowed origins. **Automatic reboots are disabled**; report if one is needed.
6. Deploy Telegraf for host and Docker metrics, save a key-only connection in
   private `hosts`, and save monitoring membership/allowlist in
   `monitoring.inventory.yml`. Backups are made before inventory changes.
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
must work. Existing unmanaged inventory names are deliberately refused to avoid
silently replacing another host; choose a new name for a new machine.

Failed root bootstrap blocks node setup; failed node setup blocks monitoring
updates, including when SSH reports the host as unreachable. Completed changes
are not rolled back. If monitoring fails, the configured node and saved inventory remain usable; correct
connectivity/allowlist settings and retry. A failed initial key/sudo check leaves
root access unchanged. Keep provider-console access available during bootstrap.
Keep the monitoring overlay private and backed up: it is ignored by Git because
source CIDRs may reveal private infrastructure details.

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
persisted inventories (this updates the live workstation stack):

```sh
ansible-playbook --vault-password-file=.ansible_pass \
  -i ./hosts -i ./monitoring.inventory.yml playbooks/ws-logs/deploy.yml
```

Offline checks (no server connections):

```sh
python -m unittest discover -s node/tests -v
python -m unittest discover -s playbooks/ws-logs/tests -v
ansible-playbook -i localhost, --syntax-check node/init_node.playbook.yaml
```
