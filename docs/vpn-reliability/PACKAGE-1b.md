# Package 1b — DNS diagnostic and launch review

Status: **implementation/offline validation in progress; privileged inspection,
launch and live probes NOT RUN or approved yet**. Stop at this package's gate.
This document does not authorize endpoint deployment or resolver migration.

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
- No privileged commands, live DNS queries, remote SSH, cache flush, service
  restart, account creation or production changes have been performed here.
  Concurrent unrelated workspace edits are present and must be preserved.

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

Run from the repository root. No shell command below has been executed yet.
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
new unprivileged UID, no supplementary groups, zero capability sets and no-new-
privileges. DynamicUser support is established only if this launch succeeds.

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
byte counters, not just text with volatile counters. Abort only the diagnostic
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

Validation, sanitized approved results, limitations and final changed-path list
will be appended here before stopping. Package 2 deployment and Package 3's
sustained runner are deliberately absent.
