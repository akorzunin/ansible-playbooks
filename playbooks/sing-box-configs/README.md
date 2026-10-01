# Remote sing-box profiles

Full Android, Windows and Linux profiles are served from the workstation through
`https://configs.akorz.duckdns.org`, with HTTPS terminated by the existing Pi Caddy.
Clients remember a stable private URL; republishing replaces its content, not its URL.
No subscription converter or management database is needed.

## Enroll devices

Private enrollment artifacts are generated in `private/` (ignored by Git, mode 0700):

- `urls.json`: paste the appropriate HTTPS URL into a **remote** profile in the client.
- `import-links.json`: `sing-box://import-remote-profile` links for compatible clients.
- `tokens.json`: stable platform tokens. Back up this file securely to preserve URLs.

For Android, use sing-box for Android. For Windows, use a client that accepts full
sing-box JSON remote profiles and supports Naïve, SSH, selectors and URLTest.
Enable automatic profile updates (normally hourly); importing as a local file
will **not** subscribe it to updates. A refresh/reconnect may be required to apply
updates while connected, depending on the client. Android battery restrictions
can delay background updates.

Profiles target sing-box 1.14+ and were checked with the controller's 1.14.1.
Remote rule-set downloads use explicit `http_client: {"engine": "go"}` instead
of deprecated `download_detour` or implicit default clients. This client dials
directly without a detour; `{}` would select the deprecated implicit client,
and `detour: "direct"` is rejected for an empty direct outbound. TUN `stack` is omitted:
1.14 uses its default stack; 1.15 uses the new sing-tun stack without a deprecation
warning. This follows the upstream [migration guide](https://sing-box.sagernet.org/migration/)
and [deprecated feature list](https://sing-box.sagernet.org/deprecated/); pre-release
1.15 behavior still needs device-side testing.
Use compatible Naïve-enabled cores; Windows also needs its matching Cronet DLL.
A configuration update cannot add protocols unsupported by the installed app.
Device-side Android/Windows runtime testing is still required.

Deployment verification: all three public profiles matched the generated files;
wrong/missing tokens, cross-platform token use, directory listing and POST were
rejected. Linux successfully applied an update and skipped an unchanged one.
Isolated connection tests from this Linux machine passed for Naïve and SSH;
VLESS timed out despite its TCP port being reachable. Its settings match the
supplied Windows profile, so VLESS connectivity (and consequently UDP) needs
separate investigation; hosting/config distribution itself is working.

Each platform currently has one token, shared by devices using that platform.
For independent revocation per device, issue separate tokens before sharing with
additional people. Treat enrollment/import links as passwords, not public links.

## Connections and routing

All profiles use the controller's private `~/.local/share/nt1-{vless,naive,ssh}.json`
files, including their real credentials. These files replace the outbounds in the
original Android/Windows examples (including the Android placeholder SSH login).

- Automatic selection: URLTest, checks every 3 minutes, 50 ms tolerance.
- Initial test order: Windows/Linux VLESS → Naïve → SSH; Android Naïve → SSH → VLESS.
- URLTest selects by **latency**, not strict priority. It can choose Naïve/SSH even
  when VLESS is healthy. The `proxy` selector also allows choosing a protocol manually.
- UDP always uses VLESS: this nt1 Naïve deployment and SSH do not provide UDP relay.
- Existing Russian-domain/GeoIP direct routing and platform inbounds are preserved.
- Linux retains the existing local mixed/system-proxy listener on `127.0.0.1:12334`;
  it does not gain a TUN interface. Windows retains its TUN and mixed listener;
  Android retains its TUN.
- Recovery HTTPS and rule-set downloads use direct routing. TUN traffic is sniffed
  before matching the configuration hostname.
- Clash API/group controls bind only to `127.0.0.1:9091`.

These three protocols all use **the same nt1 host**. Protocol selection is not
redundancy against a complete nt1 outage. Publish a replacement server through
the independent config endpoint to recover, or add a second server deliberately.

## Publish a change

From the repository root:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/sing-box-configs/deploy.yaml
```

This generates and validates all three profiles on the controller, publishes them
atomically on the workstation, validates static hosting, adds/reloads the Pi route,
and verifies all HTTPS URLs **without an HTTP proxy**. Existing clients fetch the
new contents on their next update; they do not need to be re-enrolled.

Edit `templates/{android,windows,linux}.json` for platform settings and routing.
These are credential-free snapshots of the supplied configs and Linux base config.
Edit the private outbound files above for server/credential changes, then rerun
the publish playbook. Merely editing a source file does not publish it automatically.
The original `android.json` and `win-all-proxy.json` are kept privately for reference,
ignored by Git, and are not the ongoing source of shared connection credentials.

Generate/check locally without deploying:

```sh
python playbooks/sing-box-configs/generate.py
python -m unittest discover -s playbooks/sing-box-configs -p 'test_*.py'
```

## Linux automatic updates

Enroll the machine running Ansible (requires an existing `/etc/sing-box/config.json`):

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/sing-box-configs/linux-client.yaml
```

The root-owned `/etc/sing-box-profile.json` stores the URL outside sing-box's
configuration directory, so `sing-box -C /etc/sing-box` does not parse it as a config.
The `sing-box-profile-update.timer` runs hourly with up to 5 minutes of jitter,
and shortly after boot. The updater:

1. Fetches HTTPS directly, ignoring proxy environment variables; rejects redirects.
2. Retains the current config on download failure or invalid data.
3. Skips unchanged profiles, otherwise runs `sing-box check`.
4. Preserves config ownership/permissions and replaces it atomically.
5. Restarts sing-box; restores the previous config on an immediate startup failure.

Startup verification checks the service after 2 seconds; it is not an end-to-end
connectivity test. Remote hosting can be offline without disabling the cached VPN.
`sb apply` still works, but the next remote update will overwrite local changes.

```sh
sudo systemctl start sing-box-profile-update.service  # refresh now
systemctl list-timers sing-box-profile-update.timer
journalctl -u sing-box-profile-update.service --no-pager
```

Unenroll and restore the config saved before initial enrollment:

```sh
sudo systemctl disable --now sing-box-profile-update.timer
sudo systemctl stop sing-box-profile-update.service
sudo install -o root -g sing-box -m 640 /etc/sing-box/config.before-remote /etc/sing-box/config.json
sudo systemctl restart sing-box
```

## Hosting and security

Workstation files live in root-only `/srv/deploy/sing-box-configs/`. The static Caddy
container publishes only `192.168.1.132:18085`, not all host interfaces. Do **not**
forward this port through the router. Pi → workstation HTTP assumes a trusted LAN;
use TLS on that hop if the LAN is untrusted. Public clients must use HTTPS.

Only exact token/platform paths and GET/HEAD are served. Missing/wrong tokens,
directory requests and other files return 404. Responses use `Cache-Control: no-store`.
Hosting request logs are disabled; Pi structured logs redact request URIs and
headers to avoid leaking enrollment URLs during reverse-proxy errors.
Do not enable unfiltered access/debug logging for this endpoint.

The deployment uses `remote_workstation` and `remote_pi` inventory aliases. Pi
Caddyfile changes are staged and validated before activation, with rollback on
reload failure. Updates preserve its file bind mount; a pre-existing stale mount
is detected and repaired by recreating the router container (brief HTTPS outage).
The route and log redaction are also in `playbooks/pi-caddy/Caddyfile` so a later
full Pi Caddy deployment retains them.

To rotate a leaked platform URL, replace its token in `private/tokens.json` with
64 random lowercase hex characters and republish. Re-enroll affected devices;
rerun `linux-client.yaml` for Linux. URL rotation stops future downloads but does
**not** revoke proxy credentials already downloaded: rotate those separately.
