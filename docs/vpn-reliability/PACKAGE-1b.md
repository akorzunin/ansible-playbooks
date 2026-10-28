# Package 1b — DNS diagnostic and launch review

Status: **Package 1b complete; STOP at review gate**. The user approved the
exact launch/probe plan, then explicitly approved one repeat after the first
worker was cancelled before gate release (zero probes). The repeat completed.
No endpoint deployment, resolver migration or sustained runner is authorized.
This document does not authorize endpoint deployment or resolver migration.

## Controller review

Accepted for the stated short direct-DNS diagnostic and locally corroborated
worker-isolation scope. Controller reviewed source, tests and this sanitized
report; no live probes were repeated and private raw artifacts were not reread.
All 32 vpn-probe tests passed independently on review; repository lint reproduced
the 13 unrelated YAML violations recorded below. No blocking source-review
finding for this approved bounded experiment.

- The observed YouTube UDP/53 path is unsuitable for these lookups; TCP/DoH/DoT
  produced usable answers in this window. No ISP attribution or sustained
  availability is established. DoH/DoT remain candidate bootstrap mechanisms,
  not a selected production resolver or permission to migrate DNS.
- Local underlay exemption is accepted with its missing remote-observer limit;
  preserve raw `route-unverified` records and the separate context assessment.
  Revalidate rules/identity for future runs. This launch's approval does not
  cover VPN cores, new targets or longer workloads.
- libc/NSS success does not repair or qualify UID-1000 application DNS. VPN DNS,
  tunnel bootstrap, CONNECT/application resolution and media/voice remain pending.
- No second-resolver/EDNS follow-up is required merely to advance. Next is
  Package 2 endpoint/deployment implementation and offline tests, stopping before
  deployment for exact TLS/listener/firewall/resource/teardown review.

Historical proposal text below is retained for provenance; the completed live
results and this controller review supersede its earlier pending-evidence wording.

## Scope and current unprivileged observations

- systemd 262 and `systemd-run --pipe/--wait/--collect` are available. DynamicUser,
  LoadCredential and sandbox properties are proposed below; runtime acceptance
  by the service manager is still unverified until the approved launch.
- Production sing-box and its updater timer are active. The TUN and UID-related
  policy rules still exist. There is now an additional priority-1 policy table
  compared with the inventory; it must be included in review, not ignored.
- No IPv6 default was observed. AAAA **DNS records over IPv4** are still tested;
  no IPv6 transport qualification is implied.
- The proposed worker name is absent from the local passwd file. Never accept
  a pre-existing unit/account or a worker matching UID 0, 946 or 1000.
- Approved privileged read-only inspection, gate-held launches and the single
  approved live DNS batch have now run. No remote SSH, cache flush, production
  service restart, permanent account creation or production changes occurred.
  Concurrent unrelated workspace edits and an external commit were preserved.

## Diagnostic and finite live-probe request

New standalone `playbooks/vpn-probe/dns_diag.py`; existing tools are unchanged.
It uses Python stdlib DNS wire framing, sockets, CA-verified TLS and HTTP/1.1.
It is not a recursive resolver and does not perform DNSSEC validation. AD is
recorded, not trusted as authentication. A received UDP/TCP source address is
not proof against interception or of ISP attribution.

The proposed first plan (private stdin, not URL/credential argv):

```json
{
  "resolver": {
    "alias": "resolver-one",
    "ipv4": "1.1.1.1",
    "tls_name": "cloudflare-dns.com",
    "doh_path": "/dns-query"
  },
  "names": [
    {"alias": "youtube", "name": "youtube.com", "expect": "positive"},
    {"alias": "positive", "name": "example.com", "expect": "positive"},
    {"alias": "negative", "name": "vpn-dns-control.invalid", "expect": "nxdomain"}
  ],
  "edns": false
}
```

- Sequential UDP/53, TCP/53, DoH POST/443 and DoT/853: 3 names x A/AAAA x
  4 modes = **24 explicit queries**, RD=1, no EDNS, no DO/CD, no retries.
  UDP never falls back to TCP, including truncated responses. Paired queries
  have identical settings except transaction IDs and transport framing.
- Repeat youtube A over DoH and DoT after a 5 s pause: **2 more queries**.
  This is a short temporal reachability check, not sustained availability.
- **8 libc/NSS calls**, each in a bounded child: 3 names x 2 families, plus
  the encrypted-resolver hostname x 2 families. These may use local NSS/cache/
  forwarding and produce multiple upstream packets; explicit-query counts are
  not claims about total wire packets. No cache flush or resolver replacement.
- All explicit connections use IPv4. Encrypted bootstrap is the reviewed literal
  IP independently of libc DNS; SNI, hostname/CA verification and Host remain
  `cloudflare-dns.com`. No certificate bypass, redirect, proxy environment,
  alternate resolver, family fallback or plaintext fallback.
- Each whole explicit operation and libc child has a **4 s deadline**; 250 ms
  spacing after explicit requests. Gate wait <=90 s, worker cgroup <=300 s,
  stop <=5 s. One worker, <=8 tasks, 128 MiB RAM, 4 MiB output-file ceiling.
  At most 65535 DNS bytes per explicit response; the normal private output should
  be far smaller than the 4 MiB ceiling. Estimated application traffic <2 MiB
  for explicit DNS, plus TLS/NSS/transport overhead (budget estimate <5 MiB,
  not a measured network hard cap). No remote VPN host traffic is expected.
- Manifest/ready, samples and terminal completion records are flushed JSONL.
  Private samples preserve wire query/response, RCODE, all flag bits, TTLs,
  answer/authority/additional RDATA, decoded A/AAAA/CNAME/SOA, socket endpoints,
  timing, TLS/HTTP and stage-specific errors. Malformed DNS wire is retained.
  Raw exception messages are never printed. NOERROR/NODATA, truncation and
  wrong-control responses are not usable-answer successes. Negative-control
  agreement is separate from positive resolver usability.
- VPN DNS, VPN-server bootstrap and CONNECT/application destination DNS are
  explicitly **not run pending an approved isolated core**, not inferred from
  the active selector or a resolver's familiar IP. No tunnel secrets are needed.

Only if this first result leaves ambiguity: propose a separately approved
8-query follow-up, youtube A/AAAA paired UDP/TCP with EDNS=1232 at the original
resolver, then the same non-EDNS pairs to a reviewed second resolver. That
follow-up is **not part of the approval requested here**.

## Exact proposed privileged procedure — approval required

Run from the repository root. The first approved attempt executed preparation,
inspection, gate-held launch and cleanup, but did not release the probe gate.
The explicitly approved repeat executed all stages below, with the corrected
lease-countdown comparison. These are now reproduction instructions, not fresh
approval to repeat the probes.
`RUN` is a newly created controller-owned 0700 directory outside the repository.
The only worker-writable areas are its private temporary directories and the
already-open private stdout file; no shared production/home state is accessible.
No permanent account, StateDirectory or worker-owned retained files are needed.
The controller keeps ownership of output after the dynamic identity disappears.

### 1. Controller preparation (unprivileged)

```sh
umask 077
RUN=$(mktemp -d /tmp/vpn-dns-1b.XXXXXXXX)
printf '%s\n' "$RUN"  # private local location only; do not publish raw files
# Write the exact JSON above to "$RUN/plan.json", mode 0600.
# Record source hash; stage only this reviewed diagnostic, never the repository.
sha256sum playbooks/vpn-probe/dns_diag.py > "$RUN/source.sha256"
test "$(systemctl show vpn-dns-1b.service -p LoadState --value)" = not-found
```

Record resolver/NSS provenance privately before/after: file contents and metadata
of `/etc/resolv.conf`, `/etc/nsswitch.conf`; NetworkManager/resolved activity;
production sing-box PID/start time, config file metadata (not contents), updater
state, link/address state and complete IPv4/IPv6 rules/routes. Do not contact the
Clash API, fetch profiles or read subscription URLs. Do not run ordinary-user
network probes as a preliminary check.

### 2. Read-only privileged baseline, then gate-held worker

```sh
sudo -n nft -j list ruleset > "$RUN/nft-before.json"
sudo -n iptables-save > "$RUN/iptables-before.txt"
sudo -n ip6tables-save > "$RUN/ip6tables-before.txt"
sudo -n tc -j filter show dev enp12s0 ingress > "$RUN/tc-ingress-before.json"
sudo -n tc -j filter show dev enp12s0 egress > "$RUN/tc-egress-before.json"
# Record nft/iptables versions; inspect any legacy backend or other active
# tunnel/filter attachment too. Unknown interception means route-unverified.
sudo -n mkdir -m 0755 /run/vpn-dns-1b
sudo -n install -m 0600 playbooks/vpn-probe/dns_diag.py /run/vpn-dns-1b/source.py
sudo -n systemd-run --unit=vpn-dns-1b --wait --pipe --collect \
  -p DynamicUser=yes -p User=vpn-dns-1b -p SupplementaryGroups= \
  -p LoadCredential=diagnostic:/run/vpn-dns-1b/source.py \
  -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
  -p PrivateDevices=yes -p PrivateNetwork=no -p ProtectProc=invisible \
  -p CapabilityBoundingSet= -p AmbientCapabilities= \
  -p NoNewPrivileges=yes -p RestrictSUIDSGID=yes -p RestrictNamespaces=yes \
  -p LockPersonality=yes \
  -p 'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK' \
  -p UMask=0077 -p MemoryMax=128M -p MemorySwapMax=0 -p TasksMax=8 \
  -p RuntimeMaxSec=300 -p TimeoutStopSec=5 -p KillMode=control-group \
  -p LimitFSIZE=4194304 -p StandardError=null \
  /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  /usr/bin/python -I /run/credentials/vpn-dns-1b.service/diagnostic \
  --gate /run/vpn-dns-1b/go \
  < "$RUN/plan.json" > "$RUN/events.jsonl" 2> "$RUN/launcher.log" &
LAUNCH_PID=$!
```

Gate **must remain absent** until the ready record is received and reviewed.
Within its 90 s wait, inspect the unit's actual MainPID, UID/GID/groups,
capabilities, NoNewPrivs, cgroup, systemd sandbox properties and network namespace
with `systemctl show` and root read-only `/proc/<MainPID>/{status,cgroup,ns/net}`.
Compare to ready evidence and the controller/production namespace. Require a
new unprivileged UID, no groups beyond its own dynamic primary group, zero
capability sets and no-new-privileges. DynamicUser support is established only if this launch succeeds.

For the actual worker UID, inspect all hooked nft output chains/jumps, sets,
marking/NAT and policy rules, including priority 1 and 32768. Establish how the
noncaptured UID reaches the underlay rather than relying on main-table lookup.
Use `ip -j route get 1.1.1.1 uid <worker-uid> ipproto udp dport 53` and the same
TCP lookups for ports 53/443/853; save privately. Inspect the local resolver's
route too (its private address is obtained from resolv.conf, never pasted).
Use root `ss -H -ntup` snapshots filtered locally to the worker PID/UID during
probes; DNS sample records also retain actual local/peer sockets. No packet
capture is proposed. No receipt endpoint exists, so remote observer evidence
will remain unavailable. NSS forwarding provenance may remain unknown even if
worker-socket routing is established.

If the identity, sandbox or relevant rule exemption cannot be established,
**do not release the gate**. Stop only this unit, retain an incomplete report,
and return the limitation. Do not fix production rules as a shortcut.

### 3. Release only after inspection; watch for changes

```sh
sudo -n touch /run/vpn-dns-1b/go
wait "$LAUNCH_PID"  # nonzero exit is evidence, never discard partial JSONL
```

While waiting, take bounded 1 s environment snapshots of interfaces, policy
rules/routes, production PID/start time, config metadata and timer state, plus
read-only privileged nftables snapshots. Compare semantic rules ignoring packet/
byte counters and normal DHCP address-lifetime countdowns, not just volatile
text. Preserve address identity, flags, scope and interface comparisons. Abort only the diagnostic
unit on material change; do not stop the production updater. Record actual
worker sockets with bounded `ss` snapshots. Store <=4 MiB watcher evidence and
<=16 MiB total private run artifacts, otherwise stop the diagnostic. Watcher
runs <=300 iterations and is local read-only, never a network probe.

Repeat the before snapshot commands after completion. Compare the active
production environment, not merely the repository. Any observed change or
unexplained interception invalidates route proof. Diagnostic code deliberately
emits `route-unverified`; only the controller's separate reviewed context
assessment can corroborate an underlay path. Do not relabel libc upstream
routing/provenance as proven merely because the explicit worker is exempt.

### 4. Cancellation, collection and cleanup (also approved as part of plan)

```sh
# On cancellation/failure/time/environment change; never stop any other unit:
sudo -n systemctl stop vpn-dns-1b.service
# Ignore only the known already-collected/not-loaded-unit case. Confirm no
# diagnostic cgroup/PID remains. Preserve launcher/partial records on failure.
sudo -n rm -f /run/vpn-dns-1b/go /run/vpn-dns-1b/source.py
sudo -n rmdir /run/vpn-dns-1b
```

Only remove the staging directory if it was created by this invocation and the
worker is stopped. Controller-owned output requires no root chown or widening
permissions and is retained privately for review. SIGINT/SIGTERM preserves a
cancelled terminal record when possible; cgroup stop kills/reaps only owned
children. SIGKILL/output-limit termination can leave incomplete JSONL: mark
incomplete/inconclusive, never complete or successful. Remove the specific
private `RUN` directory only after the operator no longer needs the evidence.
No production rollback should be necessary; nothing there is changed.

## Review gate and proposed DNS policy

Pending live evidence: do not select or migrate to a new resolver. Diagnose
libc/NSS separately from explicit transport and independently bootstrapped TLS.
A complete diagnostic can have no usable resolvers. NXDOMAIN over UDP and
NOERROR over TCP would demonstrate transport-dependent behavior only, not the
responsible network/operator. Do not demand identical CDN answers.

Later bootstrap policy should use an independently qualified underlay resolver
or maintained operator-approved IP-based tunnel controls with TLS/REALITY names
and verification retained. Never pin arbitrary observed DNS replies. Destination
DNS must be explicitly selected and qualified through each isolated route,
without implicit direct fallback or circular dependence on the failed tunnel.
A working DoH query alone does not configure CONNECT/application resolution.
These remain proposed design requirements, not production configuration changes.

## Approved live evidence — 2026-10-27, 18:03:22–18:03:36 UTC

Diagnostic completion: **complete**, 26 explicit attempts and 8 libc/NSS calls,
no dropped samples. Resolver usability: **transport-dependent**, not all passed.

| Name / type | Explicit UDP | Explicit TCP | Verified DoH | Verified DoT |
| --- | --- | --- | --- | --- |
| youtube.com A | NXDOMAIN, unusable | NOERROR, usable | NOERROR, usable | NOERROR, usable |
| youtube.com AAAA | NXDOMAIN, unusable | NOERROR, usable | NOERROR, usable | NOERROR, usable |
| example.com A / AAAA | NOERROR, usable | NOERROR, usable | NOERROR, usable | NOERROR, usable |
| negative control A / AAAA | Expected NXDOMAIN | Expected NXDOMAIN | Expected NXDOMAIN | Expected NXDOMAIN |

- YouTube UDP flags were `0x8583` (including AA), zero answer/authority records,
  TC=0, AD=0, approximately 6.2–6.3 ms. TCP flags were `0x8180`, four usable
  records for each type, approximately 25–29 ms. Flags do not authenticate the
  sender or establish which device/operator generated the response.
- DoH/DoT verified the CA and hostname with the explicitly approved bootstrap IP.
  Every encrypted positive query returned usable records; both encrypted negative
  controls returned expected NXDOMAIN. Initial operations were approximately
  98–151 ms; the later YouTube A repeats also passed (DoH 139 ms, DoT 96 ms).
  This brief window does not establish filtering resistance or long-term health.
- libc/NSS returned global-address answers for both positive names and the
  encrypted-resolver hostname, A and AAAA; the negative control returned
  `EAI_NONAME` (-2) in both families. Calls took approximately 51–57 ms.
  No `/etc/hosts` overrides for these names were observed. The original inventory's
  `EAI_AGAIN` was **not reproduced in this worker/window**; this is not evidence
  that UID 1000 or production application DNS has been repaired.
- System resolver provenance: one private IPv4 nameserver in a regular
  resolv.conf; NetworkManager active, systemd-resolved inactive. NSS hosts order
  was `mymachines resolve [!UNAVAIL=return] files myhostname dns`. No cache or
  upstream-forwarding inspection proves where this system resolver got replies.
  Local resolver content, NSS content and metadata were retained privately.

### Launch, route evidence, resource accounting and cleanup

- systemd accepted every proposed property. Runtime worker was a separate dynamic
  UID/GID, not 0/946/1000; supplementary-group configuration was empty and the
  process group list contained only its own primary group. All capability sets
  were zero, NoNewPrivs=1, seccomp active and proxy environment absent.
  Controller and worker shared the host network namespace as deliberately planned.
  Python was 3.14.8 / OpenSSL 3.6.5, newer than the Package 1 snapshot.
- All three sing-box output chains returned non-1000 UIDs before interception:
  TCP redirect, UDP marking and newly observed NFQUEUE prematching. Docker output
  DNAT required LOCAL destinations, not the approved resolver. The priority-1
  table held only local routes; the main underlay default preceded the late TUN
  fallback rule. Actual-UID UDP/53 and TCP/53/443/853 lookups used Ethernet.
  nft-backed IPv4/IPv6 iptables and complete nft rules were inspected; underlay
  ingress/egress tc filters were empty and no XDP attachment was reported.
- All explicit samples retained actual socket endpoints privately; the 1 s
  watcher additionally sampled one worker socket. Short-lived sockets can fall
  between watcher samples. No packet capture or remote receipt was available.
  This corroborates the **local underlay exemption**, not authenticated remote
  path/source attribution. Utility records intentionally retain
  `route-unverified`; the separate controller assessment records the local
  corroboration and missing remote evidence rather than overwriting raw records.
- Fourteen watcher samples and before/after checks found no material address,
  interface, policy route, semantic nft rule, config metadata, production
  PID/start-time or updater-state change. Packet counters and normal DHCP
  lifetime countdowns were excluded from equality checks. Production sing-box
  and updater remained active; neither was paused, restarted or modified.
- First attempt: the overly strict address comparison mistook the DHCP lease
  countdown for a change. It cancelled the worker before release, recorded a
  cancelled terminal event and sent **zero DNS probes**. Staging/unit cleanup
  completed. Only after explicit repeat approval was the corrected check used.
- Successful worker elapsed approximately 14.04 s, including the pause and
  pacing. Explicit DNS payload: 850 query bytes + 2412 response bytes. These
  exclude TLS/HTTP/TCP/IP overhead and libc resolver traffic. Observed shared
  Ethernet counters increased by 121487 received + 72695 transmitted bytes;
  they include unrelated traffic, are sampled rather than exact run boundaries,
  and must not be presented as per-diagnostic/provider billing totals.
- Private artifacts occupied approximately 275 KiB before the final local
  summary, well below limits. Output directories are 0700 and files 0600.
  Controller-owned JSONL survived DynamicUser teardown without chown. The unit
  is collected/not-found, MainPID=0, worker PID and diagnostic cgroup are gone;
  staging/release/credential directories are absent. No worker state, account,
  key, resolver setting or routing change remains.
- Raw private artifact location is available locally through the controller-owned
  mode-0600 `/tmp/vpn-dns-1b-controller-path` locator. It points to the successful
  run; the first cancelled run is retained separately. Do not commit or paste
  raw JSONL, context snapshots or socket mappings. These temporary artifacts are
  not durable archives; retain privately before /tmp cleanup if needed.

### Validation and handoff

Session-created/changed paths:

- `playbooks/vpn-probe/dns_diag.py` — bounded standalone DNS diagnostic.
- `playbooks/vpn-probe/test_dns_diag.py` — 16 deterministic offline tests covering
  paired settings, A/AAAA/CNAME/SOA, flags/controls/NODATA/truncation, malformed
  packets, UDP no-fallback, independent TLS bootstrap/hostname verification,
  DoH status/type/encoding/size rejection, redacted distinct failures, bounded
  libc, finite counts/completion with all failures, UID refusal and cancellation.
- `docs/vpn-reliability/PACKAGE-1b.md` — exact launch proposal and this review.

An external commit during the approval wait incorporated these previously new
files and the pre-existing workspace edits. This session made no commit and did
not reset/revert anyone's work. The launched diagnostic's SHA-256 still matches
current source. Existing `probe.py`, `check.py`, production profiles and the
controller's four source documents were not changed by this package.

Validation:

- `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s playbooks/vpn-probe
  -p 'test_dns_diag.py'`: **16 passed**. All `test_*.py` in that directory:
  **32 passed** at final validation (29 before concurrent external changes).
- Explicit `uvx prek run --files` for the three package paths and
  `git diff --check`: **passed**.
- `uvx prek run --all-files`: passed before the approval wait; final rerun
  **failed on 13 unrelated YAML violations**: indentation in
  `playbooks/nvidia_gpu_exporter/compose.yaml`, and comment spacing in
  `playbooks/transmission/compose.yaml` and `playbooks/wake-on-lan/compose.yaml`.
  Other hooks passed. These unrelated files were not changed to hide the failure.

Review decision remains with the user/controller. The initial UDP/TCP symptom
is reproduced; second-resolver/EDNS follow-up is **not run**, not silently
approved. VPN DNS, tunnel bootstrap, CONNECT/application resolution, IPv6
transport, sustained availability and media/voice qualification are **not run**.
No resolver migration follows from this result. The proposed independent
bootstrap/explicit per-route destination policy above remains unchanged.

Rollback: remove/revert only the three package paths if rejected, preserving
unrelated user changes and the external commit. Local privileged cleanup is
already complete. Delete only the explicitly identified private run directories
and locator after evidence retention/review; no production rollback is needed.
Stop here: no Package 2 endpoint or Package 3 sustained runner was implemented.
