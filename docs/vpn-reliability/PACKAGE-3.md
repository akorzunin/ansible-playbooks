# Package 3 — bounded TCP runner, local validation only

**Package 3r reviewed and accepted for bounded live-smoke preparation.**
Execution still requires explicit preflight/source/lease/worker/load approval.
See controller review below; original findings and local results are retained.
No lease preparation against real host material, deployment, SSH, privileged
worker, firewall/source change,
external request, production change, commit or publication occurred. All network
tests used a temporary **127.0.0.1 TLS fixture**. Existing Package 2/2b and user
changes were preserved.

## Controller review after Package 3r

Controller reviewed the corrective source/tests and revised live proposal, then
independently reran 75 probe + 28 reference tests (103 total) and repository hooks:
all passed. No live command or private evidence read occurred during review.

R1 is accepted as corrected: poll/queued-IO/EOF evidence precedes cancellation,
earlier request deadlines retain precedence, natural failures/raw exits/partial
bytes survive, and genuine parent-owned SIGTERM remains distinguishable. Boundary
regressions include real subprocess and real loopback TLS/curl tests. R2's revised
container namespace/NAT/source derivation and exact /32 approval plan is accepted
as a proposal, not an established source value or enforcement result.

Next is Package 3b bounded live smoke using the proposal below. Obtain explicit
approval for read-only preflight first, then exact endpoint-facing /32, one fresh
lease/install, isolated workers, tiny workloads, collection and teardown. Stop
for inconclusive source/routing/policy, unexpected failure or missing evidence;
never broaden sources, retry directly or change production as a shortcut.

Maximum client-read bodies remain 19 MiB over fresh 5 s, continuous 5 s and
segments 12 s, sequentially on cherry-vless. This is runner commissioning, not
performance qualification. Inspect rows/artifacts rather than exit 0 alone:
raw route-unverified is expected until a separate controller assessment records
actual UID/underlay/outbound/receipt corroboration. Preserve the raw outcome.
Require no unexpected request failure, valid complete fresh objects, positive
continuous bytes with truthful cancellation provenance, and at least one complete
hash-verified segment; censored final partial work remains explicitly partial.
Missing evidence or a short-window failure is not proof of DPI/protocol failure.
No endpoint serving-capacity, direct baseline, DNS, UDP or media claim follows.

## Original controller review — held before Package 3r

Controller independently reran 66 probe + 28 reference tests (94 total) and
repository hooks: all passed. Source/proposal review nevertheless found a
blocking deadline-classification defect. No live commands or private evidence
reads were performed during review.

**R1 — preserve naturally failed transfers at the planned deadline.**
`Runner.pump()` calls `abort('completed-window')` at the workload deadline without
checking whether curl has already exited. `Transfer.finish()` gives this reason
precedence over a natural nonzero curl exit. A deterministic no-network check
reproduced both steps: an already-exited curl 18 was assigned planned cancellation;
a transfer with valid HTTP 200/Content-Length 100, only 3 received bytes and curl
18 then yielded `outcome=completed-window`, `error=null`. Curl 18 represents
truncation, not evidence of runner-owned normal cancellation. This can hide a
failure near the deadline; existing passing tests do not cover this boundary.

Correct the smallest relevant accounting path and add regressions for natural
EOF/errors already observable before cancellation, genuine parent-owned planned
cancellation, timeout and malformed/error responses. Preserve termination/error
provenance; ambiguous races must remain explicit rather than erasing an observed
failure. Expected runner SIGTERM is not itself a transport failure. Keep partial
bytes, failed samples and planned windows; do not fix this by disabling deadlines,
removing raw curl exits or accepting every deadline-adjacent failure.

**R2 — amend the proposed live endpoint source plan.** The destination/bind IP and
public VPN egress IP are not necessarily the source seen by a native endpoint
when a containerized exit connects to its own host. A container/bridge address
may reach INPUT without Internet-egress masquerading. Preflight must establish
the current selected core's network mode, namespace/route/NAT and endpoint-facing
source. Propose that exact minimal /32 for explicit approval; do not automatically
broaden it or treat policy refusal as a VPN failure. This is a proposal correction,
not permission for remote inspection, new sources or probes now.

Next is Package 3r: implement/test R1 and correct R2's written proposal, then return
for review. No new lease, worker launch or live smoke is approved. Other Package 3
implementation remains a candidate, not commissioned. Historical local results
below are retained; they do not invalidate the independently reproduced defect.

## Package 3r — local corrections

R1 and R2 are corrected locally; **the live gate remains held**. Only these paths
were changed by this corrective session:

- `playbooks/vpn-probe/screen.py`: deadline/error attribution and request provenance.
- `playbooks/vpn-probe/test_screen.py`: nine boundary regression tests, including
  real no-network subprocesses and real loopback TLS/curl.
- `docs/vpn-reliability/PACKAGE-3.md`: this update and corrected unexecuted source plan.

### Reproduction and accounting fix

Before the fix, deterministic child wait/pipe barriers reproduced `pump()` assigning
`completed-window` to already-exited curl-status stand-ins 18/56/28. The separate
poll/signal-race cases reproduced `finish()` yielding `completed-window/error=null`
for only **3/100 bytes**, including curl 18. Partial natural segments and emitted
malformed metrics also became planned successes. The initial regression run failed
as expected; no remote or credential evidence was needed.

`abort()` now polls before assigning a cancellation cause or signaling. `pump()`
drains available IO before cancellation and wakes at the earliest relevant deadline;
all existing curl/parent time limits remain unchanged. An earlier request deadline
cannot become a normal workload-window deadline just because observation is late.
Body EOF is retained; `POLLHUP` also detects a closed writer behind unread pipe
bytes before signaling. Natural curl 18/56 truncations, curl 28 timeout, malformed
metrics/responses and HTTP errors remain failed rows with their raw curl exit.
An empty write-out after TERM/error is unavailable timing, not invented metrics;
emitted malformed write-out remains an error.

Request-end rows now include `cancellation_reason` and `termination`. The latter
distinguishes `natural-exit`, `runner-sigterm`, `eof-before-runner-sigterm`, and
`exit-raced-with-cancellation`. A cancellation request alone cannot override a
natural nonzero exit. Only actual runner-owned SIGTERM without previously observed
EOF can yield a planned partial `completed-window`; full segments still require
length/hash validation. Natural partial EOF fails. Expected runner SIGTERM does
not itself populate `first_transport_failure`, including when HTTP/diagnostic
validation fails. No-body deadlines and genuine transport failures still do.
Partial bytes, failed rows, raw exits, progress zeros and planned windows are kept.

Boundary cases cover natural 18/56/28/0, failure racing with signaling, actual
parent TERM, EOF before TERM (including unread body/EOF), earlier request timeout,
403/malformed headers/malformed metrics, and complete versus partial segments.
Tests assert both request-end events and summary failures/completions, partial-byte
totals, progress-byte totals, transport attribution and planned-window coverage.
Real TLS/curl cases use `wait()` to establish natural exit before the boundary and
a first-body pipe barrier to cancel a still-running transfer before curl's timeout;
there are no deadline-adjacent sleeps. Synthetic 600-second timelines check window
accounting only: these are **not sustained runs or performance evidence**.

### Local validation and limits

Executed locally, using only temporary **127.0.0.1** TLS listeners:

```sh
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe/reference -p 'test_*.py'
uvx prek run --all-files
uvx prek run --files playbooks/vpn-probe/screen.py \
  playbooks/vpn-probe/test_screen.py docs/vpn-reliability/PACKAGE-3.md
git diff --check
```

Results: **75 probe tests (43 screen) + 28 reference tests = 103 passed**.
The seven deterministic boundary test methods also passed five consecutive runs.
Repository-wide hooks, explicit changed-file hooks and whitespace checks passed.
One intermediate focused run exposed a cleanup-accounting regression introduced
while ordering the fix: disk exhaustion became failed instead of inconclusive.
Nonplanned cleanup/budget precedence was restored; the unchanged disk test passes.
The pre-fix failures and this intermediate failure are retained, not counted as
successful runs. Local logs are owner-only `/tmp/package3r-*.log`.

Only the owned process/pipe observations establish cancellation attribution;
unobserved ordering inside curl is not reconstructed. A natural exit racing with
TERM remains explicitly labeled and cannot erase an observed failure. A future
natural curl 28 at the planned boundary is still timeout, not automatically normal.
No route, source enforcement, external reachability, capacity or VPN/DPI claim
follows. All test processes/listeners, temporary keys and directories were cleaned;
no historical private evidence/credentials were read. No lease, SSH, privileged
worker, source/firewall change, public discovery/probe, deployment, production
change, commit or publication was performed.

R2 is incorporated in the proposal below: approve read-only container/namespace/
route/NAT inspection first, then privately review and explicitly approve the exact
endpoint-facing /32 before preparing/installing any lease. Unknown source/policy
means stop/inconclusive, not VPN failure. **That preflight was not run.**

Rollback: revert only this session's attribution/tests/report changes, preserving
all prior Package 3 and unrelated user changes; do not delete the original package.
No remote rollback is needed. Remove only the exact local `package3r-*.log` files
listed by this session after review if no longer needed. Stop for controller review.

## Original Package 3 changed paths

- `playbooks/vpn-probe/screen.py`: standalone stdlib runner, curl subprocesses,
  optional isolated sing-box, offline controller selection/worker handoff.
- `playbooks/vpn-probe/test_screen.py`: 34 tests, including real curl/TLS, real
  offline Ansible Vault round-trip and real offline sing-box configuration check.
- `docs/vpn-reliability/PACKAGE-3.md`: this report and unexecuted smoke proposal.

Existing diagnostic, endpoint, deployment and production files were not edited.
Runtime dependencies remain existing Python, curl, sing-box and, **only in the
Vault-owning controller**, existing Ansible and its YAML parser. No new package,
resolver, exporter, account, service or framework was installed.

## Implemented behavior

### Inputs, handoff and route boundary

The contract CLI is implemented: one `--route`, `--workload fresh|continuous|segments`,
finite duration/concurrency/rate/body/disk budgets, private endpoint/preflight
files, and explicit Vault/password or Cherry export paths. Continuous requires
one connection; fresh is sequential and at most 12 requests; segments permit 1–4
workers with the aggregate curl rate divided among them. There is no transparent
object retry, direct fallback, selector, detour, profile generator or production
state reuse. Tiny segments cannot consume unlimited endpoint operation IDs:
338 workload objects maximum, reserving operations for two preflights and up to
two receipt reads per object, always within 1024 operations.

Descriptors validate exact fields, HTTPS origin, IP/family consistency, scoped
CA path, run ID, authentication headers, lengths/digests, cache policy, final-only
`{request}` substitution, and integer expiry. Controls must have identical
origin/run/expiry/trust/authentication and a complete <=64 KiB preflight object.
Continuous objects must exceed the entire client byte cap. Startup and workload
lifetime checks reserve their remaining phases plus a five-second clock-skew
margin. Expired/short leases and HTTP 429 are endpoint constraints, not tunnel/DPI
failures. IPv6 execution is unsupported; no family fallback is attempted.

Additional CLI switches:

- `--prepare-worker`: **offline**, writes only selected `worker.json` and scoped
  `ca.pem` into the new private output directory. Descriptors explicitly name
  `/run/credentials/vpn-screen.service/ca.pem`. No network child starts.
- `--worker-input`: accepts only `worker.json` from the exact systemd credential
  directory, on a read-only mount, with safe owner/group and 0400/0440 modes.
  The worker receives no Vault password, full export, enrollment tokens, admin
  key, repository/home access or production state.
- `--gate`: network execution requires an initially absent, controller-released
  file. A ready event contains the actual Python PID/UID/GID/groups/net namespace.
  Gate wait is inside the 30-second startup allowance. Root and production UID
  946 cannot run the network worker. There is **no sudo or route-proof flag**.

Controller plaintext inputs remain owner-only, with private parents and no
symlink components. This is distinct from strict systemd credential loading;
read-only root-owned ACL-readable credentials do not relax controller checks.
The existing tracked Vault **ciphertext** is 0644, so it has its own ciphertext/
owner/non-writable validation; password/descriptors/exports are still private.
Vault view and Ansible YAML parsing are bounded subprocesses, plaintext only in
memory/pipes. Ansible uses a private temporary HOME and empty `ansible.cfg`, not
repository or user configuration; that temporary state is removed in `finally`.

The runner intentionally retains **route-unverified** raw outcomes, even for
successful body checks. A gate release is not machine-verifiable route proof.
Selected outbound log identity is recorded, but privileged interception/policy/
actual-socket corroboration belongs to the separately approved controller. No
short local test can produce a capacity qualification. Exit 0 can mean tool
completion with `route-unverified` or offline `skipped`: **inspect the outcome**.
DNS intent distinguishes IP-literal controls (DNS not exercised), independent
local tunnel bootstrap, and unknown CONNECT destination-resolution provenance.
A new curl connection is never advertised as a new outer tunnel connection.

### Progress, failures and resource bounds

- Curl config/URLs/headers go through stdin, never argv. `--disable` is first;
  inherited proxies/home configuration are excluded. Explicit proxy/noproxy,
  IPv4, HTTP/1.1, verified TLS, no redirects/retries, identity encoding and cache
  controls are set. This is deliberately an HTTP/1.1 **inner** TCP screen.
- Nonblocking selector IO concurrently writes config and drains body, header,
  allowlisted numeric metrics and stderr pipes. Payloads are discarded after
  incremental hash/counting. Stderr is drained but never stored. Diagnostics
  have strict ceilings; individual header/metric buffers are <=64 KiB, receipt
  bodies <=8 KiB, other diagnostics <=8 MiB. Secrets/raw curl JSON never enter
  events, exception messages or summaries.
- Per-second monotonic progress includes zero-byte intervals, measured interval
  lengths and failed-request time. Preflight and receipt bodies are separate
  from workload goodput, but charged against the aggregate client body cap.
  Body reads stop at that cap; in-flight/kernel/server bytes are not represented
  as client delivery. Curl's rate limiter can burst within its buffering; its
  cap is not an exact packet-level instantaneous shaper.
- Fresh connections are paced across their planned duration. All HTTP operations
  are additionally limited to <=20/s, below reference admission's 32/s ceiling;
  pacing pumps other active bodies rather than blocking their pipes.
- Connect <=10 s, first-body deadline <=20 s, non-continuous request <=30 s,
  startup/preflight <=30 s, receipts <=20 s, owned-group TERM grace <=5 s, then
  KILL/reap. Planned continuous cancellation is `completed-window`, not an
  unexpected curl timeout. Early EOF, no body, malformed metrics, HTTP policy,
  redirect, type/encoding/cache/length/hash failures remain explicit samples.
- Post-first-byte zero-progress gaps >=2 s are stalls, including censored open
  stalls at cancellation. Intentional between-request spacing is not a stall.
  Failed traffic stops further workload launches rather than hiding recovery
  behind a reconnect loop. Recovery and actual outer reuse remain unknown.
- Nonoverlapping post-warm-up ten-second windows retain zeros and label partial/
  missing coverage. First/middle/last windows use the planned timeline, not the
  last successful data. Window boundaries use overlap-weighted one-second samples,
  explicitly an estimator, not invented packet timestamps. Full windows below
  10 Mbit/s identify the first threshold breach; transport failure time/bytes
  are separate. Fresh mode never applies a sustained throughput threshold.
- `/proc` host CPU/memory/network drops/retransmissions and owned-process CPU/RSS
  are sampled each second. Shared host counters are confounded; remote CPU,
  memory, OOM/restarts and NIC/provider accounting are unknown. Unprivileged
  route/link/address/resolver fingerprints detect some environment changes;
  the full privileged watcher is still required, including production core,
  updater/config metadata and nft/iptables policy. No updater is paused.

Each new output directory is 0700; manifest, incrementally flushed JSONL, atomic
JSON/human summaries and temporary state are 0600. A 256 KiB terminal reserve
preserves reports at the disk ceiling. Normal terminal files and directory are
fsynced. Secret core configuration is removed at cleanup. Finished child groups
are retired immediately, not signaled again using old potentially reused PIDs.
SIGINT/SIGTERM preserves partial/failure records and a cancelled summary. SIGKILL,
OOM or failed finalization can leave an incomplete manifest: treat it as
inconclusive, never as a successful run.

### Receipt evidence

Every object/control operation gets a distinct authenticated operation ID. Each
object has at most two receipt reads, spaced 200 ms only after `active`, bounded
by finalization/expiry/operation/body budgets. No redownload obtains a receipt.
Binding, schema, source family, finite timing, size and final outcome are checked.
Active, expired, missing, mismatched or timed-out receipts remain incomplete,
independently of body integrity. Source mappings are private-manifest-only; events
and human summaries contain no addresses, URLs or credentials. Server
socket-accepted bytes are not proof of client delivery or protocol identity.

## Local results and validation

Observed local tools: Python **3.14.8**, curl **8.23.0** (OpenSSL 3.6.5), sing-box
**1.14.4**. No assumptions were carried forward from older version snapshots.
Temporary TLS certificates had a loopback IP SAN; curl used explicit scoped trust.
An unrelated real CA produced curl 60/TLS failure, with no insecure retry.

Retained illustrative runs (body bytes, excluding TLS/HTTP/tunnel overhead):

| Fixture workload | Workload requests | Workload bytes | Preflight bytes | Receipt bytes | Result |
| --- | --- | ---: | ---: | ---: | --- |
| Fresh, 0.8 s | 12 complete, 0 failed | 49152 | 4096 | 2716 | All complete hashes verified; route-unverified |
| Continuous, 3.2 s | 1 completed-window | 4096 | 4096 | 439 | Partial-unverified; 3.208 s open stall; route-unverified |
| Segments, 0.6 s, fan-out 4 | 10 complete, 0 failed | 163840 | 4096 | 2326 | Complete hashes verified; route-unverified |
| Deliberate HTTP 403 preflight | 0 workload; 2 failed preflights | 0 | 38 | 0 | Failed; both 403 samples retained |

These are **fixture correctness evidence**, not throughput/capacity results.
The continuous fixture deliberately sends 4096 bytes then stalls; it observes
client disconnect before finalizing an interrupted receipt. All 26 receipts in
the three successful fixture runs finalized (including preflight); the rejected
preflight run retains two incomplete receipts. No full post-warm-up throughput
window exists in these short examples.

Private retained artifacts: **97750 bytes**, located through owner-only
`/tmp/vpn-screen-package3-evidence-path`. Each run has private JSONL, manifest and
both summaries. Raw source mappings must not be published. All fixture listeners,
threads, subprocesses, certificates/private keys and fixture directories were
closed/removed; only private non-credential diagnostic artifacts remain. Test
logs are owner-only `/tmp/package3-*.log`. Temporary evidence is not a durable
archive; delete only the exact directory named by the locator after review.

Executed:

```sh
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe/reference -p 'test_*.py'
uvx prek run --all-files
uvx prek run --files playbooks/vpn-probe/screen.py \
  playbooks/vpn-probe/test_screen.py docs/vpn-reliability/PACKAGE-3.md
git diff --check
```

Final results: **66 probe tests (34 new) + 28 reference tests = 94 passed**;
repository-wide and explicit new-file hooks and whitespace checks passed.
Tests cover strict inputs/redaction/handoff, actual read-only credential-loader
criteria without loosening local inputs, ambiguous/missing sources, core check/
startup failures, real curl headers/metrics, 403/HTML/redirect/compression/length/
hash errors, malformed metrics plus a noisy stderr pipe, zero progress/open
stalls, planned windows, normal deadlines versus timeout, bounded fan-out, exact
aggregate byte cap, disk exhaustion/final records, environment invalidation,
receipt races/mismatch/expiry/deadline/operation ceiling, SIGINT and direct-child/
descendant termination/reaping. Credential read-only mount flags/ACL ownership
are simulated against real files; **no privileged systemd sandbox was launched**.
Core startup failure tests use no-network child processes; the real sing-box test
is **check only**, not a live VPN handshake.

Earlier local iterations failed and were corrected, not presented as passes:
empty explicit curl proxy serialization; curl `000` status being invalid JSON
unless quoted; real TLS truncation returning curl 56 as well as 18; late segment
launches at a deadline; and Ansible rejecting `/dev/null` as a configuration file
and needing private writable local temp state. The real Vault round-trip now
exercises the corrected environment. These were local implementation/fixture
failures, not tunnel/DNS/ISP observations.

## Concrete live-smoke proposal — NOT EXECUTED, approval required

Propose **one fresh <=900 s lease**, one selected **`cherry-vless`** route, three
sequential tiny workloads, each in a fresh isolated worker. No direct workstation
request, public source-discovery request, UDP traffic or sustained campaign.
Endpoint remains the reviewed native Cherry IPv4 TCP 9443 service; installed UDP
9444 is unused and removed with the lease. The **only proposed endpoint source /32**
is the selected exit core's exact **endpoint-facing source**, still unknown pending
separately approved read-only preflight. It is **not assumed to equal** either the
endpoint bind IP or Cherry's public Internet-egress IPv4: a container/bridge address
can reach the native host's INPUT path without Internet-egress masquerading. The
workstation reaches the existing VLESS listener on TCP 8443, not the endpoint
directly. Exact private inventory/bind/source/outbound values and source derivation
must be presented locally and explicitly approved **before lease preparation or
installation**; no value or source permission is inferred from this report or 2b.

1. First obtain approval **only for pinned read-only Cherry/workstation preflight**.
   Recheck provider policy, assigned bind, all native/Docker/NAT listener ownership,
   existing VPN/SSH health, nft/iptables/policy/tc context and updater state.
   Establish the **current selected VLESS core**, not merely a container name:
   container ID, actual core PID/start identity, configured network mode, attached
   networks/addresses/gateways and `/proc/<core-pid>/ns/net` versus the host namespace.
   Use narrowly selected `docker inspect` fields (not full secret-bearing config/env
   dumps), read-only namespace link/address/rule/route inspection, and TCP 9443
   destination route lookup in that actual namespace. Include any core source-bind
   or marking policy in the private source derivation. Follow the route through
   host bridge/veth and local delivery, inspecting relevant host/namespace nft and
   iptables PREROUTING/OUTPUT/POSTROUTING NAT plus INPUT/FORWARD/filter hooks. Determine
   whether any SNAT/masquerade actually matches this **host-local destination**;
   Internet-egress NAT alone is not evidence. Corroborate with already-existing
   socket context if available; route lookup alone is not source enforcement proof.

   Privately present bind IP, public egress IP (if already known; no discovery
   request), and derived endpoint-facing source as **separate facts**, with the
   exact minimal /32 and expected guard/receipt path. Then obtain explicit approval
   for that exact source, one fresh lease/install, worker launch, bounded load,
   collection and teardown. A container /32 addition/replacement needs explicit
   approval; never append it automatically, allow the bridge subnet, retain an
   unnecessary historical host source, or add a direct fallback. Host-local
   readiness with a different source would require its own separately approved /32
   and operations; it is not implied here. If read-only context cannot establish
   the source, stop and return a separately bounded observation proposal for review;
   do not send a discovery probe. Unknown/conflicting source or policy means stop/
   inconclusive. Policy refusal is not a VPN failure. Privileged reads remain
   separate from the network worker; admin keys never enter it. **None of this
   preflight or source approval is executed by Package 3r.**
2. Prepare just in time using reviewed `reference/prepare.py`, then install only
   through `reference-deploy.yaml`. The lease clock starts at preparation; keep
   all server caps unchanged. Verify actual endpoint PID/identity/guard/listeners/
   cgroup before the client worker. No retained commissioning credentials exist.
3. Controller privately selects `cherry-vless` and writes three handoffs:

   ```sh
   # CONTROL is a new owner-only directory outside the repository.
   # Paths contain descriptors/exports, never URL/token command-line literals.
   python playbooks/vpn-probe/screen.py --prepare-worker \
     --route cherry-vless --extra-outbounds-file "$CHERRY_EXPORT" \
     --endpoint-file "$OBJECT_DESCRIPTOR" --preflight-endpoint-file "$FRESH_DESCRIPTOR" \
     --workload "$WORKLOAD" --duration "$DURATION" --concurrency 1 \
     --rate-limit "$RATE" --max-bytes "$CAP" --max-disk-bytes 1048576 \
     --output "$CONTROL/handoff-$WORKLOAD"
   ```

   | Workload | Descriptor | Duration | Aggregate rate bytes/s | Aggregate client body cap |
   | --- | --- | ---: | ---: | ---: |
   | fresh | fresh.json | 5 s, <=12 requests | 262144 | 1048576 |
   | continuous | continuous.json | 5 s | 262144 | 2097152 |
   | segments | segment.json | 12 s | 1048576 | 16777216 |

   Thus at most **19 MiB client-read response bodies**, including controls, across
   all three invocations; expected workload roughly 13 MiB plus small controls.
   Actual client/server shared NIC deltas must be recorded separately. TLS/IP,
   administrative traffic and cancel overshoot are extra: 19 MiB is **not a wire
   or billing guarantee**. Server reservations remain bounded by the existing
   4 GiB lease cap; do not silently increase it or infer serving capacity.

4. Proposed launch below is for **each** workload, sequentially. Refuse existing
   own units/staging/runtime paths; use the fixed unit name because the handoff
   explicitly scopes its CA path to it. Stage only reviewed source, selected
   bundle and CA as root-owned 0600 under a new `/run/vpn-screen-stage` (0700).
   Create `/run/vpn-screen-release` root-owned 0755, with `go` **absent**. No
   repository/home permissions are widened.

   ```sh
   # Only AFTER approval. Copy the selected handoff into the new staging directory.
   sudo -n systemd-run --unit=vpn-screen --wait --pipe --collect \
     -p DynamicUser=yes -p User=vpn-screen -p SupplementaryGroups= \
     -p LoadCredential=screen.py:/run/vpn-screen-stage/screen.py \
     -p LoadCredential=worker.json:/run/vpn-screen-stage/worker.json \
     -p LoadCredential=ca.pem:/run/vpn-screen-stage/ca.pem \
     -p RuntimeDirectory=vpn-screen -p RuntimeDirectoryMode=0700 \
     -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
     -p PrivateDevices=yes -p ProtectProc=invisible -p PrivateNetwork=no \
     -p NoNewPrivileges=yes -p CapabilityBoundingSet= -p AmbientCapabilities= \
     -p RestrictSUIDSGID=yes -p RestrictNamespaces=yes -p LockPersonality=yes \
     -p 'RestrictAddressFamilies=AF_UNIX AF_INET AF_NETLINK' -p UMask=0077 \
     -p MemoryMax=256M -p MemorySwapMax=0 -p CPUQuota=100% -p TasksMax=16 \
     -p RuntimeMaxSec=100 -p TimeoutStopSec=5 -p KillMode=control-group \
     -p LimitFSIZE=1048576 -p StandardError=null \
     /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
       CREDENTIALS_DIRECTORY=/run/credentials/vpn-screen.service \
     /bin/sh -c '/usr/bin/python3 -I /run/credentials/vpn-screen.service/screen.py \
       --worker-input /run/credentials/vpn-screen.service/worker.json \
       --route cherry-vless --workload "$1" --duration "$2" --concurrency 1 \
       --rate-limit "$3" --max-bytes "$4" --max-disk-bytes 1048576 \
       --output /run/vpn-screen/result --gate /run/vpn-screen-release/go; \
       rc=$?; sleep 15; exit "$rc"' \
       screen-worker "$WORKLOAD" "$DURATION" "$RATE" "$CAP" \
       > "$CONTROL/$WORKLOAD-launch.log" 2>&1 &
   LAUNCH_PID=$!
   ```

   The fixed credential paths and explicit non-secret `CREDENTIALS_DIRECTORY`
   assignment deliberately survive `env -i`; the strict loader still verifies
   the actual read-only mount and file metadata. No inherited proxy/home values
   are retained.

5. Within the 30 s gate wait, read the ready event and inspect **its actual Python
   PID**, not systemd's pre-exec process or wrapper MainPID alone. Verify a fresh
   non-0/non-946/non-1000 UID, only its primary group, zero capabilities, NNP=1,
   host net namespace, cgroup/sandbox limits, read-only credential mount and private
   writable runtime path. Inspect all interception/marking/NAT/policy hooks for
   that UID, including late TUN fallback rules. Capture privately:

   ```sh
   sudo -n nft -j list ruleset
   sudo -n iptables-save
   sudo -n ip6tables-save
   sudo -n ip -j route get "$CHERRY_IP" uid "$WORKER_UID" ipproto tcp dport 8443
   sudo -n ss -H -ntup
   # Plus complete IPv4/IPv6 rules/routes/link/address and tc/XDP context.
   # Release ONLY after policy/identity review establishes the intended underlay:
   sudo -n touch /run/vpn-screen-release/go
   ```

   Gate release is a separate reviewed controller action. DynamicUser and a
   route lookup alone do not establish exemption. Watch semantic policy, links,
   production PID/start/config metadata/updater and owned sockets at one-second
   intervals, bounded to 100 samples / 4 MiB each invocation. Abort only the test
   unit on material change or missing context; never repair/stop production.
   Corroborate actual selected VLESS log identity plus endpoint receipt source,
   which must match the explicitly approved endpoint-facing /32. Source mismatch
   or source-guard/policy refusal stops the smoke as inconclusive, not a VPN
   failure; do not alter sources or retry directly. Short sockets missed by
   sampling and outer reuse remain explicitly unknown.
   Read-only remote `/proc`/container health samples every five seconds, <=20
   samples, belong to the approved pinned controller context, not the worker.

6. The wrapper's **15 s post-run hold** keeps the dynamic identity/runtime directory
   alive for collection. On terminal manifest, while the unit still exists:

   ```sh
   # Controller-owned redirected archive, umask 077; no worker credential/config copy.
   sudo -n tar --no-recursion -C /run/vpn-screen/result -cf - \
     manifest.json events.jsonl summary.json SUMMARY.md \
     > "$CONTROL/$WORKLOAD-artifacts.tar"
   wait "$LAUNCH_PID"  # Preserve nonzero status and partial output.
   ```

   Bound controller collection to that hold; if artifacts cannot be collected,
   mark incomplete, not successful. The runtime directory is removed at teardown;
   no chown, permanent account or DynamicUser-owned persistent files are needed.
   Review body, receipt and route evidence before the next workload. Stop on any
   unexpected failure; no same-lease object rerun to manufacture a pass.

7. In `finally`, stop only `vpn-screen.service` if necessary, verify its cgroup,
   children, credentials/runtime mounts/account are gone, then remove only this
   invocation's staging/release files. Always run reviewed reference teardown,
   including after partial install. Set a controller workload/launch deadline
   **600 s from preparation**: cancel the own worker then, allow <=240 s for
   controller teardown and <=60 s for verification within the unchanged lease.
   Never restart or renew the lease. Verify endpoint
   listeners/units/guard/replay state gone and preserved production SSH/VPN/process/
   policy health against baseline. Keep private evidence, then delete this
   invocation's selected handoffs and original lease material; unlink is not
   guaranteed secure storage erasure.

This proposal requires fresh explicit approval. It does **not** establish external
negative-source rejection, direct ISP baseline, DNS usability, endpoint serving
capacity, Internet egress, sustained performance, UDP relay, media/Discord or DPI
resistance. Those remain separate gates. Same-host receipt sources and distinct
9443/IP-SAN/private-CA handshakes are known confounders.

## Rollback and cleanup

Remove only the three new Package 3 paths if rejected. No production rollback or
remote cleanup is needed: nothing was installed or contacted. Private local
artifacts can be removed using the exact owner-only locator after evidence review;
all temporary fixture keys/processes/listeners are already gone. Preserve the
pre-existing modified documents and untracked Package 2/2b sources. Stop here.
