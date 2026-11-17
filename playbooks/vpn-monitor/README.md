# Workstation VPN monitor

Deploy the sibling [vpn-monitor](../../../vpn-monitor) checkout and provision its
metrics in the existing workstation Prometheus/Grafana stack. No VPN servers,
active clients, DNS records or firewall rules are changed.

## Current status: retired probes

GE2 is blocked and has been removed from the allowlist, including its UDP endpoint.
`config.yaml` now has `servers: []`; the workstation monitor is stopped and
`monitoring_vpn_monitor_enabled: false` removes its Prometheus scrape job. History
is retained. Before deploying again, review the surviving Vault routes and enable
the inventory opt-in. `deploy.yml` now discovers standalone servers from Vault by
default, even when the tracked list is empty; it rejects an empty discovered list. The GE2-specific echo deployment playbook
has been removed. No changes are made on the blocked server itself.

## Inputs

- Existing `remote_workstation` must be the single `monitoring_servers` host,
  with the monitoring stack/network `ws-logs_default` already installed.
- Add `monitoring_vpn_monitor_enabled: true` to that host in private `hosts`.
- This repo owns the workstation configuration:
  - [`config.yaml`](config.yaml): tracked probe settings and optional manual
    server/protocol allowlist. Each `outbound_tag` references the shared encrypted
    profile Vault. By default the playbook replaces this list in memory with
    discovered standalone routes.
  - [`../sing-box-configs/secrets.vault.yaml`](../sing-box-configs/secrets.vault.yaml):
    `sing_box_secrets.connections` / `extra_outbounds` supply native sing-box outbounds;
    `vpn_monitor_secrets` supplies `VPN_MONITOR_API_TOKEN` and `VPN_MONITOR_UDP_TOKEN`.
    Edit with `ansible-vault edit --vault-password-file=.ansible_pass
    playbooks/sing-box-configs/secrets.vault.yaml` from the repo root.
  No sibling private `config.yaml` or `.env`, generated profile JSON, or prior publish
  is needed. The sibling checkout supplies application source only.
  Existing monitor tokens were migrated unchanged into Vault; no rotation is required.
- Controller: Go 1.25+, Node 22.12+, npm, Python 3 with PyYAML, and the existing Ansible collections.
  This deployment builds a static Linux **amd64** binary. Override
  `vpn_monitor_source_dir` with an absolute checkout path if it is not adjacent.
- Existing shared `external_vars.yml` and Vault password supply Grafana credentials.

## Prefill servers from sing-box

From `ansible-playbooks/`, preview standalone routes from the shared encrypted
sing-box source (requires Python 3, PyYAML and `ansible-vault`):

```sh
python3 playbooks/vpn-monitor/prefill-servers.py
# Or select specific nodes; repeat --node to include several:
python3 playbooks/vpn-monitor/prefill-servers.py --node dyn2
```

Optionally save a manual selection, then deploy with automatic discovery disabled:

```sh
python3 playbooks/vpn-monitor/prefill-servers.py --node dyn2 --write
ansible-playbook -i ./hosts --vault-password-file=.ansible_pass \
  playbooks/vpn-monitor/deploy.yml -e vpn_monitor_prefill_servers=false
```

Omit `--node` to include **all eligible nodes in Vault**, not just the newest one.
`--write` replaces the whole `servers` list, so stale entries disappear. Other
settings are preserved, but YAML formatting/comments are normalized. Repeating
an unchanged selection does not rewrite the file. Preview first and review the
diff: every selected route adds test traffic, including configured speed tests.
The script does not enable the inventory opt-in, start services, change Vault,
or contact VPN hosts. No prior profile publication is needed.

Tags must follow `<node>-<type>` (for example `dyn2-vless`); legacy bare protocol
tags are grouped under `default`. Unsupported types, unrecognized aliases,
`workstation-hop`, chains and routing overrides are skipped. Duplicate tags,
missing requested nodes, empty selections and more than 64 routes fail without
writing. Only names/tag references enter the public config, never credentials.
UDP defaults to `false`; enable it explicitly only after configuring a suitable
endpoint and confirming protocol/server support. New runs reset route-level UDP
flags to `false`. Override paths with `--config`, `--vault-file` and
`--vault-password-file` if needed.

## Deploy

```sh
# From ansible-playbooks/
ansible-playbook -i ./hosts --vault-password-file=.ansible_pass \
  playbooks/vpn-monitor/deploy.yml --syntax-check
ansible-playbook -i ./hosts --vault-password-file=.ansible_pass \
  playbooks/vpn-monitor/deploy.yml
```

No separate prefill run is needed: by default the playbook invokes
`prefill-servers.py --stdin` with the Vault data Ansible already decrypted. It
replaces `servers` **in memory only**, preserving all other tracked settings and
leaving local `config.yaml` untouched. Every eligible Vault node is selected,
including newly registered nodes; every selected route adds test/speed traffic.
The inventory monitoring opt-in remains required.

To monitor only specific nodes, pass a JSON list (or set it in inventory):

```sh
ansible-playbook -i ./hosts --vault-password-file=.ansible_pass \
  playbooks/vpn-monitor/deploy.yml -e '{"vpn_monitor_nodes":["dyn2"]}'
```

Set `vpn_monitor_prefill_servers: false` (CLI: `-e vpn_monitor_prefill_servers=false`)
to use the tracked allowlist unchanged, including any manually enabled UDP flags.
`vpn_monitor_nodes` applies only to automatic discovery. Discovered routes have
UDP disabled; discovery never guesses endpoint or server support.

After discovery, `generate.py` resolves selected tags directly from Vault.
Missing/duplicate tags and explicitly selected chained outbounds fail deployment.
Automatic discovery skips chains and routing overrides; never strip `detour`
from a chain to pretend it is a direct route.

It builds on the controller, transfers only the binary/public web assets
into a Docker build context, and uses the pinned workstation sing-box image with
Naïve/QUIC support. Credentials never enter image layers. It validates application
configuration before starting, then applies the ordinary monitoring deployment
(**not** UI replacement), verifies an authenticated Prometheus scrape, route metrics,
and Grafana file provisioning. It intentionally refuses `--check`; builds and live
validation are required. Repeating the run does not restart an unchanged monitor.

The app runs as the workstation user in `~/deploy/vpn-monitor`, with a read-only
root filesystem, no capabilities, bounded logs/resources, and persistent `data/`.
Docker restarts it after reboot. Only `127.0.0.1:8081` is published; the app listens
on its container interface so Prometheus can scrape `vpn-monitor:8081` over the
existing monitoring bridge. The API token also protects internal metrics/API access.
This measures workstation egress through a Docker bridge, not a host-native socket;
host TUN/proxy/firewall routing can still affect results. No bypass is claimed.

Prometheus reads `~/deploy/ws-logs/secrets/vpn-monitor-token` through a read-only
mount, never from public YAML. Subsequent ordinary ws-logs deployments preserve
the scrape job through the inventory opt-in. Redeploy this playbook after rotating
the token so both the monitor and scraper receive it together.

## Access and verification

- Web UI: workstation `http://127.0.0.1:8081`; log in with the existing project token.
  From another machine, use SSH forwarding rather than exposing the bearer token
  over public HTTP: `ssh -L 18081:127.0.0.1:8081 <workstation-ssh-host>`, then open
  `http://127.0.0.1:18081`.
- Grafana: `/d/vpn-monitor`, in **Monitoring / VPN monitor**, using the fixed
  `monitoring-prometheus` datasource. The tracked dashboard adapts the project's
  `examples/grafana-dashboard.json`; preserve that fixed UID and `editable: false`
  when syncing panel updates.
- Prometheus: `up{job="vpn-monitor"}` must be `1`; `vpn_monitor_healthy` contains
  each server/protocol. A successful scrape does **not** mean VPN routes are healthy.
  Startup checks run serially, so latency/throughput appear as tests complete.
  UDP/speed panels intentionally have no data when those tests are disabled.

```sh
cd ~/deploy/vpn-monitor
docker compose ps
docker compose logs --tail=50 vpn-monitor
```

The tracked allowlist is empty; the workstation's active Cherry VPN connection
is independent. When deployed, generated credentials exist only in
Ansible memory and mode-0600 runtime `~/deploy/vpn-monitor/config.yaml` / `.env`
(and private backups) on the workstation. The runtime config changes the tracked
loopback listen address to `0.0.0.0:8081` for the private Docker bridge. Protect
runtime files and backups; edit tracked settings/Vault, not deployed files.

## Optional UDP and bounded downloads

UDP testing is disabled: its former GE2 endpoint is blocked. A future deployment
needs an explicitly configured, authenticated endpoint and approved firewall
allowlist. SSH and Naïve do not support this monitor's UDP test. Empty panels mean
**disabled/unsupported**, not zero loss or zero throughput.

The retained speed settings cap each download at 4 MiB with a 15-second timeout.
With three routes every five minutes this can consume **3.4 GiB/day**, plus
ordinary probe traffic. No downloads run while the monitor is stopped. This is
a bounded throughput sample, not sustained capacity; the public download service
can fail independently of the VPN.

## Stop / rollback

Stop only this app with `docker compose stop vpn-monitor` in its deployment directory.
Set `monitoring_vpn_monitor_enabled: false` in private inventory and run ws-logs
`deploy.yml` to remove the scrape job. Keep `data/` for history. For an application
rollback, check out the prior source and rerun this playbook; configuration changes
retain private Ansible backup files beside `config.yaml` and `.env`. No automatic
rollback is performed if monitoring verification fails after application startup.
