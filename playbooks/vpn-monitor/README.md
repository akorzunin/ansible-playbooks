# Workstation VPN monitor

Deploy the sibling [vpn-monitor](../../../vpn-monitor) checkout and provision its
metrics in the existing workstation Prometheus/Grafana stack. No VPN servers,
active clients, DNS records or firewall rules are changed.

## Inputs

- Existing `remote_workstation` must be the single `monitoring_servers` host,
  with the monitoring stack/network `ws-logs_default` already installed.
- Add `monitoring_vpn_monitor_enabled: true` to that host in private `hosts`.
- This repo owns the workstation configuration:
  - [`config.yaml`](config.yaml): tracked probe settings and explicit server/protocol
    allowlist. Each `outbound_tag` references the shared encrypted profile Vault.
  - [`../sing-box-configs/secrets.vault.yaml`](../sing-box-configs/secrets.vault.yaml):
    `sing_box_secrets.connections` / `extra_outbounds` supply native sing-box outbounds;
    `vpn_monitor_secrets` supplies `VPN_MONITOR_API_TOKEN` and `VPN_MONITOR_UDP_TOKEN`.
    Edit with `ansible-vault edit --vault-password-file=.ansible_pass
    playbooks/sing-box-configs/secrets.vault.yaml` from the repo root.
  No sibling private `config.yaml` or `.env`, generated profile JSON, or prior publish
  is needed. The sibling checkout supplies application source only.
  Existing monitor tokens were migrated unchanged into Vault; no rotation is required.
- Controller: Go 1.25+, Node 22.12+, npm and the existing Ansible collections.
  This deployment builds a static Linux **amd64** binary. Override
  `vpn_monitor_source_dir` with an absolute checkout path if it is not adjacent.
- Existing shared `external_vars.yml` and Vault password supply Grafana credentials.

```sh
# From ansible-playbooks/
ansible-playbook -i ./hosts --vault-password-file=.ansible_pass \
  playbooks/vpn-monitor/deploy.yml --syntax-check
ansible-playbook -i ./hosts --vault-password-file=.ansible_pass \
  playbooks/vpn-monitor/deploy.yml
```

The playbook resolves allowlisted tags directly from Vault using `generate.py`.
Missing/duplicate tags and chained outbounds fail deployment rather than silently
omitting probes. The monitor supports standalone routes only; do not strip `detour`
from a chain to pretend it is a direct route. Aurora and newly published outbounds
are not monitored unless explicitly added to this repo's allowlist.

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

The tracked allowlist monitors only GE2 (SSH, Naïve and VLESS); the workstation's
active Aurora VPN connection is independent. Generated credentials exist only in
Ansible memory and mode-0600 runtime `~/deploy/vpn-monitor/config.yaml` / `.env`
(and private backups) on the workstation. The runtime config changes the tracked
loopback listen address to `0.0.0.0:8081` for the private Docker bridge. Protect
runtime files and backups; edit tracked settings/Vault, not deployed files.

## Optional UDP and bounded downloads

These tests need explicit configuration; empty Grafana panels otherwise mean
**disabled/unsupported**, not zero loss or zero throughput. SSH and Naïve do not
support this monitor's UDP test; the direct GE2 VLESS route does.

The separate `echo-ge2.yml` playbook installs the project's static `--echo` binary
as a sandboxed, reboot-persistent systemd service on existing GE2. It reads the same
`vpn_monitor_secrets.VPN_MONITOR_UDP_TOKEN` from the shared Vault as the checker.
For a new setup, store random API/UDP tokens of at least 24 characters there before deploying:

```sh
ansible-playbook -i ./hosts --vault-password-file=.ansible_pass \
  playbooks/vpn-monitor/echo-ge2.yml
```

Unlike the main workstation playbook, this explicitly adds firewall rules: a
dedicated nftables table restricts **UDP 9444 only** to GE2, Aurora's exit IP and
GE2's VPN Docker subnet (`172.22.0.0/16`). It rate-limits accepted traffic and
requires an HMAC-authenticated payload. Other firewall tables are untouched.
Update the allowlist if the exits or VPN Docker subnet change. GE2-to-itself
probes measure the tunnel, **not onward Internet UDP routing**. The allowlist
still permits Aurora, but the workstation monitor no longer probes it.

The tracked `config.yaml` enables these bounded tests with:

```yaml
udp:
  endpoint: 94.249.187.177:9444
  token_env: VPN_MONITOR_UDP_TOKEN
  samples: 10
  timeout: 1s
speed:
  url: https://speed.cloudflare.com/__down?bytes=4194304
  max_bytes: 4194304
  timeout: 15s
```

Rerun `deploy.yml` after changing tracked settings, outbounds or monitor tokens in
Vault. After rotating the UDP token, also rerun `echo-ge2.yml` to keep both ends in sync.
A 4 MiB download per route every five minutes consumes up to **3.4 GiB/day across
three routes**, plus ordinary probe traffic. This is a bounded throughput sample,
not sustained capacity. The public download service can fail independently of
the VPN; inspect the per-test errors rather than assuming VPN blocking.

Verify `vpn_monitor_udp_loss_ratio`, `vpn_monitor_udp_rtt_seconds` (GE2 VLESS),
and `vpn_monitor_speed_bits_per_second` (three routes) in Prometheus after
tests finish and the next scrape completes. Old disabled history is retained.

To stop the endpoint, disable/stop `vpn-monitor-echo.service` on GE2. Only after
stopping it, remove its dedicated table with `nft delete table inet vpn_monitor_echo`;
remove/disable `udp` in the checker config to avoid failed probes.

## Stop / rollback

Stop only this app with `docker compose stop vpn-monitor` in its deployment directory.
Set `monitoring_vpn_monitor_enabled: false` in private inventory and run ws-logs
`deploy.yml` to remove the scrape job. Keep `data/` for history. For an application
rollback, check out the prior source and rerun this playbook; configuration changes
retain private Ansible backup files beside `config.yaml` and `.env`. No automatic
rollback is performed if monitoring verification fails after application startup.
