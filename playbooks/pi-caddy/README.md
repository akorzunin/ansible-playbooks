# Workstation edge Caddy

The directory name is retained from the old Pi deployment. `deploy.yaml` now targets
`remote_workstation` (`192.168.1.132`), installing into `/srv/deploy/caddy`.
Caddy uses host networking, with TCP 80/443, UDP 443 (HTTP/3), and its admin API on
loopback port 2019. The separate `sing-box-configs` container remains on port 18085.

Caddy is pinned to the Pi's version, `2.8.4-alpine`, for this migration. Upgrade it
separately after verifying the cutover.

## Deployment

Run from the repository root:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass playbooks/pi-caddy/deploy.yaml
```

The playbook validates the configuration before recreating the container. Existing
certificate state in `caddy_data` is retained. Never commit certificate private keys
or enrollment credentials to the repository.

`playbooks/sing-box-configs/deploy.yaml` now updates the edge Caddy on the workstation,
not the old Pi. Both deployments retain the profile endpoint's log redaction.

## Migration preparation

Before starting the workstation instance:

1. Confirm ports 80, 443, and 2019 are free and the workstation IP is reserved in DHCP.
2. Back up the Pi's `/home/akorz/deploy/pi-caddy/` configuration and storage privately.
3. Copy `caddy_data` to `/srv/deploy/caddy/caddy_data`, preserving permissions and
   ownership, so the existing certificates are available before port forwarding changes.
   Do not share a live storage directory between the two instances.
4. Deploy and verify TLS using the real domain names through a private SSH tunnel.
5. Keep the Pi running for rollback until external verification succeeds.

The migration was staged and completed on 2026-10-11. The controller's temporary
certificate archive was removed after verification; the Pi's original configuration
and certificate storage remain intact for rollback.

The staging SSH tunnel was closed after verification. For future router management
or private testing, open a tunnel with these loopback-only forwards:

- `http://127.0.0.1:18081/` → Keenetic `192.168.1.1:80`.
- `127.0.0.1:18443` → workstation Caddy `127.0.0.1:443`.

To open the tunnel:

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -p 22123 \
  -L 127.0.0.1:18081:192.168.1.1:80 \
  -L 127.0.0.1:18443:127.0.0.1:443 \
  akorz@akorz.duckdns.org
```

Validate the staged site's certificate without disabling verification:

```sh
curl --noproxy '*' --connect-to jellyfin.akorz.duckdns.org:443:127.0.0.1:18443 \
  -I https://jellyfin.akorz.duckdns.org/
```

Root-path smoke tests match the Pi for 25 of 26 domains. Existing unavailable
backends (502) remain unavailable. `fs.akorz.duckdns.org` changes from 403 to 200:
Copyparty accepts the workstation-local proxy, and the owner confirmed this is
intentional for on-demand encrypted file sharing. No authentication was added.
Root status checks do not replace authenticated application tests.

The staged Jellyfin video download reached 77–81 Mbps through the private SSH/TLS
preview tunnel and about 1.5 Gbps over workstation-local HTTPS. After cutover, a
128 MiB public video download averaged 66.4 Mbps with playback paused, versus
47.5 Mbps through the Pi before migration. Busy tests sharing bandwidth with playback
averaged 44–47 Mbps; these are not isolated capacity measurements.

Post-cutover verification confirmed that public connections reach workstation
Caddy, HTTP redirects work, HTTPS certificates validate, and HTTP/3 works over UDP
443. Android, Windows, and Linux profile downloads passed authenticated JSON and
`no-store` checks; invalid/missing tokens still return 404. Pi Caddy was stopped
with `docker compose stop caddy`; unrelated Pi services remain running.

The previously unavailable backends still return 502. The on-demand file server
also returned 502 after cutover because nothing was listening on workstation port
4444 at verification time; its Caddy route was retained as requested.

## Keenetic cutover

Log into the router through the tunnel and save a configuration backup. Change the
existing WAN forwarding rules, preserving their external/internal port numbers:

| Protocol | External port | New destination | Internal port |
| --- | --- | --- | --- |
| TCP | 80 | 192.168.1.132 | 80 |
| TCP | 443 | 192.168.1.132 | 443 |
| UDP | 443 | 192.168.1.132 | 443 |

UDP 443 is optional for HTTP/3; update it if already forwarded, or add it if HTTP/3
is wanted. TCP 80 is still needed for HTTP redirects and certificate validation.
Do not change SSH forwarding (22123/22158), router management, or unrelated rules.
Do not expose ports 2019, 18085, or 8096 directly to the internet.

No DNS change is needed while the public IP is unchanged. Any existing public IPv6
AAAA records and IPv6 firewall rules need separate review; IPv4 forwarding does not
change IPv6 routing.

After switching, verify from outside the server LAN (without the Caddy preview
tunnel): valid HTTPS, HTTP redirects, Jellyfin playback/throughput, other required
applications, and profile endpoint behavior. Existing playback connections may
need reconnecting before they take the new path.

Once verified, stop the old Pi Caddy, leaving its state intact for rollback. Do not
stop unrelated Pi services used as upstreams (Homepage, Portainer, WoL).

## Rollback

Restore TCP 80/443 (and UDP 443 if used) forwarding to `192.168.1.58`, with the same
internal ports. If Pi Caddy was stopped, start it again:

```sh
ansible remote_pi -i hosts --vault-password-file .ansible_pass \
  -m ansible.builtin.command \
  -a 'docker compose up -d chdir=/home/akorz/deploy/pi-caddy'
```

Before deploying profile routes during a rollback, also restore that playbook's
router target to `remote_pi` and its path to `/home/akorz/deploy/pi-caddy`.
The Pi's certificates will not receive renewals made only on the workstation; a
long-delayed rollback needs a fresh certificate-state review.

Close a foreground SSH tunnel opened with the command above using Ctrl-C.
