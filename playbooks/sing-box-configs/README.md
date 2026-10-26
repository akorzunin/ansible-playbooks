# Remote sing-box profiles

Full Android, Windows and Linux profiles are served from the workstation through
`https://configs.akorz.duckdns.org`, with HTTPS terminated by the existing Pi Caddy.
Clients remember a stable private URL; republishing replaces its content, not its URL.
No subscription converter or management database is needed.

## Enroll devices

Private enrollment artifacts are generated in `private/` (ignored by Git, mode 0700):

- `urls.json`: paste the appropriate HTTPS URL into a **remote** profile in the client.
- `import-links.json`: `sing-box://import-remote-profile` links for compatible clients.
- `tokens.json`: generated copy of the shared Vault tokens, not their source of truth.

For Android, use sing-box for Android. For Windows, use a client that accepts full
sing-box JSON remote profiles and supports Naïve, SSH, selectors and URLTest.
Enable automatic profile updates (normally hourly); importing as a local file
will **not** subscribe it to updates. A refresh/reconnect may be required to apply
updates while connected, depending on the client. Android battery restrictions
can delay background updates.

Profiles target sing-box 1.14+ and the current generated profiles were checked
with the controller's 1.14.2.
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
separate investigation; hosting/config distribution itself is working. Those
observations refer to the earlier nt1-only trial, not the new Cherry VLESS endpoint.

Current Cherry publication: `cherry-ssh`, `cherry-naive` and `cherry-vless` are
available alongside nt1 through the same private URLs/tokens, with existing nt1
defaults retained. All three public platform files matched generated contents.
The fetched Linux profile passed six isolated direct checks (three protocols,
two HTTPS targets) with the Amsterdam node's egress. This workstation was **not
enrolled** by user choice: its active local `ssh-via-workstation` fallback and
inactive updater timer remain unchanged. Refresh already-enrolled remote profiles
to see the new options; merely having these published does not enroll a local
JSON file or automatically switch protocols.

Each platform currently has one token, shared by devices using that platform.
For independent revocation per device, issue separate tokens before sharing with
additional people. Treat enrollment/import links as passwords, not public links.

## Connections and routing

All profiles use `sing_box_secrets.connections` in `secrets.vault.yaml`, an
Ansible Vault-encrypted file tracked in Git. It also stores the existing platform
tokens in `sing_box_secrets.tokens`. No controller-local outbound files are needed,
and a fresh controller never generates replacement tokens.

- Manual selection only through `proxy`; Auto/URLTest is removed because successful
  probes did not reliably predict usable connections on mobile networks.
- Android defaults to SSH; select VLESS manually when UDP is needed.
- Windows/Linux default to VLESS; select Naïve or SSH manually if it fails.
- `ssh-via-workstation` and `cherry-ssh-via-workstation` reach the corresponding
  SSH server through the workstation. Both are TCP-only; `workstation-hop` is an
  internal transport, not a selectable exit. Defaults remain unchanged.
- Manual changes interrupt existing connections. Selector choices are not persisted
  by the core cache; restarting may restore the platform default.
- Proxied TCP and UDP follow the selected protocol. UDP/443 is no longer rejected.
  This nt1 Naïve deployment and SSH do not provide UDP relay: select working VLESS
  for UDP applications. TCP fallback depends on the application.
- Existing Russian-domain/GeoIP direct routing and platform inbounds are preserved.
- Linux retains the existing local mixed/system-proxy listener on `127.0.0.1:12334`;
  it does not gain a TUN interface. Linux omits `auto_detect_interface`: it is
  unnecessary without TUN and caused startup DNS timeouts on the controller's
  1.14.2 core; unbound direct dialing passed the same test. Windows retains its
  TUN and mixed listener; Android retains its TUN.
- `duckdns.org` and all its subdomains use direct routing, before the catch-all
  UDP rule. This includes recovery HTTPS to the configuration hostname.
  TUN traffic is sniffed first to identify domain names. IP-only connections or
  TLS with hidden SNI (ECH) may not match: a domain rule alone cannot guarantee
  bypass for those; use DNS mapping or destination IP rules if needed.
- Rule-set downloads use direct routing.
- Clash API/group controls bind only to `127.0.0.1:9091`.

These three protocols all use **the same nt1 host**. Protocol selection is not
redundancy against a complete nt1 outage. Publish a replacement server through
the independent config endpoint to recover, or add a second server deliberately.

## Additional VPN nodes

Optionally add `sing_box_secrets.extra_outbounds` to `secrets.vault.yaml`: a list
of complete sing-box outbound objects for additional nodes. The existing
`connections` mapping remains unchanged. Every outbound needs a unique,
nonempty `tag` that does not collide with nt1 or `auto`/`proxy`/`direct`.
The installed sing-box core validates all platforms before any local profile
is replaced. Keep private keys/passwords in Vault, not templates or command-line
arguments. SSH outbounds must pin the independently verified server `host_key`;
only distribute an unprivileged tunnel key, never an administrator key.

The Vault also contains a pinned `workstation-hop` SSH outbound in `extra_outbounds`.
When it is present, generation clones each non-detoured SSH exit (including nodes
supplied through `--extra-outbounds-file`) as `<tag>-via-workstation`, preserving
its credentials and host-key pin and adding `detour: workstation-hop`. The hop
itself is omitted from the selector. Generated tags must not collide with supplied
tags. Removing `workstation-hop` removes the generated chained options.

The workstation's `sing-box-hop` account must allow each destination in **both**
its `authorized_keys` `permitopen` options and its sshd `Match User` `PermitOpen`.
The deployed allowlist includes nt1 and Cherry SSH only; adding another SSH node
requires explicitly extending both allowlists and validating/reloading sshd.
Do not replace these restrictions with unrestricted forwarding. This allowlist
is managed separately from profile generation; rendering cannot prove reachability.

Publish with the command below. Extra outbounds are appended to every manual
selector without changing nt1 defaults, routing or enrollment URLs. Refresh the
client's existing remote profile and explicitly select the trial node. On Linux,
start `sing-box-profile-update.service` to refresh immediately; Android/Windows
use the app's remote-profile refresh. An imported local JSON file does not update.
There is no automatic failover or evidence of connectivity from generation alone.

After a supervised replacement, edit the extra outbound's endpoint, credentials
and pinned host key in Vault, then republish. Before destroying a trial node,
remove its outbound and republish; clients still need to refresh/select nt1.
Omitting additional-node outbounds restores nt1-only exits (plus the workstation
hop when configured). OpenTofu does not change this Vault
file or publish on its own. See the [Cherry trial guide](../../infra/cherry-vpn/README.md).

The [`vpn_node` role](../../roles/vpn_node/README.md) can export a private JSON
list with SSH, Naïve and VLESS connections. Publish that list without modifying
the shared profile Vault:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/sing-box-configs/deploy.yaml \
  -e sing_box_extra_outbounds_file=infra/cherry-vpn/private/cherry-outbounds.json
```

The file entries are appended to any Vault `extra_outbounds`; duplicate tags are
rejected. Keep supplying the file on subsequent publishes, or copy its list into
the encrypted Vault and omit the flag. Publishing without either source removes
the trial entries. File-based inputs remain controller-local and must be
regenerated with the role after a controller/VM change. This is supervised
publication, not an automatically reconciled resource catalogue.

## Check whether a request is proxied

On Linux, watch the service log:

```sh
sudo journalctl -u sing-box -f
```

In another terminal, force a request through the Linux mixed listener (replace
this hostname with the one you want to check):

```sh
curl --noproxy '' -x http://127.0.0.1:12334 -I https://jellyfin.akorz.duckdns.org/
```

Look for the corresponding `outbound/direct[direct]` connection: it means sing-box
connected directly, not through the remote proxy. `outbound/vless[...]`,
`outbound/naive[...]` or `outbound/ssh[...]` means it was proxied. Android/Windows
clients expose equivalent connection logs in their UI. For TUN clients, also
check a normal browser request; explicitly using an HTTP proxy supplies the
hostname and does not test whether TUN sniffing can identify it.

## Deploy from another machine

Clone the repository including `secrets.vault.yaml`. Install Ansible and a
Naïve-enabled sing-box 1.14+ core, and provide:

- Inventory with `remote_workstation` and `remote_pi` (the current `hosts` file is
  ignored by Git; copy it securely or supply your own with `-i`).
- SSH access and sudo privileges for the target hosts as required by the playbook.
- The existing Vault password, supplied through a private `.ansible_pass` file
  (mode 0600), `--vault-password-file /secure/path`, or `--ask-vault-pass`.

Do **not** commit the Vault password, plaintext credentials, or `private/`.
`secrets.vault.yaml` contains encrypted JSON (valid YAML). Its credentials and
platform tokens are shared deployment state; editing it changes all future
publishes. Use a trusted editor without plaintext swap/backup files:

```sh
ansible-vault edit --vault-password-file .ansible_pass \
  playbooks/sing-box-configs/secrets.vault.yaml
```

Generated files in `private/` can be recreated on each machine. Decrypted inputs
reach the generator through stdin, not command-line arguments or an input file;
the Ansible task uses `no_log`. Linux enrollment also reads its URL from Vault,
so it does not require a previous deployment or a local `private/urls.json`.

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
Edit `secrets.vault.yaml` with `ansible-vault edit` for server/credential changes,
then rerun the publish playbook. If a separate server playbook changes proxy
credentials, update this Vault file to match before publishing. Merely editing
a source file does not publish it automatically.
The original `android.json` and `win-all-proxy.json` are kept privately for reference,
ignored by Git, and are not the ongoing source of shared connection credentials.

Generate/check locally without deploying:

```sh
set -o pipefail
ansible-vault view --vault-password-file .ansible_pass \
  playbooks/sing-box-configs/secrets.vault.yaml | \
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
forward this port through the router. The workstation's edge Caddy proxies to this
local HTTP listener. Public clients must use HTTPS.

Only exact token/platform paths and GET/HEAD are served. Missing/wrong tokens,
directory requests and other files return 404. Responses use `Cache-Control: no-store`.
Hosting request logs are disabled; edge Caddy structured logs redact request URIs and
headers to avoid leaking enrollment URLs during reverse-proxy errors.
Do not enable unfiltered access/debug logging for this endpoint.

The deployment uses the `remote_workstation` inventory alias for both hosting and
edge Caddy (`/srv/deploy/caddy`). Caddyfile changes are staged and validated before
activation, with rollback on reload failure. Updates preserve its file bind mount;
a pre-existing stale mount is detected and repaired by recreating the router
container (brief HTTPS outage). The route and log redaction are also in
`playbooks/pi-caddy/Caddyfile` (legacy directory name) so a later full edge Caddy
deployment retains them. See `playbooks/pi-caddy/README.md` for the router cutover.

To rotate a leaked platform URL, use `ansible-vault edit` to replace its token in
`sing_box_secrets.tokens` with 64 random lowercase hex characters and republish.
Editing the generated `private/tokens.json` does not rotate the shared token. Re-enroll affected devices;
rerun `linux-client.yaml` for Linux. URL rotation stops future downloads but does
**not** revoke proxy credentials already downloaded: rotate those separately.
