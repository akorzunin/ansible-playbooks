# Remote sing-box profiles

Full Android, Windows and Linux profiles (also used on macOS) are served from the workstation through
`https://configs.akorz.duckdns.org`, with HTTPS terminated by the existing Pi Caddy.
Clients remember a stable private URL; republishing replaces its content, not its URL.
No subscription converter or management database is needed.

## Enroll devices

Private enrollment artifacts are generated in `private/` (ignored by Git, mode 0700):

- `urls.json`: paste the appropriate HTTPS URL into a **remote** profile in the client.
- `import-links.json`: `sing-box://import-remote-profile` links for compatible clients.
- `tokens.json`: generated copy of the shared Vault tokens, not their source of truth.
- `setup-links.json`: private, rerunnable Windows/macOS setup links. macOS shares the Linux token/profile.
- `setup-windows.ps1` and `setup-macos.sh`: rendered scripts containing private profile URLs; never share publicly.

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

Current Cherry publication: `cherry-ssh`, `cherry-naive`, `cherry-vless` and
`cherry-vless-via-naive` and `cherry-hysteria2` are available through the same private
URLs/tokens. `aurora-vless` is an additional manual option from the Aurora VLESS
connection, verified with an isolated HTTPS request on this workstation; UDP and
Android/Windows runtime behavior have not been tested. nt1 is blocked and has been removed from publisher credentials and
all generated direct/chained routes. All platforms default to `cherry-vless-via-naive`.
The initial fetched Linux profile passed six isolated direct checks (three protocols,
two HTTPS targets) with the Amsterdam node's egress. Later direct Cherry VLESS
checks failed at the REALITY handshake despite matching server credentials;
the identical VLESS settings passed through both SSH and Naïve carriers. This
suggests a direct-path problem, not a proven cause or a credential mismatch.
The Naïve chain passed 20/20 STUN replies, 10/10 HTTPS probes and 5 MB transfers
in both directions, exiting through Cherry. Real Discord voice testing is pending. This workstation was **not
enrolled** by user choice: its active local `ssh-via-workstation` fallback and
inactive updater timer remain unchanged. Refresh already-enrolled remote profiles
to see the new options; merely having these published does not enroll a local
JSON file or automatically switch protocols.

Each platform currently has one token, shared by devices using that platform.
For independent revocation per device, issue separate tokens before sharing with
additional people. Treat enrollment/import links as passwords, not public links.

## Connections and routing

All profiles use `secrets.vault.yaml`, an Ansible Vault-encrypted file tracked in
Git. `sing_box_secrets.connections` is now empty; Cherry credentials and the
workstation hop are stored in `sing_box_secrets.extra_outbounds`. The Vault also
stores the existing platform tokens in `sing_box_secrets.tokens` and the shared
selector default in `sing_box_secrets.default_outbound`. No controller-local
outbound files are needed, and a fresh controller never generates replacement tokens.

- Manual selection only through `proxy`; Auto/URLTest is removed because successful
  probes did not reliably predict usable connections on mobile networks.
- All platforms default to `cherry-vless-via-naive`, which carries both TCP and UDP
  through Cherry VLESS over Naïve. Other Cherry protocols remain manual choices.
- `cherry-ssh-via-workstation` reaches Cherry SSH through the workstation. It is
  TCP-only; `workstation-hop` is an internal transport, not a selectable exit.
  nt1's `ssh-via-workstation` route is no longer generated.
- Manual changes interrupt existing connections. Selector choices are not persisted
  by the core cache; restarting may restore the platform default.
- Proxied TCP and UDP follow the selected protocol. UDP/443 is no longer rejected.
  Direct Naïve and SSH do not provide UDP relay: select working VLESS, its Naïve
  chain, or Hysteria 2 for UDP applications. TCP fallback depends on the application.
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
- Clash API/group controls bind only to `127.0.0.1:9091`, with secret `admin`.
  Open <https://yacd.metacubex.one> and add `http://127.0.0.1:9091` with that secret.
  Only that HTTPS origin is allowed by CORS; private-network browser access is enabled.
  Allow the browser's local-network permission if prompted. The simple shared secret
  is intentional for a personal loopback-only API, not a security boundary against
  local processes. Never expose the controller on LAN/public interfaces.

The Cherry protocols all use **the same Cherry host**; switching between them is
not redundancy against a complete Cherry outage. `aurora-vless` uses a separate
endpoint and can be selected manually; there is no automatic failover.

## Discord-only Linux networking (opt-in)

An HTTP/system proxy does not capture Discord's WebRTC UDP. `sb test` uses its
own UDP-capable SOCKS probe; a passing result alone does not fix the application.
The separate `discord-vpn` launcher uses the installed `/usr/bin/vesktop` client
and captures **only Vesktop and its children**:

```text
Vesktop → namespace gVisor TUN → VLESS/REALITY over wlan0 → dyn1 → Internet
```

Only the TUN and its routes are created in the `discord-vpn` network namespace
(sing-box 1.14+). The separate core and its outbound sockets stay in the host
namespace. No host default routes, forwarding, NAT, global TUN or changes to the
main sing-box service are needed. The single VLESS outbound and its bootstrap
DNS (UDP to `1.1.1.1`) bind to `wlan0`; no Naïve or SSH carrier is involved.
Application DNS uses TCP to `1.1.1.1` through VLESS, independently of the UDP
relay. Voice UDP explicitly uses XUDP: disabling it causes the Vision server
to reject UDP with a flow mismatch. The namespace uses gVisor on sing-box 1.14;
retest the replacement TUN stack before upgrading to 1.15. Earlier chained
trials passed short probes but later stalled during real app startup; probe
success alone is not application verification.
There is no wired or direct fallback. Connect Wi-Fi before launching; if it
loses connectivity, Vesktop loses connectivity rather than switching to wired.
The outbound/bootstrap use routing mark `0x2024`, matching the main host
sing-box TUN's bypass mark; keep these in sync if that mark changes. Host
routing, the wired default, other apps and the main sing-box service stay unchanged.
DNS returns IPv4 results only: the
exit's IPv6 TLS connections to Discord voice endpoints fail, leaving Chromium
stuck connecting instead of retrying IPv4. Restore dual-stack DNS only after
IPv6 egress passes TLS and UDP checks. Host DNS and routing remain unchanged.
UDP-over-TCP can stall under packet loss; passing STUN probes is not a
voice-quality guarantee.

Install from the Cherry worktree after restoring its private client export:

```sh
ansible-playbook -i localhost, --vault-password-file .ansible_pass \
  -e sing_box_extra_outbounds_file="$PWD/infra/cherry-vpn/private/cherry-outbounds.json" \
  playbooks/sing-box-configs/linux-discord.yaml
```

This validates the profiles and installs root-only credentials in
`/etc/sing-box-discord/config.json`, an opt-in service, and the launcher/menu
entry. It does not publish profiles, enroll the host, start Vesktop or enable
boot-time startup. Vesktop must already be installed. Rerun after credential
rotation; the dedicated config is a snapshot, not an automatically refreshed
subscription. The private Cherry export
is created by the `vpn_node` role and is not stored in Git.

Quit existing Vesktop instances, then run `discord-vpn` as your desktop user
(or choose **Vesktop (Wi-Fi VPN)** from the menu). The launcher checks that
`wlan0` has a default route and tunnel DNS works before starting the GUI.
The command and service retain
the `discord-vpn` name. Sudo is required to start/join the namespace; Electron
itself runs as your normal user, not root. The ordinary Discord and Vesktop
launchers remain unchanged. Do not run ordinary Vesktop and VPN Vesktop
concurrently: Electron can forward a second launch to the already-running instance.

The installed 7.2.11 kernel supports the namespace TUN. Direct Wi-Fi VLESS
with TCP DNS loaded the real Vesktop interface during repeated checks. With
XUDP enabled, native UDP/STUN replies passed. Host routes/rules and the wired
default remained unchanged. Real voice audio and long-term stability still
need user verification. The ordinary Vesktop launcher does not join the VPN
namespace. Diagnostics:

```sh
sudo journalctl -u discord-vpn.service -n 30 --no-pager
sudo ip -n discord-vpn route show table all
sudo ip netns exec discord-vpn curl --noproxy '*' -I https://www.gstatic.com/generate_204
sudo systemctl stop discord-vpn.service  # stop after quitting Discord
```

Stopping the service removes the namespace name/TUN; running namespace apps
lose connectivity rather than falling back directly. For removal, stop it,
then delete `/etc/sing-box-discord`, `/etc/netns/discord-vpn`,
`/etc/systemd/system/discord-vpn.service`, `/usr/local/bin/discord-vpn` and
`/usr/share/applications/discord-vpn.desktop`, then `sudo systemctl daemon-reload`.

## Additional VPN nodes

Optionally add `sing_box_secrets.extra_outbounds` to `secrets.vault.yaml`: a list
of complete sing-box outbound objects for VPN nodes. The `connections` mapping
may contain any subset of `vless`, `naive` and `ssh`, including an empty mapping
when retiring the original server. Every outbound needs a unique, nonempty `tag`
that does not collide with another connection or `auto`/`proxy`/`direct`.
`default_outbound`, when set, must name a selectable outbound (including derived
chains); otherwise the first selectable entry is used. Empty selectors are rejected.
The installed sing-box core validates all platforms before any local profile
is replaced. Keep private keys/passwords in Vault, not templates or command-line
arguments. SSH outbounds must pin the independently verified server `host_key`;
only distribute an unprivileged tunnel key, never an administrator key.

For each extra `<node>-vless` with a matching `<node>-naive` carrier, generation
also derives `<node>-vless-via-naive` with identical VLESS credentials and a Naïve
`detour`. Removing either connection removes the derived choice; update
`default_outbound` too if it names that chain. Generated tags must be unique. The
carrier only needs TCP CONNECT, not native UDP support.

The Vault also contains a pinned `workstation-hop` SSH outbound in `extra_outbounds`.
When it is present, generation clones each non-detoured SSH exit (including nodes
supplied through `--extra-outbounds-file`) as `<tag>-via-workstation`, preserving
its credentials and host-key pin and adding `detour: workstation-hop`. The hop
itself is omitted from the selector. Generated tags must not collide with supplied
tags. Removing `workstation-hop` removes the generated chained options.

The workstation's `sing-box-hop` account must allow each destination in **both**
its `authorized_keys` `permitopen` options and its sshd `Match User` `PermitOpen`.
`workstation-hop.yaml`, included by the publish playbook, configures both allowlists
from the validated generated Linux profile's direct SSH exits (currently Cherry
only). It uses the existing `workstation-hop` outbound and
`workstation_ssh_public_key` in Vault, with a dedicated forwarding-only account:
no shell, commands, PTY, agent/X11/Unix-socket or reverse forwarding. The complete
sshd configuration is validated before reload. Generate profiles before running
this playbook separately. Do not replace these restrictions with unrestricted
forwarding; rendering cannot prove reachability.

Publish with the command below. Extra outbounds are appended to every manual
selector without changing routing or enrollment URLs. Refresh the
client's existing remote profile; the configured default applies on restart.
Explicitly select a different connection if needed. On Linux,
start `sing-box-profile-update.service` to refresh immediately; Android/Windows
use the app's remote-profile refresh. An imported local JSON file does not update.
There is no automatic failover or evidence of connectivity from generation alone.

After a supervised replacement, edit the extra outbound's endpoint, credentials
and pinned host key in Vault, then republish. Before destroying a trial node,
publish a working replacement and update `default_outbound` before removing the
old outbounds. Clients still need to refresh. There is no nt1 fallback, and
publishing without selectable exits fails without replacing existing profiles.
OpenTofu does not change this Vault file or publish on its own. See the [Cherry trial guide](../../infra/cherry-vpn/README.md).

The dynamic-node flow also exports `cherry-hysteria2` (UDP/443, Brutal) alongside
SSH, Naïve and VLESS. It remains an additional manual choice, with existing defaults
unchanged; no automatic failover or publication is introduced.

The [`vpn_node` role](../../roles/vpn_node/README.md) can export a private JSON
list with SSH, Naïve and VLESS connections. Publish that list without modifying
the shared profile Vault:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/sing-box-configs/deploy.yaml \
  -e sing_box_extra_outbounds_file=infra/cherry-vpn/private/cherry-outbounds.json
```

The file entries are appended to any Vault `extra_outbounds`; duplicate tags are
rejected. Current Cherry entries already live in Vault: publish **without** this
flag unless importing a different node. Keep supplying the file on subsequent publishes, or copy its list into
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

This generates and validates all three profiles on the controller, configures the
restricted workstation SSH hop, publishes profiles atomically on the workstation,
validates static hosting, adds/reloads the Pi route,
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

## Windows and macOS manual setup/refresh

Publish first, then securely give the user the corresponding link from
`private/setup-links.json`. No Vault password or repository checkout is needed on
client machines. The link downloads executable code containing a private enrollment
URL: trust the hosting endpoint, treat the link as a password, and inspect the script
before running it if desired. Source scripts with `__PROFILE_URL__` are templates;
use the **published** links, not raw GitHub source links.

On Windows 10/11 (x64/ARM64), open **PowerShell as Administrator**, replace the placeholder
with the private Windows setup link, and run:

```powershell
& ([scriptblock]::Create((curl.exe --noproxy '*' --proto '=https' --fail --silent 'PASTE_WINDOWS_SETUP_LINK' | Out-String)))
```

On macOS (Apple Silicon/Intel), open Terminal as your ordinary desktop user
(**not** sudo), replace the placeholder with the private macOS setup link, and run:

```sh
setup=$(mktemp)
curl --noproxy '*' --proto '=https' -fsS 'PASTE_MACOS_SETUP_LINK' -o "$setup" && /bin/bash "$setup"
rm -f "$setup"
```

**Rerun the same command/link whenever a new config is wanted.** There is no polling
or scheduled config pull. Each run fetches the current profile directly, validates it
with `sing-box check`, and restarts the managed instance, even if the file is unchanged.
Download/validation failures retain the current config; immediate startup failures
restore previous files and attempt to restart the previous instance. The short startup
check only checks process liveness, not connectivity.

If no core is installed, setup installs the pinned official **1.14.2** release after
SHA-256 verification (Windows includes `libcronet.dll`). A core on `PATH` is reused;
Windows copies it and any adjacent Cronet DLL into its protected directory. Existing
GUI applications/services are **not** migrated or overwritten: quit/disable them
before enrolling to avoid competing listeners/routes. Reused cores must support
Naïve, SSH, TUN (Windows), and Clash API. Incompatible cores fail validation; upgrade
them yourself, or remove the managed `core` directory to let the next setup reinstall.
The scripts do not automatically upgrade the core on each refresh.

- Windows stores credentials/core in administrator/SYSTEM-only
  `%ProgramData%\\sing-box-remote`. Task Scheduler's `sing-box-remote-profile` runs the
  core as SYSTEM now and at boot. The Windows profile retains its system-wide TUN.
- macOS stores credentials/core/logs in the private
  `~/Library/Application Support/sing-box-remote` directory and installs the user
  LaunchAgent `io.github.akorzunin.sing-box-remote`, running now and at login.
  It uses the **unchanged Linux profile**, with HTTP/SOCKS at `127.0.0.1:12334`:
  configure your apps or macOS HTTP/HTTPS proxy settings to use it. No TUN, system
  proxy changes or root privileges are added on macOS. An app's own bundled core
  outside `PATH` is not detected.

To stop/uninstall, disable/delete the Windows task in Task Scheduler and remove its
managed directory. On macOS, run
`launchctl bootout "gui/$(id -u)/io.github.akorzunin.sing-box-remote"`, then remove
`~/Library/LaunchAgents/io.github.akorzunin.sing-box-remote.plist` and the managed
directory. Undo any manually configured macOS proxy settings as well.
Native Windows/macOS runtime testing is still required; Linux tests simulate the
macOS commands and do not prove OS-specific task/LaunchAgent behavior.

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

Only exact token/platform profile paths, Windows setup under the Windows token,
macOS setup under the Linux token, and GET/HEAD are served. Missing/wrong tokens,
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
