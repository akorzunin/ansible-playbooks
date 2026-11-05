# Workstation VPN monitor

Deploy the sibling [vpn-monitor](../../../vpn-monitor) checkout and provision its
metrics in the existing workstation Prometheus/Grafana stack. No VPN servers,
active clients, DNS records or firewall rules are changed.

## Inputs

- Existing `remote_workstation` must be the single `monitoring_servers` host,
  with the monitoring stack/network `ws-logs_default` already installed.
- Add `monitoring_vpn_monitor_enabled: true` to that host in private `hosts`.
- Keep the sibling project's **private** `config.yaml` and `.env` in place.
  Configuration uses `listen: 127.0.0.1:8081`, `sing_box: sing-box`,
  `web_dir: web/dist`, and `history_file: data/history.json`.
  The API token named by `api_token_env` must be a plain `KEY=value` entry in
  `.env`. Secrets are copied with mode 0600 and suppressed in Ansible output.
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

The playbook builds on the controller, transfers only the binary/public web assets
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

The current private config is used as-is apart from the container listen address;
no Telegram bot or UDP endpoint is added implicitly. API credentials and private
SSH tunnel keys remain on the workstation. Protect its files and backups.

## Stop / rollback

Stop only this app with `docker compose stop vpn-monitor` in its deployment directory.
Set `monitoring_vpn_monitor_enabled: false` in private inventory and run ws-logs
`deploy.yml` to remove the scrape job. Keep `data/` for history. For an application
rollback, check out the prior source and rerun this playbook; configuration changes
retain private Ansible backup files beside `config.yaml` and `.env`. No automatic
rollback is performed if monitoring verification fails after application startup.
