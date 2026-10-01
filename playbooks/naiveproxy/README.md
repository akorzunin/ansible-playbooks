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
controller, verifies the pinned SHA-256, and copies the binary to nt1. No Docker
image or Go/Chromium build runs on the server. The archive is cached under
`~/.cache/ansible-naiveproxy` on the controller.

The unprivileged `naiveproxy.service` has a **64 MiB hard memory limit**, a
48 MiB soft limit and a 40 MiB Go memory target. This is sized for a single-user
1 GiB VPS; increase the limits deliberately if real workloads cause OOM kills.

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
  -a 'systemctl status naiveproxy --no-pager; journalctl -u naiveproxy -n 40 --no-pager; systemctl show naiveproxy -p MemoryCurrent -p MemoryPeak -p NRestarts'
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

Restore the previous router file **in place**, reload Caddy, then stop the backend:

```sh
sudo cp /srv/deploy/caddy/Caddyfile.before-naive /srv/deploy/caddy/Caddyfile
sudo docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl disable --now naiveproxy
```

Also remove the `@naive` route from `node/nt1/caddy/Caddyfile` before a subsequent
normal Caddy deployment. Do not restore an old backup blindly if unrelated router
changes have been made since deployment. Certificates and service files can be
retained for a later retry; the existing SSH/VLESS configs are not modified.
