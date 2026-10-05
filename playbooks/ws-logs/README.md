# Inventory-managed monitoring

Ansible + Compose remain the deployment mechanism. Git owns Prometheus targets,
one shared node/container dashboard, data sources, the node-availability rule, and Telegram
notification routing. Grafana's database still stores users and other runtime state.

## Inventory

Always load both inventories:

```sh
-i ./hosts -i ./monitoring.inventory.yml
```

`hosts` remains your private Dropbox inventory. `monitoring.inventory.yml` is a
tracked overlay with **one entry per machine**, not both local and remote aliases.
It monitors `workstation`, `pi`, `nk1`, and `nt1`. `kr1`, `sw1`, and `pl1` are retired:
no targets and no exporter deployment, even if accidentally added to `monitored_nodes`.
Their private SSH records are not deleted.

`monitoring_address` overrides `ansible_host` when Prometheus needs a different
address (for example, a VPN address). `monitoring_node` is a stable human-readable
label. Workstation exporters use Compose DNS; remote exporter ports are inherited
from the same inventory variables used to deploy them.

Exporter ports (nk1/nt1 probed directly; Pi verified through Prometheus during deployment):

| Node | node-exporter | cAdvisor |
| --- | --- | --- |
| nk1 | 9100 | 3003 |
| nt1 | 901 | 900 |
| pi | 9100 | 3003 |

Exporters currently respond on public addresses. Restrict them to the workstation
or a private monitoring network with firewall/VPN rules; this playbook does not
change networking or expose additional ports.

## Secrets and environment

Keep real credentials in the existing `external_vars.yml`, preferably as `!vault`
strings. The tracked `external_vars.yml.example` lists the required names:

- `MONITORING_TELEGRAM_BOT_TOKEN`
- `MONITORING_TELEGRAM_CHAT_ID` (numeric string; group IDs are usually negative)
- `MONITORING_GRAFANA_ADMIN_USER` / `MONITORING_GRAFANA_ADMIN_PASSWORD`
  (**current** org-1 administrator credentials, needed only for UI cleanup)

Reuse your existing Telegram bot/chat. If the token is lost, obtain/reissue it with
BotFather. Start the bot or add it to the target group before testing notifications.
Grafana's database backup preserves the old contact point, but a redacted contact
point export alone cannot recover its bot token.

Copy `.env.example` to `playbooks/ws-logs/.env` and configure it, or pass
`-e monitoring_env_file=/absolute/path/to/your/existing/.env`. Preserve existing
settings. `GF_SECURITY_ADMIN_*` initializes a new database; it does not reset an
existing administrator password.

Secret files on the server are mode `0600`; secret tasks suppress Ansible output.
The rendered contact point still contains the bot token, so treat server files and
backups as sensitive. Nothing modifies the private inventory or secrets automatically.

## First migration: back up, replace, provision

Run from the repository root. The server defaults to `local_workstation`, not every
host in the private inventory. No infrastructure is changed until you run these commands.

```sh
ansible-galaxy collection install -r requirements.yml

ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  playbooks/ws-logs/deploy.yml --syntax-check

ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  --vault-password-file=.ansible_pass \
  playbooks/ws-logs/deploy.yml -e monitoring_replace_ui=true
```

The migration:

1. Validates inventory, Telegram settings, the local `.env`, and cleanup credentials.
2. Stops Grafana briefly and takes a consistent, root-readable archive of
   `grafana_data`, `.env`, and the old stack configuration under
   `~/deploy/ws-logs/backups/grafana-<timestamp>.tar.gz`. Grafana is restarted even
   if the archive fails. Requires sudo for root-owned data.
3. Verifies org 1, then deletes **all old dashboards and Grafana-managed alert
   rules** except the new managed UIDs. Refuses deletion if a legacy dashboard is
   owned by another provisioning source. It does not delete users, folders, old
   data sources, old contact points, or Prometheus/Loki-managed rules.
4. Installs the shared **Monitoring / Nodes & Containers** dashboard, data
   sources, availability rule, and Telegram contact point.
5. Validates Prometheus configuration with `promtool`, reconciles Compose changes,
   restarts services to reload changed configuration, and waits for Grafana readiness.
   Unchanged containers are not force-recreated: Loki currently has container-local
   storage, which survives restarts but not recreation. Persistent Loki storage is
   still needed before changing its image or Compose configuration.

The provisioning file owns the **entire org-1 notification-policy tree** and
replaces the old policy with Telegram routing, including NoData/Error alerts.
Old contact points may remain unused. This policy change also happens on an
ordinary deployment; the first managed deployment backs up an existing Grafana
installation even without UI cleanup.

Copy the archive off the workstation. If cleanup/deployment fails midway, the
archive is the recovery point; there is no automatic rollback. The archive covers
Grafana and configuration, **not Prometheus history or Loki log data**.

Only use `monitoring_replace_ui=true` for the intentional migration. Ordinary
runs preserve other UI-created dashboards/alerts:

```sh
ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  --vault-password-file=.ansible_pass playbooks/ws-logs/deploy.yml
```

Override `remote_install_path` if the existing stack lives elsewhere. Don't run a
second Grafana against an empty directory and mistake it for a migration.

## Alerts

One multidimensional rule checks:

```promql
up{job="nodeexporter", availability_alert="true"}
```

Each series below 1 for two minutes creates an alert for its `node`. Currently only
`nt1` and `nk1` opt in. An unreachable exporter/network also triggers it; this is a
reachability check, not proof the machine is powered off. cAdvisor failure alone
does not page you. Missing all query data and evaluation failures generate Grafana
NoData/Error alerts, routed to Telegram too.

After deployment, test **Monitoring Telegram** in Grafana's contact-point UI and
check both targets in Prometheus. No test notification is sent by Ansible. Add
richer alerts later in `grafana/provisioning/alerting/rules.yml`; alerts must preserve
node labels and cannot use dashboard variables.

## Adding, disabling, and retiring nodes

1. Add SSH details to the private `hosts` inventory.
2. Add the same host to `monitored_nodes` in `monitoring.inventory.yml`.
3. Override exporter ports/address as needed; set `monitoring_availability_alert:
   true` if it should page you.
4. For a new Docker host, deploy exporters, then redeploy the monitoring server:

```sh
ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  --vault-password-file=.ansible_pass playbooks/ws-logs/deploy-clients.yml -l newnode

ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  --vault-password-file=.ansible_pass playbooks/ws-logs/deploy.yml
```

The client playbook requires Docker and sudo; it creates the existing role's
`monitoring` network. The server's exporters stay in the server Compose project.
**Do not blindly redeploy existing Pi/nk1 exporters:** older standalone Compose
projects use the same container names. Retire those old exporter projects first,
then use `deploy-clients.yml` with the inventory ports. nt1 already uses this role.

Dashboards discover new nodes automatically. Use `monitoring_enabled: false` to
stop scraping a host, or move it to `retired_nodes`. Redeploy the server afterward.
This intentionally stops availability alerts for the removed node; it does not
uninstall its exporters or other services.

Changing the old per-node jobs to shared jobs creates new label sets/time series.
Old metrics keep their old labels until retention expires; the new dashboards
won't show pre-migration history. Stable `node` labels survive later address changes.

## Editing and validating

Edit the combined dashboard in `grafana/dashboards/nodes.json`, not the old per-node
JSONC template. It keeps the `monitoring-nodes` UID so existing node dashboard links
continue to work. One node selector filters both exporter and container metrics.
A shared crosshair marks the hovered timestamp across charts. Node panels include
filesystem utilization (%), available disk space (automatically scaled to GiB/TiB),
1/5/15-minute load averages, and logical CPU count. Available space excludes blocks
reserved for root. Container charts are full-width with right-side table legends
sorted by latest non-null value, highest first. Click the value-column header to
change sorting; legend values reflect the end of the selected time range, not the
hovered timestamp.

Provisioned dashboards are read-only; use a temporary UI copy for experiments and
export changes back to Git. Removed Git dashboard files are deleted from the managed
server directory on deployment. An ordinary deployment removes the old provisioned
Containers dashboard; no `monitoring_replace_ui=true` is needed for this merge.

Local checks (Python uses Ansible's existing Jinja2/PyYAML dependencies):

```sh
python3 -m unittest discover -s playbooks/ws-logs/tests -v
ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  playbooks/ws-logs/deploy-clients.yml --syntax-check
```

## Restoring the Grafana backup

On the workstation, in the existing stack directory, stop Grafana, move the failed
state aside, and restore the archive. Keep the backup directory itself untouched:

```sh
cd ~/deploy/ws-logs
backup="$PWD/backups/grafana-<timestamp>.tar.gz"
docker compose stop grafana
sudo mv grafana_data "grafana_data.failed-$(date +%s)"
# If present, move new provisioning aside so it cannot overwrite restored state.
if [ -d grafana ]; then mv grafana "grafana.failed-$(date +%s)"; fi
sudo tar -xzf "$backup" -C "$PWD"
docker compose up -d --force-recreate
```

An off-server `.tar.gz.vault` backup must first be decrypted on the controller
with the same Vault password file, then transferred securely to the workstation:

```sh
ansible-vault decrypt --vault-password-file=.ansible_pass \
  --output=/private/directory/grafana-backup.tar.gz /path/to/grafana-backup.tar.gz.vault
```

Treat the decrypted archive as sensitive and remove it after restoration.

The restored Compose/configuration comes from before migration. Keep the failed
state until you have verified the restored dashboards, alerts, and notification
routing. Restoring a later managed backup also restores its provisioning files.
