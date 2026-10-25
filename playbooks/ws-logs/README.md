# Inventory-managed monitoring

Ansible + Compose remain the deployment mechanism. Git owns Prometheus targets,
shared node/container and NVIDIA GPU dashboards, data sources, the node-availability
rule, and Telegram notification routing. Grafana's database still stores users and other runtime state.

## Inventory

Always load both inventories:

```sh
-i ./hosts -i ./monitoring.inventory.yml
```

`hosts` remains your private Dropbox inventory. `monitoring.inventory.yml` is an
ignored private overlay with **one entry per machine**, not both local and remote aliases.
For a new setup, copy `monitoring.inventory.yml.example` to that path and replace
the documentation-only scraper CIDR with your actual egress IP or VPN /32. Keep
an existing overlay unchanged and back it up privately.
It monitors `workstation`, `pi`, `nk1`, and `nt1`. `kr1`, `sw1`, and `pl1` are retired:
no targets and no exporter deployment, even if accidentally added to `monitored_nodes`.
Their private SSH records are not deleted.

`monitoring_address` overrides `ansible_host` when Prometheus needs a different
address (for example, a VPN address). `monitoring_node` is a stable human-readable
label. All four nodes use Telegraf. The workstation uses Compose DNS
(`telegraf:9273`); remote agents publish port 9273. `remote_pi` uses the public
hostname for SSH but `monitoring_address: 192.168.1.58` for LAN scrapes from the
workstation, and publishes metrics only on that LAN address.

Remote agents require `monitoring_telegraf_allowed_sources`. The Pi allows the
workstation's LAN address; nk1/nt1 share the privately configured workstation
source allowlist. Prefer a stable VPN /32: allowing a dynamic ISP pool also lets
other subscribers in that pool read metrics. Loopback and local Docker bridge
sources are also allowed. Requests from other public sources receive HTTP 403.
**Future ISP assignments outside the configured sources require updating
`monitoring_workstation_allowed_sources` in `monitoring.inventory.yml` and
redeploying those clients.** nk1/nt1 share that list, and bootstrap uses it by
default for new nodes (saving a per-node copy). Update saved copies too when the
source changes. Prefer a stable VPN
source for host-only access. No firewall rules are modified. The workstation
agent has no published host port; its endpoint stays inside the Compose network.

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

Run from the repository root. The server defaults to `remote_workstation`, not every
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
4. Installs the shared **Monitoring / Nodes & Containers** and **Monitoring /
   NVIDIA GPUs** dashboards, data sources, availability rule, and Telegram contact point.
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

## Telegraf collectors

All monitored nodes use Telegraf 1.40.2. Workstation, nk1, and nt1 use the Alpine
image; the 32-bit ARMv7 Pi uses `telegraf:1.40.2` (Debian), because the Alpine tag
does not publish ARMv7 images. One template,
`roles/monitoring_client/templates/telegraf.conf.j2`, supplies every agent's
configuration with its stable node hostname and optional endpoint source allowlist.
The workstation agent lives in the existing stack; remote agents live in the
separate `/srv/monitoring/telegraf` Compose project.

It collects host CPU, available memory, load/uptime, filesystem capacity, disk I/O,
and network counters, plus running Docker containers' CPU, memory, network, and
block-I/O metrics. Read-only host mounts supply real host data. `/proc/1/net` is
mounted over `/hostproc/net` so network counters come from the host's namespace,
not the agent's bridge interface. No host networking or privileged mode is needed.

**Security:** Telegraf runs as root and can read the host filesystem and access
the Docker socket. A `:ro` socket bind does **not** make the Docker API read-only;
that API is root-equivalent access. The image's privilege-dropping entrypoint is
bypassed intentionally. Do not allow untrusted changes to its configuration.

Deploy remote agents first with `deploy-clients.yml` (serial, one host at a time).
It never removes legacy exporters or uses the generic role's force-recreate/orphan
cleanup. Deploy the server with `deploy.yml` to switch Prometheus to the inventory's
Telegraf endpoints. After checking every dashboard query, run `retire-exporters.yml`:
it checks a successful scrape and 13 required metric families **for each node from
the actual Prometheus server**, verifies the old exporter images/Compose labels,
and saves root-readable rollback metadata and Compose files under
`/srv/monitoring/telegraf/legacy-*` before removing only the two exporter containers.
Existing legacy project directories, networks, images, and volumes are retained.
The server's previous configuration is archived under `~/deploy/ws-logs/backups/`.
A failed verification stops retirement; no stack-wide `down` or global orphan
cleanup is used.

**Monitoring / Nodes & Containers** supports both collectors. Queries prefer
Telegraf per node/filesystem/container and fall back to exporter metrics, retaining
old history until Prometheus retention expires. Native metric names are not
rewritten into fake `node_*` or `container_*` metrics. The separate test Telegraf
dashboard has been removed; use **Nodes & Containers** and **NVIDIA GPUs**.

Container CPU is still expressed in cores in the shared dashboard (Docker CPU
percentage divided by 100). Container memory uses `docker_container_mem_usage`
directly: Telegraf already applies Docker CLI-style cache adjustment. Do not subtract
inactive file cache again or clamp the result; that double subtraction can create
artificial zeroes and spikes. Historical cAdvisor data still uses working-set bytes.
This is dashboard/alert coverage, not full metric-for-metric parity: non-Docker
cgroups and unused exporter collectors are not reproduced. Host network sums can
still double-count VPN traffic.

Verify after deployment:

1. Check `docker compose logs --tail=50 telegraf` in `~/deploy/ws-logs`.
2. Check `up{job="telegraf"}` is `1` for all four nodes, with no node-exporter or
   cAdvisor scrape targets remaining.
3. Check every shared dashboard panel for each node, and check the disk alert
   query still returns every node's writable root filesystem.

To roll back, restore the saved server configuration and restart Prometheus/Grafana.
For a remote host, use its retained legacy project directories and saved metadata
to recover the old image versions/settings, then run `docker compose up -d` only
in those exporter projects. Restore the corresponding Git/inventory configuration
before the next managed deployment. Do not delete metric history.

## Alerts

The node availability rule checks:

```promql
up{job=~"nodeexporter|telegraf", availability_alert="true"}
```

Each series below 1 for two minutes creates an alert for its `node`. Currently only
`nt1` and `nk1` opt in. An unreachable exporter/network also triggers it; this is a
reachability check, not proof the machine is powered off. cAdvisor failure alone
does not page you. Missing all query data and evaluation failures generate Grafana
NoData/Error alerts, routed to Telegram too.

The **Disk space below 20% free** rule checks all monitored nodes, independently
of availability-alert opt-in. Each writable, non-empty filesystem with less than
20% available space for five minutes generates an alert identifying its node,
mountpoint, and device. It uses Telegraf's `disk_free / disk_total` for writable
filesystems (`mode="rw"`), or `node_filesystem_avail_bytes / node_filesystem_size_bytes`
on exporter nodes. Both exclude reserved blocks, `tmpfs`, `overlay`, and `squashfs`.
Telegraf's `path` label is normalized to `mountpoint`; read-only and zero-sized
filesystems are excluded. Evaluation remains once per minute.

Both rules route through **Monitoring Telegram**, including NoData/Error alerts.
After deployment, test that contact point in Grafana and check the Prometheus
targets. No test notification is sent by Ansible. Alerts in
`grafana/provisioning/alerting/rules.yml` must preserve node labels and cannot use
dashboard variables.

## Adding, disabling, and retiring nodes

For a fresh Debian/Ubuntu server, use the [automated node bootstrap](../../node/init.md):
it installs Docker/security updates/SSHGuard, saves SSH and monitoring inventory,
deploys Telegraf, updates this stack, and verifies the new scrape target.
The manual steps below remain useful for existing Docker hosts.

1. Add SSH details to the private `hosts` inventory.
2. Add the same host to `monitored_nodes` in `monitoring.inventory.yml`.
3. Configure the metrics address, `monitoring_client_telegraf_port` if not 9273,
   and a non-empty `monitoring_telegraf_allowed_sources` list. Set
   `monitoring_availability_alert: true` if it should page you.
4. For a new Docker host, deploy Telegraf, then redeploy the monitoring server:

```sh
ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  --vault-password-file=.ansible_pass playbooks/ws-logs/deploy-clients.yml -l newnode

ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  --vault-password-file=.ansible_pass playbooks/ws-logs/deploy.yml
```

The client playbook requires Docker Compose and sudo. Both the client role and
`node/nt1/services.deploy.yaml` now deploy Telegraf, not the old exporters; always
load the monitoring overlay for endpoint restrictions. For an existing exporter
host, keep the old containers until server-side checks pass, then retire them:

```sh
ansible-playbook -i ./hosts -i ./monitoring.inventory.yml \
  --vault-password-file=.ansible_pass playbooks/ws-logs/retire-exporters.yml -l newnode
```

The retirement playbook supports the existing single-file Compose projects;
back up multi-file legacy projects manually before attempting their migration.

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
The searchable **Container** dropdown lists containers on the selected nodes from
both Telegraf and cAdvisor. Open it, type a name, and select one or several containers
to filter all four container charts and their legends; **All** restores every container.
Host charts are unaffected. The list discovers currently reported containers, not
containers that only exist in historical data. Search lives in this dashboard filter,
not inside individual legends.
A shared crosshair marks the hovered timestamp across charts. Node panels include
filesystem utilization (%), available disk space (automatically scaled to GiB/TiB),
1/5/15-minute load averages, and logical CPU count. Available space excludes blocks
reserved for root. Container charts are full-width with right-side table legends
sorted by latest non-null value, highest first. Click the value-column header to
change sorting; legend values reflect the end of the selected time range, not the
hovered timestamp.

The **Monitoring / NVIDIA GPUs** dashboard lives in `grafana/dashboards/nvidia.json`
with UID `monitoring-nvidia`. Its node selector discovers only GPU exporter targets
(currently `workstation`). It shows exporter availability, GPU utilization, used/total
VRAM, temperature, power draw/limit, fan speed, and graphics/memory clocks. Legends
include node and GPU UUID so multiple GPUs stay distinct. Ratio metrics use 0–1
percentage units; memory and clocks are already exported in bytes and Hz. Unsupported
hardware metrics remain **No data**, not zero.

To restore the GPU dashboard after the IaC migration, run the ordinary server
`deploy.yml` command above, **without** `monitoring_replace_ui=true`. No exporter
or Compose changes are required. Then open **Monitoring / NVIDIA GPUs** and check
`up{job="nvidia-gpu-exporter", node="workstation"}` in Prometheus if panels are empty.

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
