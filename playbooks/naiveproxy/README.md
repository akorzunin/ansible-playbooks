# NaïveProxy on nt1

Authenticated, padded HTTP/2 CONNECT on `naive.akorz-nt1.duckdns.org:443`.

The existing Caddy layer4 listener passes this SNI through to a separate Caddy
with klzgrad's Naïve `forward_proxy` module on `127.0.0.1:8444`. Existing websites,
MTProxy, SSH and VLESS are unchanged. The backend gets a public certificate using
TLS-ALPN-01 through the port-443 passthrough; it does not need public port 8444.

## Deploy

From the repository root:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/naiveproxy/deploy.yaml
```

The playbook downloads the **upstream prebuilt Linux amd64** server on the
controller, verifies the pinned SHA-256, and copies the binary to nt1. No
Go/Chromium compilation runs on the server. The archive is cached under
`~/.cache/ansible-naiveproxy` on the controller. Docker only packages the static
binary and the host CA trust store into a small `scratch` image using
`/srv/deploy/naiveproxy/compose.yaml`.

The `naiveproxy` container runs as the existing unprivileged account, with host
networking, a read-only root filesystem, a **64 MiB hard memory limit** and a
40 MiB Go memory target. There is no `MemoryHigh` soft limit: the former 48 MiB
limit caused sustained reclaim throttling and blocked proxy threads on this
swapless VPS. Increase the hard limit deliberately if real workloads cause OOM
kills. The container appears in the existing cAdvisor/Grafana container panels.

### Persistent data and migration

The container bind-mounts the existing host paths without moving their contents:

- `/etc/naiveproxy` (read-only): Caddyfile with the existing credentials.
- `/var/lib/naiveproxy` (read-write): certificates, private keys and ACME account.

Both `XDG_DATA_HOME` and `XDG_CONFIG_HOME` retain `/var/lib/naiveproxy`, so Caddy
uses the same storage paths as the former systemd service. Recreating the container
or running `docker compose down` does not delete these host directories. Back up
both directories securely; neither credentials nor certificates belong in the image.

Running the deployment also migrates the legacy systemd installation. It refuses
to change its configuration during migration, prepares the image before cutover,
stops/disables `naiveproxy.service`, and saves a private
`/srv/deploy/naiveproxy/pre-docker-state.tar.gz` before starting Docker. A failed
migration restores the previously running systemd service. The legacy unit and
binary remain installed for rollback but are not used by Docker.

The hostname, port, credentials, certificates and public router are unchanged;
**clients do not need new configs**. Active proxy connections briefly disconnect
during cutover.

By default the username is `naive`, and a random password is persisted in the
controller's private `~/.local/share/nt1-naiveproxy-password`. Alternatively set
`NAIVEPROXY_USER` and `NAIVEPROXY_PASSWORD` in encrypted `external_vars.yml`.
Use at least 24 ASCII letters/digits/underscores/hyphens for the password.
The backend configuration is root-owned and only readable by its service group.

The public router configuration is validated before reload and restored if
reload fails. Its bind-mounted file is updated in place, so no existing
containers need to be recreated. The previous configuration is retained as
`/srv/deploy/caddy/Caddyfile.before-naive`.

## Client

The playbook writes `~/.local/share/nt1-naive.json` on the controller with mode
0600. After certificate issuance completes:

```nu
sb apply nt1-naive.json
```

This uses sing-box's Chromium-backed Naïve HTTP/2 outbound, not a generic HTTPS
proxy. The installed sing-box must support `with_naive_outbound` and its runtime
requirements. Keep its Chromium/Cronet stack up to date for fingerprint matching.

HTTP/3 is deliberately disabled: nt1's UDP/443 belongs to its existing Caddy,
and the current layer4 passthrough is TCP-only. Supporting HTTP/3 would require
explicit QUIC routing, not merely enabling `quic` in the client. This deployment
also does not provide UDP-over-TCP relay support.

## Check

Initial deployment and comparison measurements: [RESULTS.md](RESULTS.md).

```sh
ansible nt1 -i hosts --vault-password-file .ansible_pass -b \
  -m ansible.builtin.shell \
  -a 'docker ps --filter name=naiveproxy; docker logs --tail 40 naiveproxy; docker stats --no-stream naiveproxy'
```

To repeat the isolated comparison from this workstation (requires the private
`nt1-ssh.json`, `nt1-vless.json` and generated `nt1-naive.json`):

```sh
python playbooks/naiveproxy/check.py --rounds 60 --interval 10 \
  --output /tmp/nt1-proxy-comparison
```

The script uses the shared sing-box configuration with separate listeners,
caches and processes. It does not restart or change the active VPN. Temporary
credential-bearing configs are deleted when it exits. Results and logs remain
in the output directory.

`sb test` checks one Google HTTPS request, not sustained stability or logged-in
ChatGPT functionality. ChatGPT can challenge automated clients despite healthy
network connectivity; `/cdn-cgi/trace` is useful for unauthenticated transport
checks. Compare repeated tests and concurrent requests before switching your
active config.

## Roll back

To return a migrated installation to its retained systemd service, stop the
container first so only one process uses port 8444 and the certificate store:

```sh
sudo docker compose -f /srv/deploy/naiveproxy/compose.yaml down
sudo systemctl enable --now naiveproxy
```

No router, credential or certificate changes are needed. Do not run the Docker
deployment again unless you intend to migrate back.

To remove NaïveProxy entirely, stop the container and disable any legacy systemd
service. Remove only the `@naive` route from `node/nt1/caddy/Caddyfile` and deploy
the updated router. Do not restore an old router backup blindly if unrelated
changes have been made since deployment. Keep the private config/state directories
and migration backup if a later restore is needed.
