# Package 1 — sanitized runtime inventory

Review gate: **stop here**. No deployment, sustained traffic, application test,
active-client change, route change, restart, publication or commit was performed.
The user approved bounded read-only SSH inspection of Cherry and nt1 in this
session. Observation window: 2026-10-26, approximately 20:07–20:16 UTC.
Addresses, host keys, account secrets, profile URLs and private mappings are
intentionally omitted. Aliases below are repository route/inventory identifiers.

## Evidence levels and corrections to PLAN.md

- **Current repository:** `infra/cherry-vpn/` now has 20 tracked files, including
  deployment/bootstrap source and tests. `playbooks/vpn-probe/` has four tracked
  files, including a working small-request observer and tests. The plan's
  “ignored artifacts/cache only” statements are obsolete. No state/plans/caches
  were read or decompiled during discovery.
- **Verified runtime:** Cherry is a distinct host from nt1. Published local
  generated profiles and the installed Linux config contain its three routes.
  The statement that all available routes share nt1 no longer applies to Cherry.
  The workstation hop alone still does not create a distinct exit.
- **Verified runtime:** the main Linux JSON is mixed-only, but the running service
  also loads a local JSON-with-comments fragment with a TUN and interception.
  The plan's “this machine has no TUN” assumption is false at runtime.
- **Verified runtime:** the selector currently reports `ssh`, not the historical
  `ssh-via-workstation` selection in the READMEs. The repository profile updater
  timer is inactive, but a different installed updater timer is active.
- Historical six-request Cherry successes and nt1 VLESS timeouts in READMEs are
  **repository reports**, not rerun measurements. No service qualification or
  present end-to-end tunnel availability is established by this inventory.

## Host identity and safe access

| Alias | Source / access | What was verified |
| --- | --- | --- |
| `cherry_vpn_test` | Existing `infra/cherry-vpn/private/inventory.yaml`, administrator key `private/ssh/admin`, dedicated `private/known_hosts` | Non-root `vpnadmin`, TCP 22, strict pinned host authentication, key-only direct SSH and noninteractive sudo succeeded. No ProxyCommand is configured. |
| `nt1` | Existing ignored `hosts` inventory; existing SSH identity and known-host entry | Strict known-host checking and key-only SSH succeeded. Sudo required the existing Vault-backed inventory password, decrypted only into controller memory and supplied on stdin. |

Both SSH invocations explicitly overrode `ansible.cfg`'s unsafe global
`host_key_checking = False`: `StrictHostKeyChecking=yes`, `BatchMode=yes`,
`ConnectTimeout=8`, no first-use acceptance, no host-key scan, no forwarding.
Cherry's private directory is 0700; inventory, pin file and administrator key
are 0600. The Vault password file is 0600. No inventory regeneration or
OpenTofu/provider API operation was needed. Identity is verified against existing
pins, not independently re-attested against a provider console in this session.

The Cherry inventory IP matches both IP-based client outbounds in its private
export. Its region/server identity are described as Amsterdam in the maintained
README; provider region, billing and remaining allowance were **not rechecked**.
Use the existing inventory to target this host, never copy an address from this
shareable report or use an administrator credential for tunnel tests.

## Verified capabilities (not throughput/UDP results)

| Route | Public port / outer transport | Runtime / authentication | Inner UDP |
| --- | --- | --- | --- |
| `cherry-ssh` | TCP 22 / SSH | Native SSH; exported client pins host key and uses restricted probe credential | Unsupported by this SSH outbound |
| `cherry-naive` | TCP 443 / TLS HTTP/2 CONNECT | Upstream server reports v2.11.7; image `vpn-node-naive:2.11.7-naive2`; TLS verification enabled client-side; TCP 80 also published for ACME | Not enabled; client has neither QUIC nor UDP-over-TCP |
| `cherry-vless` | TCP 8443 / REALITY, plain TCP, Vision | sing-box 1.14.4, Go 1.26.10, revision `c005f35300ce76427dc285481ec5695f5b179cd2`; client 1.14.2 | Configured capability, **not tested**; UDP would be carried over TCP, not native outer UDP |
| `ssh` (nt1) | TCP 22 / SSH | Existing pinned SSH outbound; administrator SSH works, probe forwarding not exercised here | Unsupported |
| `naive` (nt1) | TCP 443 / TLS HTTP/2 CONNECT, Caddy layer4 passthrough | Server reports v2.11.2; image `naiveproxy:v2.11.2-naive`; repository backend TCP 8444 | Not enabled; no client QUIC or UDP-over-TCP |
| `vless` (nt1) | TCP 16001 / REALITY, plain TCP, **no Vision flow** | Xray 25.10.15, revision `b69a376`, Go 1.25.3; client explicitly uses `packet_encoding: xudp` | Configured capability, **not tested** |
| `ssh-via-workstation` / `cherry-ssh-via-workstation` | Workstation SSH TCP 22123, then respective host TCP 22 | Present in installed config; explicit SSH detour; host-key pins present | Unsupported; intentionally nested controls, not direct-ISP baselines |

Cherry VLESS client and server agree on UUID, `xtls-rprx-vision`, allowed SNI,
short ID, port and derived REALITY public key. Its short ID has 16 hex characters;
its SNI/handshake target is `www.google.com`. Client uTLS fingerprint is `chrome`.
Packet encoding is omitted (installed-core default), not explicitly proven XUDP.

The relevant nt1 inbound and client also agree on UUID, empty flow, allowed SNI
(`google.com` client), short ID, port and derived public key. Both clients retain
TLS verification. Keys were compared locally/over authenticated SSH without
printing them; public keys were derived with OpenSSL from private bytes on stdin.
These comparisons remove obvious configuration mismatches; they do not prove
REALITY handshake reachability, valid time-dependent behavior or UDP relay.
The role's historical latest-Xray compatibility warning is not evidence that
this older running nt1 Xray is incompatible. No protocol tuning is justified yet.

### Resources / health snapshot

| Host / component | Verified ceiling or observation |
| --- | --- |
| Cherry host | Debian 13, kernel `6.12.86+deb13-cloud-amd64`, 1 CPU, 991160 KiB RAM, no swap; NTP synchronized |
| Cherry Naïve | 96 MiB hard memory, 128 PIDs, read-only root; about 25 MiB at idle; no current OOM flag, zero container restarts |
| Cherry VLESS | 128 MiB hard memory, 128 PIDs, read-only root; about 35 MiB at idle; no current OOM flag, zero container restarts |
| nt1 host | 1 CPU, 1083376 KiB RAM, no swap; NTP synchronized; shares host with application services |
| nt1 Naïve | 64 MiB hard memory, 64 PIDs; about 17 MiB at idle; no current OOM flag, zero container restarts |
| nt1 Xray parent container | `3x-ui`, 256 MiB reported by stats; about 88 MiB combined panel/core use at idle |
| nt1 front Caddy | 96 MiB hard memory, one container restart; cause/time not attributed |

Point-in-time flags are not historical proof of no OOM/reclaim or stable CPU
under load. No resource load was applied. Cherry publishes TCP 80/443/8443 on
wildcard addresses; SSH listens on 22. No native public UDP VPN listener was
observed. DNS-related 53/5355 listeners also exist; their scope/access was not
qualified. Docker nftables tables exist; neither provider firewall nor complete
host filtering policy was certified. The role explicitly does not install a host
firewall. Package 2 must review exact listeners and source restrictions.

Monitoring source: `node/nt1/services.deploy.yaml` includes `monitoring_client`;
its Telegraf template collects CPU/memory/network/disk and Docker metrics at 15 s,
with an explicit metrics source allowlist required by the role. A running
Telegraf 1.40.2 container was verified on nt1. Cherry has only its two VPN
containers, no observed Telegraf container. Prometheus ingestion/dashboard health,
host OOM history and retransmission/drop trends were **not verified**. Prefer
bounded SSH sampling of existing `/proc`/cgroup counters, not a new monitoring
service, for the later campaign.

## This Linux machine: the actual path

- sing-box **1.14.2**, linux/amd64, Go 1.27.1, CGO enabled, with Naïve, QUIC,
  uTLS, gVisor and Clash API build tags. curl **8.22.0** supports HTTP/2, HTTP/3,
  HTTPS proxies and IPv6. Python **3.14.7**, Ansible core **2.21.4**.
  `iperf3` is not on PATH. Client NTP reports synchronized.
- `enp12s0` is the up Ethernet underlay, MTU 1500, with the main IPv4 default
  through a private LAN gateway. Wi-Fi has no carrier. Docker/libvirt bridges
  exist. Only link-local IPv6 was observed on the underlay; no IPv6 default or
  route to a public IPv6 destination. IPv6 is **unavailable in this snapshot**,
  not a passed tunnel family.
- Environment `http_proxy` and `https_proxy` point to HTTP loopback port 12334;
  `no_proxy` is set (values withheld). sing-box's mixed listener is loopback-only.
  Selector read through the local Clash API was `ssh`; on-disk default is VLESS.
- The service runs as UID 946 and loads `-D /var/lib/sing-box -C /etc/sing-box`.
  Besides `config.json`, `00-local-udp.json` adds TUN `sing-udp`, MTU 1500,
  `auto_route`, `auto_redirect`, `include_uid: [1000]` and interface detection.
  `/proc` file descriptors confirm the running sing-box owns `/dev/net/tun`.
- IPv4 policy table 2022 contains split routes through `sing-udp`; priorities
  9000–9002 use marks 0x2024/0x2023, with further routing after `main`.
  nftables `inet sing-box` redirects TCP and marks UDP for UID 1000, bypassing
  other UIDs/private destinations/appropriate marked connections. A plain
  `ip route get` returning Ethernet therefore **does not prove no interception**.
- The local fragment bypasses TCP/ICMP, UDP DNS port 53, and UDP ports
  27000–27200 to direct; other UDP can follow the selected proxy. This is not a
  verified Discord route: the current SSH selection cannot relay that UDP.
  No leak claim or Discord acceptance is possible without application evidence.
- Kernel TCP route lookups for IP-based nt1/Cherry outbounds returned `enp12s0`.
  Hostname-based outbounds could not all be resolved: system `getaddrinfo`
  returned temporary failure (`EAI_AGAIN`, -3), also when repeated as UID 1000.
  `/etc/resolv.conf` is a regular file pointing to a private IPv4 resolver;
  NetworkManager is active, systemd-resolved inactive. NSS tries `resolve`
  before files/DNS. Exact resolver failure/forwarding upstream is **unknown**.
  No DNS settings or cache were changed. Runtime config has no explicit DNS
  servers; destination-vs-bootstrap resolution must be made explicit in tests.

### Configuration provenance and updater hazards

The three installed nt1 protocol objects match `sing_box_secrets.connections`
from `playbooks/sing-box-configs/secrets.vault.yaml` ignoring tags. That Vault has
**no** extra outbounds. Cherry's installed objects and generated private Linux
objects match `infra/cherry-vpn/private/cherry-outbounds.json` exactly. Thus
Vault alone currently cannot supply Cherry; the explicit private export remains
necessary. `cherry-test.json` contains loopback listeners 12340/12341/12342;
its multi-route/shared-process shape is not the proposed capacity-test isolation.
Offline `sing-box check` passed for it and the generated private Linux profile.
No isolated processes were started.

`sing-box-profile-update.timer` is inactive and `/etc/sing-box-profile.json` is
absent, consistent with no enrollment in the repository updater. However,
**`sing-box-update.timer` is active**, and its different service last failed
with `exit-code`; installed code is `/usr/local/libexec/sing-box-subscription.py`.
It invokes curl, configuration checking and service restart/rollback, without an
identified semantic connectivity check. No URL was read into the report and no
update was triggered. Its failure cause was not investigated. Do not pause or
repair it without approval; instead detect profile/process/rule changes and
invalidate a future run if the active environment changes.

Repository `generate.py` keeps manual selectors, DuckDNS and Russian destination
bypasses, direct remote rule-set fetches, and platform-specific TUNs on Android/
Windows. `update-linux.py` checks startup after two seconds, not connectivity.
Those inherited policies must not be copied into measurement profiles.
`naiveproxy/check.py` concurrently probes three routes and inherits a shared
routing base; `vpn-probe/probe.py` observes bounded small requests, not sustained
capacity. Preserve both tools; neither qualifies media or UDP.

## Isolation decision required at review

Controller review: the findings below are accepted as a snapshot, but the proposal
to reuse the production service UID is **not approved**. Follow the amended
`CONTRACT-v1.md`: propose a transient unprivileged worker, validate interception
exemptions, isolate credentials and obtain approval for the exact launch. Package
1b adds DNS baseline diagnosis before endpoint deployment. Historical observations
and the unexecuted proposal below are retained for provenance.

Do **not** call a normal UID-1000 direct request or isolated proxy an unnested
ISP test merely because curl ignores proxy variables. Proposed route-safe launch:
run the later test core **and direct curl** under an approved existing
non-intercepted unprivileged UID (for example the existing sing-box service UID),
with separate owned 0700 temporary state and 0600 configs. This needs a narrowly
reviewed privileged launch/ownership procedure, not a new account, a shared
service directory, a production restart, or a default-route change. It was **not
executed** here. Do not run the measurement core as root or reuse production state.

At each future run, verify UID, network namespace, complete policy rules,
nftables interception and actual sockets; corroborate with endpoint receipt and
outbound identity. Verify that every relevant interception rule exempts the
chosen UID and that no other host tunnel catches it. Kernel route lookups alone
are insufficient. Stop as `route-unverified` if that cannot be established.
Intentional workstation-hop tests must be explicitly labeled nested.

## Gate: unresolved needs and handoff

1. Review this inventory and `CONTRACT-v1.md`, including the noncaptured-UID
   launch proposal. No bypass/routing repair is authorized by this document.
2. Diagnose/recheck local DNS before hostname bootstrap or tests; preserve the
   observed failure. No current direct Internet or tunnel baseline is claimed.
3. Package 2 must propose the exact Cherry HTTPS/UDP endpoint, source restrictions,
   bounds and teardown **before deployment approval**. No controlled transfer/
   UDP endpoint is verified ready; no distinct controlled reference host has
   been identified. A same-host endpoint cannot measure Cherry Internet egress.
4. Recheck active selection, updater, interfaces and rules at campaign start;
   they differ materially from the historical notes. Qualify UDP separately.
5. Provider firewall/billing/allowance, handshake target reachability, actual
   certificate validation through a client, sustained behavior, real media,
   Discord, MTU under load and loss recovery remain **not run / unverified**.

Evidence commands included `git ls-files`, source reads, `sing-box version`,
`curl --version`, `ip -j link/addr/rule/route`, `systemctl show`, allowlisted
local Clash API reads, `/proc` owner inspection, sanitized `nft -j list ruleset`,
and bounded pinned SSH with read-only `docker inspect/stats/exec ... version`
and selected private-config comparisons. Raw inventory/config/log/error output
was captured locally and not echoed. One initial Cherry inspection script and
one nt1 controller helper failed before completing; corrected inspections passed.
These were tooling failures, not tunnel test failures.

## Validation and workspace handoff

- `python -m unittest discover -s playbooks/sing-box-configs -p 'test_*.py'`:
  17 passed; updater restart messages came from mocks, not real service actions.
- The same discovery command for `playbooks/vpn-probe`, `roles/vpn_node/tests`
  and `infra/cherry-vpn`: respectively 13, 6 and 16 passed (52 total).
- `uvx prek run --all-files`: passed all hooks. Also ran
  `uvx prek run --files docs/vpn-reliability/INVENTORY.md docs/vpn-reliability/CONTRACT-v1.md`
  because these new documents are untracked; all hooks passed.
- `git diff --check`: passed. No runner, deployment or route configuration was
  implemented; future command examples are proposals, not executed tests.

During validation, unrelated changes appeared in `infra/cherry-vpn/README.md`,
`monitoring.inventory.yml`, `node/nt2/README.md`, `playbooks/ws-logs/README.md` and
`playbooks/ws-logs/tests/test_monitoring.py`. These were not made by this package
and were preserved; the workspace is evidently not static. A tracked test
bytecode file regenerated by the focused tests was restored to its original
HEAD bytes. Recheck repository and runtime facts before the next package; this
inventory is a time-bounded observation, not a lock on external activity.

This package adds only `INVENTORY.md` and `CONTRACT-v1.md`. Rollback: remove those
two new documents if rejected. Preserve pre-existing staged `PLAN.md`/`PROMPTS.md`
and all unrelated edits, including `.gitignore` and `.ansible-lint`. No production
rollback is necessary; no keys, pins, retained private artifacts or diagnostic
processes were created. No commit was made.
