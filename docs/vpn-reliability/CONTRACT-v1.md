# VPN measurement contract v1 — proposal, not an implemented runner

Package 1 review artifact, amended by controller review. Read `INVENTORY.md` for
current constraints and PLAN.md's DNS qualification requirements. The inventory
is accepted as a time-bounded snapshot; implementation may follow this amended
contract, but privileged execution, deployment and campaigns need separate user
approval. Package 1b is reviewed and complete within its documented scope;
see `PACKAGE-1b.md` for evidence and limitations. Package 2's offline implementation
and Package 2b's same-host commissioning/cleanup are reviewed. See `PACKAGE-2b.md`
for failed attempts, runtime fixes and limits. External paths/source enforcement
and throughput are not established. Package 3r's deadline-accounting corrections
and source-path proposal are now reviewed/accepted in `PACKAGE-3.md`; 103 tests
and repository hooks passed independently. Package 3b installed one approved lease
but aborted before gate release due to controller polling; cleanup is documented.
No workload/route result exists. Package 3b-r polling/collection is implemented,
but review found an initial unselected-envelope mismatch with the actual runner.
Next is Package 3b-r2 local writer/reader integration correction, then review
before any fresh attempt. No live retry is approved.
Keep existing tools intact. Commands below describe the proposed package-3
interface, **not commands to run now**.

## Inputs and implementation boundary

Implement one small stdlib runner, `playbooks/vpn-probe/screen.py`, and deterministic
`test_screen.py` tests; no framework, dashboard, automatic switching or dependency.
Use curl for HTTPS and one isolated sing-box core for one selected VPN route.
Package 2 supplies the reviewed endpoint; package 4 supplies UDP/media acceptance.

- `--route`: exactly one alias: `direct`, `nt1-ssh`, `nt1-naive`, `nt1-vless`,
  `cherry-ssh`, `cherry-naive`, `cherry-vless`. No selector or implicit detour.
  Workstation-hop routes require later explicit opt-in and nested labeling.
- `--vault-file`: existing `playbooks/sing-box-configs/secrets.vault.yaml`;
  `--vault-password-file`: existing private file, never its contents on argv.
  Capture `ansible-vault view` into memory, suppress plaintext/stdout/errors,
  select only `sing_box_secrets.connections` for nt1. Do not invoke the generator
  (it writes profiles), retain token fields, or create a second credential source.
- `--extra-outbounds-file`: explicit private JSON export for Cherry. Validate one
  exact tag, allowed type and required fields. Reject duplicates, unknown tags,
  selectors, automatic/fallback routes, `detour` and unexpected direct outbounds.
  Current Vault has no Cherry extras: missing export is `skipped/missing-input`,
  never an invented host. If Vault later owns the same tag, reject ambiguity
  until the operator chooses one source. No input files are rewritten.
- `--endpoint-file`: owner-only private JSON, not a URL on argv. Version 1 object:
  `schema_version`, `alias`, `https_url`, `auth_header` (optional), `family`,
  `expected_status`, `content_type`, `object_bytes`, `sha256`, `cache_policy`,
  `receipt_url` and `receipt_auth_header` (optional), `location` (`vpn-host` or
  `distinct-host`). Aliases use `[a-z0-9_-]+`. Reject plaintext HTTP, userinfo,
  redirects, unknown fields, invalid sizes/digests, unexpected family and
  group/world-readable inputs. URLs/headers remain private. Receipt support
  must tie an authenticated run ID to source evidence, never echo client tokens.
  Implemented/reviewed Package 2/2b extensions are `ca_file`, `run_id`, the receipt
  template and integer Unix UTC `expires_at` equal to the server config's expiry.
  `ca_file` identifies selected lease-specific trust staged for this worker, not
  a system trust-store modification or permission for insecure TLS. Reject unsafe
  file paths/permissions and credential/config-line injection. Require authenticated
  `X-Run-ID` and a fresh `X-Request-ID` for each HTTP operation, including receipt
  reads. Receipt URLs must remain on the exact HTTPS origin with the same scoped
  CA; only the final `{request}` component may be substituted with a validated ID.
  Reject all other unknown fields/templates, redirects or origin/trust fallback.
  Record lease expiry/remaining time; insufficient lifetime for startup/workload/
  receipt collection is an endpoint constraint, not a tunnel failure.
- `--preflight-endpoint-file`: required for continuous/segments, selecting the
  lease's complete small fresh object; fresh mode may use its own endpoint file.
  Validate the same origin, run ID, expiry, CA trust and authentication across
  both descriptors. Do not use a 4 GiB object as a successful tiny preflight,
  guess hashes or silently derive/replace URLs. Account preflight/control bytes
  separately from workload goodput and against applicable aggregate budgets.
- Endpoint object is finite, noncompressible, immutable for the run, serves the
  declared length/type/hash, has no content encoding and disables caching.
  Use workload-specific objects: a small bounded object for fresh/preflight
  checks, complete digest-verifiable objects for segments, and an object larger
  than the maximum permitted download for continuous screens. Completed shorter
  objects do not become sustained results. Package 2 must show how large finite
  content is generated/served without exhausting the 1 GiB test host's RAM/disk.
  Segments use complete objects and verify digest/length for each completion;
  their hash detects integrity, not compressibility. Package 2 must establish
  noncompressibility. An incomplete continuous object has no full-object hash
  verdict: report `integrity=partial-unverified`, not checksum success.
- `--workload`: `fresh`, `continuous`, `segments`; `--duration` seconds,
  `--concurrency` 1–4, `--rate-limit` aggregate bytes/s, `--max-bytes` aggregate
  body bytes, `--max-disk-bytes` total output/state, `--output` a new private dir.
  CLI rejects unbounded/zero durations, unsafe paths, invalid combinations and
  excessive limits before launch. `continuous` requires concurrency 1. `fresh`
  makes 12 bounded requests maximum, sequentially, regardless of remaining time.

No privilege-changing CLI flag: the separately reviewed launcher must establish a
noncaptured unprivileged UID for **all** network children, including direct curl,
resolver clients and isolated cores. Do not reuse production sing-box UID 946:
same-UID processes can access/signal production regardless of separate directories.
Prefer a transient systemd DynamicUser identity, or an equivalently isolated
identity after review; no permanent account or routing change is assumed.

The source-owning controller selects credentials; the worker receives only its
selected outbound/endpoint material via a private pipe or equivalent reviewed
mechanism. Do not grant the worker access to the Vault password, administrator
SSH keys, whole private export, home directory or production state. Keep remote
administrative sampling in a separate approved controller context. Clear inherited
proxy variables, drop capabilities/supplementary groups, use no-new-privileges,
and make only owned temporary state writable. Arrange readable diagnostic source
without widening private home/repository permissions. Bound the worker's process
group/cgroup lifetime and terminate only its own children. Handle ownership and
collection of private output after transient identity teardown explicitly.

Package 1b verified systemd sandbox support, local exemptions and cleanup for its
approved direct-DNS worker. It did not qualify a VPN core or longer workload.
Use that procedure as a reviewed pattern, not blanket execution approval.
DynamicUser itself does not prove route bypass. Record UID/namespace and recheck
nftables/policy context before claiming any new baseline. Root is permitted only for narrowly reviewed launch/state
inspection, not the network worker/core. No privileged launch is authorized by
this contract. Fail `route-unverified` if context or underlay cannot be proven.

## Isolation, DNS and route proof

1. Snapshot UTC, monotonic start, tool builds, active core PID/start time, config
   metadata, interfaces, policy routes, nftables interception and proxy env
   presence (not raw values). Use actual outer IP/family/port lookups and socket
   evidence for the chosen execution UID; verify endpoint receipts where available.
   Watch the environment throughout the run; abort/invalidate on material change.
2. Construct the minimum profile from scratch: loopback mixed listener on an
   OS-assigned port, only the chosen outbound, final route explicitly that outbound,
   no selectors, production rules, rule sets, direct destination rules, external
   controller, TUN or shared cache. Use private independent working state and
   fail on listener/core startup errors. Validate with the installed core first.
3. curl uses `--disable` first, sanitized proxy environment, TLS verification,
   explicit `--proxy` and `--noproxy ''` for VPN. Direct uses `--proxy ''` and
   `--noproxy '*'`. Do not follow redirects or retry transparently. Secret URL/
   header options go through curl configuration stdin, not argv; do not log the
   config, curl's raw `%{json}` or unfiltered stderr.
4. Separate **bootstrap DNS** (local/underlay resolver for the VPN hostname) from
   **destination DNS** (domain delivered by HTTP CONNECT to the selected outbound;
   relay/server resolution must be corroborated or labeled unknown). Direct uses
   the local resolver. Record resolver mode and failure, not an invented remote
   DNS guarantee. No direct DNS fallback after a tunneled-resolution failure.
   Local DNS failed during inventory; preserve/recheck that result rather than
   silently replacing names with unreviewed IPs or disabling TLS verification.
   Package 1b implements the paired DNS checks below; throughput runs reference
   that evidence but must recheck bootstrap and destination resolution.
5. IPv4-only first (`--ipv4` plus IPv4 outer resolution strategy). Record both
   inner and outer family independently. IPv6 is a separate requested run and
   currently `unsupported/no-ipv6-underlay`; never silently retry another family.
6. Proof requires selected outbound log identity **and** verified underlay context;
   add authenticated endpoint-observed source when available. Source alone cannot
   distinguish protocols sharing an exit. Missing receipts reduce evidence; if
   no alternative establishes route identity, outcome is `route-unverified`.
   Count observed outer connections/reuse, or mark them unknown; a new curl
   process does not establish a fresh outer tunnel. No direct fallback on failure.
   For a native endpoint on the selected VPN's host, establish the actual core's
   network namespace/mode and endpoint-facing source. Container/bridge traffic
   addressed to that host may not traverse Internet-egress masquerading. Bind IP,
   public exit IP and endpoint-observed source are distinct facts. Review/approve
   the exact needed /32; do not automatically broaden sources or misclassify a
   source-guard drop as a failed VPN handshake.

## DNS diagnostic gate (Package 1b)

Implement a small bounded diagnostic, separate from `screen.py` unless existing
code can be reused without coupling. Use available tools and deterministic tests;
no new local resolver service or production DNS changes. Approve the concrete
execution context/targets before live probes. Start with this machine only.

- Accept aliases/private resolver specifications; retain bootstrap IPs and any
  returned addresses privately. All network clients must use the verified worker
  context, not UID 1000 by accident. Record unverified-context samples as such.
- Pair the same name, type, resolver, EDNS settings and query flags over UDP/TCP.
  Disable UDP-to-TCP fallback, bound retries/time, preserve original response
  flags/RCODE/answer/authority and indicate truncation. Check NOERROR contains
  usable positive answers; record expected NXDOMAIN controls separately. Test A
  and AAAA even with IPv4 transport. Do not require identical CDN addresses.
- Start with the user's youtube.com observation and positive/negative controls;
  use a second resolver and a separate EDNS comparison only to resolve ambiguity.
  Keep a fixed finite query count, pacing and manifest; no name/resolver scanning.
- Test HTTPS/DoH and TLS/DoT with CA/hostname verification and explicit independent
  bootstrap. Verify both the TLS transport and decoded DNS result. Blocked TLS,
  HTTP error/HTML, malformed DNS, unusable answers and timeout are distinct.
  No insecure TLS, redirect following or transparent plaintext fallback.
- Support an explicitly routed encrypted/TCP DNS check through each candidate
  once the isolated core is ready; never label a direct query VPN-routed because
  it used a familiar resolver address. Unsupported UDP relay is not DNS failure.
- Distinguish system/libc resolution, VPN-server bootstrap, encrypted-resolver
  bootstrap, explicit queries via VPN, and actual application destination DNS.
  Do not assume HTTP CONNECT or DoH configuration makes all these paths remote.
- Keep diagnostic completion separate from resolver usability; repeated failures
  still yield a complete report. Reproduce without cache flushing or production
  resolver changes. A claimed source IP does not authenticate UDP/TCP DNS.

A 1b run is not a resolver migration or a prerequisite that every mode pass.
A verified IP-based tunnel control may proceed independently of broken local DNS
with retained TLS/REALITY name verification. Any production bootstrap/fallback
policy remains a later explicit design decision, without circular tunnel dependency.

## Package 2 endpoint implementation gate

Implement and test offline before requesting deployment approval. The package
must return the exact host/listeners, TLS trust/renewal plan, authentication,
firewall effects, resource limits, health/smoke commands, teardown and private
endpoint descriptor compatible with the runner. No existing VPN/SSH listener,
ACME storage, production DNS or client profile changes are implicitly approved.

- Preserve occupied TCP 22/80/443/8443; recheck actual listener ownership before
  proposing additional ports. Do not add SNI routing or reload existing proxies
  just to reuse 443 without a separate reviewed change. If a distinct port is
  chosen, ordinary HTTPS there is a port-specific control, not a same-port DPI
  comparison. Validate TLS without insecure mode; propose any scoped CA trust or
  descriptor extension explicitly rather than copying production private keys.
- Bound endpoint CPU/RAM/disk/processes/concurrency and aggregate bytes/rate/time
  without making the endpoint a hidden bottleneck below the client screen cap.
  Provide small fresh objects, complete hashed segments and finite continuous
  content larger than the client byte cap, generated with bounded RAM/disk.
  Do not produce throughput claims from sparse/zero/compressed payloads.
- No open reflector/proxy. Use restricted sources and appropriate authentication,
  expiry, replay controls and bounded replies/sessions. Review actual host/Docker
  firewall behavior; merely declaring a source allowlist is not enforcement proof.
- Receipts bind authenticated run/request IDs to server-observed source, bytes
  and timing. Do not trust forwarded headers from untrusted clients or pretend
  source identity proves the chosen protocol. Bound retention and omit tokens.
- UDP echo alone measures round-trip RTT/loss, not independent one-way loss or
  jitter. Define sequence/count evidence for each receiving direction if those
  metrics are promised; no synchronized-clock claim without synchronization.
  Package 2 supplies the endpoint; client/Discord acceptance remains Package 4.
- Same-Cherry-host tests isolate access/tunnel capacity, not Cherry Internet
  egress. Document local/hairpin/exit source behavior without silently changing
  source restrictions or adding another server. Unit tests run without Internet.

Offline implementation gate reviewed: `PACKAGE-2.md` provides code, tests and the
proposed deployment/smoke plan. Package 2b must obtain explicit user approval for
pinned read-only remote preflight, exact bind and /32 source list, then one fresh
lease install, same-host readiness and teardown. Recheck current native/Docker/NAT
port ownership and assigned IP before installation; conflicts/unknown host or
provider policy stop execution. Do not use Package 1b's historic launch approval.

Approved design scope (not execution permission): dedicated CA with IP SAN,
TCP 9443/UDP 9444 on one reviewed Cherry IPv4, own source-guard table, ephemeral
credentials, no production listener/DNS changes. Same-host smoke is six HTTPS
operations and one authenticated UDP packet, no sustained load. Runtime source
filter enforcement, dynamic identity, loaded guard, health and cleanup still need
evidence. If a negative-source check lacks a reviewed independent vantage,
report not run rather than spoofing sources or modifying rules to simulate it.

Known ceilings: 900 s lease, <=600 s UDP session, four sessions, 4 GiB object
budget and ephemeral receipts. One lease cannot cover a complete sequential
multi-route campaign or 30-minute voice acceptance. Keep limits unchanged for
commissioning; a later explicit design review must cover longer qualification.
Resource/CPU ceilings also need later calibration, not tiny-smoke inference.
Collect receipts before expiry/teardown. Package 2b is reviewed: the same-host
commissioning passed after runtime corrections and all resources were removed.
Only Cherry's own /32 source was authorized/tested; external source rejection,
client path and throughput remain unqualified. There is no retained live lease.

## Timing, progress and outcomes

Hard bounds for proposed screens: 600 s workload, startup/preflight <=30 s,
final receipt collection <=20 s, cleanup <=10 s, whole invocation <=660 s. HTTP connect timeout 10 s, TTFB deadline
20 s; continuous request max-time is remaining workload budget; segment request
max-time 30 s. Startup gets one attempt. Preflight gets at most two attempts per
stage with 2 s spacing, preserving both failures. Exhaustion still writes a report.
Record endpoint remaining lifetime at validation and immediately before workload;
require enough for remaining planned phases and a documented clock-skew margin.
Expiry/insufficient lifetime or known endpoint budget exhaustion is an endpoint
constraint, not DPI/tunnel failure. Keep canceled/incomplete evidence on failure.
A normal continuous screen reaching its planned deadline is not a curl timeout;
a genuinely runner-owned cancellation at that deadline may be `completed-window`.
Check already-observable child exit/EOF/error state before assigning that cause.
Do not overwrite a naturally exited curl 18/56/28 or malformed/error response with
planned-success accounting merely because the parent observes it at/after the
workload deadline. Preserve raw curl status and cancellation provenance; ambiguous
races remain explicit/inconclusive, not silently successful. Conversely, expected
parent SIGTERM alone is not a transport failure. Unexpected curl/subprocess
failures remain failures. Early EOF is `unexpected-length`.
Byte/disk limits before the deadline yield `inconclusive/budget-exhausted`.

Drain body bytes incrementally through a pipe without storing payload; sample
monotonic progress every second even when there are no received bytes. Drain
metrics/stderr concurrently with strict bounds, so stalled pipes cannot deadlock.
Use actual interval elapsed time (not an assumed second) for goodput:
`8 * body_byte_delta / elapsed_seconds / 1e6` Mbit/s. Payload bytes exclude TLS,
HTTP and tunnel overhead; count those separately only if measured.

- Warm-up is the first 10 s; retain it but exclude it from screen thresholding.
- A zero-byte interval counts as zero goodput, never disappears from averages.
  A stall is a maximal contiguous zero-progress period of at least 2 s after
  first body byte. Pre-body delay is TTFB; intentional idle spacing is not a stall.
  Mark open stalls at cancellation/end and report longest stall and censoring.
- Evaluate nonoverlapping 10 s workload windows after warm-up, including zeros
  and failed-request time. Incomplete final windows are labeled partial. Proposed
  sustained screen threshold (continuous/segments only): every full window
  >=10 Mbit/s with route proof and no unexpected HTTP/transport/integrity failure.
  Fresh/preflight checks assess reachability/latency, never sustained throughput.
  Report first threshold breach
  time/bytes and first transport failure separately. This is only a controlled
  TCP screen, not service qualification or evidence of DPI invisibility.
- First/middle/last 60 s windows use the **planned** timeline: [10,70), [270,330),
  [540,600) for 600 s runs. Early-ended windows remain missing/partial; do not
  substitute the last successful samples. Report total attempted/completed/failed
  requests, partial bytes, TTFB, stalls, errors, reconnects, connection reuse and
  recovery. Recovery is unknown/not run until explicit cooldown probes are added;
  no tight automatic reconnect loop hides a transient block.

Each incrementally flushed JSONL record has this common envelope:

```json
{"schema_version":1,"event":"progress","run":"r001","route":"cherry-vless","endpoint":"reference-on-vpn","utc":"2026-10-26T00:00:01Z","elapsed_s":1.0,"request":1,"interval_s":1.0,"body_bytes_total":0,"body_bytes_delta":0,"goodput_mbit_s":0.0,"stage":"response-body","outcome":null}
```

This is an illustrative sanitized schema, **not observed traffic**. Events:
`run-start`, `preflight`, `request-start`, `progress`, `request-end`, `host-sample`,
`route-evidence`, `run-end`. Request-end additionally records `curl_exit`, HTTP
status/version, expected/received bytes, content checks, integrity, TTFB,
`time_total`, new/reused outer connection evidence and a sanitized error code.
Unavailable timings/attribution are null with an explicit reason. A proxy's TLS
or connect timing is not automatically the remote leg's timing.

Terminal outcome is one of `passed`, `failed`, `timeout`, `unsupported`, `skipped`,
`route-unverified`, `inconclusive`, `cancelled`. Keep a separate stage/error code:
`input`, `core-check`, `startup`, `route`, `bootstrap-dns`, `destination-dns`,
`tcp`, `tls`, `authentication`, `http-status`, `redirect`, `content-type`,
`content-encoding`, `unexpected-length`, `integrity`, `response-body`, `process`,
`budget`, `cleanup`. Unknown-stage failures stay unknown, not guessed DNS/DPI.
Application/policy errors such as 403 remain distinct from transport failures.
A preflight HTTP success is not a workload or route qualification pass.
SIGINT/SIGTERM preserves partial records and a cancelled summary, terminates only
owned process groups, waits <=5 s then kills/reaps owned children. SIGKILL cannot
promise a final record; next inspection marks an incomplete manifest inconclusive.

### Receipt finalization and evidence

Receipts can legitimately be `active` immediately after the last client body byte.
A finalized receipt is separate from the body integrity verdict. Permit at most
two explicit receipt reads per workload request, spaced 200 ms when the first is
active, within the 20 s finalization/whole-run/lease budgets. Each read has its own
fresh authenticated operation ID and uses the selected route and scoped CA.
This is recorded control-plane polling, not an invisible retry of failed traffic.
Never rerun the object to obtain a receipt. Still-active/missing/expired/mismatched
receipts leave receipt evidence incomplete; do not invent final source/bytes or
claim proof of client delivery from server socket-accepted bytes. Respect the
1024-operation endpoint ceiling, counting objects, preflight and receipt reads.

Keep workload byte progress separate from preflight and receipt bodies. Record
route proof and qualification scope separately from successful tool completion:
a short local/smoke run cannot become a 600 s capacity qualification. Server CPU,
shared-host counters or uncalibrated endpoint limits can leave performance
attribution inconclusive even when transfer metrics are valid.

## Artifacts, resource sampling and security

A new output directory is 0700, files 0600, umask 077; reject unsafe existing
output, symlinked paths and insecure parents. Write `manifest.json` before
startup, `events.jsonl` flushed every record and at least each second, and atomic
`summary.json` plus sanitized `SUMMARY.md` even after preflight failure. On normal
completion fsync terminal evidence; mark a run incomplete if finalization fails.
No secrets/URLs/addresses in shareable summaries. Keep any necessary address
mapping/socket details in the private manifest only. Private raw logs are still
credential-sensitive and must never be committed or pasted as evidence.

Manifest: aliases, versions/builds, timing/budgets, command options without
secret-bearing values, workload/endpoint location, family/DNS intent, route
proof/limitations, baseline host state, sanitized config fingerprint, outcome.
Fingerprint is SHA-256 of canonical config with hosts replaced by aliases and
credentials/pins replaced by presence/type markers, **not hashes of passwords**.
It identifies the public configuration shape, not credential equality. Do not
persist decrypted Vault or enrollment URLs. Temporary credentials are unlinked
on exit (not guaranteed secure erasure from storage).

Sample client `/proc` CPU/memory/network drops/TCP retransmissions every second;
for the selected remote host propose finite read-only SSH sampling every 5 s of
host and relevant container CPU/memory, OOM/restart counters, drops and TCP
retransmissions. A missing collector is `unknown`, not zero. Remote collection
requires review for the campaign; no new exporter, capture or service. Counters
shared with other traffic are explicitly confounded, not per-route packet loss.

Default screen limits: concurrency 1; aggregate 4194304 body bytes/s (32 Mibit/s,
33.55 Mbit/s); 3221225472 body bytes; 67108864 output/state bytes. Bound individual
log/diagnostic buffers to 8 MiB and reserve terminal-summary space within the disk
limit. Stop with partial evidence if any budget is reached. At concurrency 4,
divide the aggregate cap among workers, not 4x the allowance. This intentional
rate ceiling can mask capacity above 33.55 Mbit/s; raise it only in a reviewed
campaign, not by interpreting a capped run as maximum throughput. Disk bodies
are discarded; segment digests are computed incrementally.

## Controller readiness and abort-evidence gate

Package 3b exposed an untested session-private orchestration path: an empty poll
was passed to json.loads, then unit stop removed dynamic runtime artifacts before
collection. Package 3b-r must correct/test these paths locally in a small tracked
helper, not build a generic orchestration framework or change the network runner.

- Poll boundedly. An absent file, no bytes, whitespace or an unfinished final JSONL
  record means pending, not malformed JSON or readiness. Parse complete records
  incrementally; retain the unfinished tail privately until more data or deadline.
  Complete malformed/wrong-schema records, permission/read errors, truncation and
  early child/unit exit have distinct outcomes. Do not hide them as empty polls.
- A valid ready event identifies a candidate Python PID for existing controller
  inspection, not authority to release the gate. Never infer readiness from
  systemd success, MainPID alone or a parser default. Helper tests must send no
  packets, create no release gate and require no systemd/privileged launch.
- On startup/poll/cancellation/error paths, attempt bounded private collection of
  existing manifest.json/events.jsonl/summary.json/SUMMARY.md before removing the
  owned runtime where safe. Refuse symlinks/nonregular files, cap reads/disk/time,
  record partial/missing files and never copy core.json, handoffs or credentials.
  Missing terminal worker files cannot become an invented complete outcome.
- Gracefully cancel only a verified owned worker if necessary/safe to let it write
  terminal evidence; do not signal guessed PIDs. If immediate stop is required or
  the unit already exited, preserve what remains and explicitly record evidence
  loss. Do not expand runtime/lifetime/permission bounds to collect files.
- Collection errors/timeouts must not prevent the always-run own-resource teardown.
  Offline tests must establish ordering and cleanup on poll/copy/process failures.
  Do not suppress failures, renew leases or send live retries under past approval.

Package 3b-r review reproduced an interoperability hold: the actual runner emits
run-start with unselected run/endpoint before read_inputs, whereas the reader
requires selected identity on all rows. Package 3b-r2 must align this exact
bootstrap transition and test actual writer rows. Do not relax approved identity
checks on ready events, ignore arbitrary mismatched records or lose pre-input
failure artifacts. Bootstrap/default metadata can never itself grant readiness.

Return PACKAGE-3b-r.md/3b-r2.md (or a clearly separated correction section) with
code, integration regressions and the revised unexecuted procedure. Fresh preflight/
exact-source/lease/load approvals remain a later execution gate after review.

## Proposed ten-minute screening commands — DO NOT RUN YET

These require the runner to be implemented, the approved noncaptured-UID launch
context, resolved preflight constraints, and a package-2 endpoint file readable
only in that context. Placeholder private paths must be supplied locally, never
with URL/credential contents. `RUN_ROOT` must be a private 0700 parent. Each
invocation selects one route; comparisons are sequential with rotated ordering.

```sh
python playbooks/vpn-probe/screen.py \
  --route cherry-vless \
  --extra-outbounds-file "$CHERRY_OUTBOUNDS" \
  --endpoint-file "$CONTINUOUS_ENDPOINT" --preflight-endpoint-file "$FRESH_ENDPOINT" \
  --workload continuous --duration 600 --concurrency 1 \
  --rate-limit 4194304 --max-bytes 3221225472 \
  --max-disk-bytes 67108864 --output "$RUN_ROOT/cherry-vless-continuous"

python playbooks/vpn-probe/screen.py \
  --route nt1-naive \
  --vault-file "$PROFILE_VAULT" --vault-password-file "$VAULT_PASSWORD_FILE" \
  --endpoint-file "$SEGMENT_ENDPOINT" --preflight-endpoint-file "$FRESH_ENDPOINT" \
  --workload segments --duration 600 --concurrency 1 \
  --rate-limit 4194304 --max-bytes 3221225472 \
  --max-disk-bytes 67108864 --output "$RUN_ROOT/nt1-naive-segments"
```

For a direct control use the same command with `--route direct` and no credential
input flags; the noncaptured-UID requirement **still applies**. Use identical
workload/endpoint/budget when comparing protocols; the two commands illustrate
interfaces, not a valid cross-workload protocol comparison. A fresh-connection
check uses `--workload fresh --duration 60 --concurrency 1` (maximum 12 requests),
with the same finite limits. Fresh HTTP connections and fresh outer connections
must be reported separately. Concurrency 4 is a later separately labeled run.

One ten-minute screen transfers at most approximately 2.52 GB body data at the
cap, before overhead; four screens <=10.07 GB, about 0.20% of a nominal decimal
5 TB allowance before overhead. Package 2 must also enforce finite server-side
transfer/session budgets for cancel overshoot. Record actual client/server NIC
counter deltas where available, distinguish shared traffic, and estimate overhead
and unresolved provider billing semantics. No allowance/bill guarantee is made.
A same-VPN-host endpoint measures access/tunnel capacity, not host Internet egress;
complement it later with a distinct available controlled endpoint or authorized
real-destination traffic. No public speed-test load or new VPS is proposed.

## Implementation/review gates

1. Controller review accepts Package 1's snapshot and Package 1b's short direct-DNS
   evidence/isolated launch. VPN DNS, tunnel/application bootstrap and sustained
   health remain unqualified. Package 2b commissioning/cleanup is reviewed and
   accepted for its same-host scope. No endpoint remains. Package 3 now implements
   the runner locally; no new endpoint deployment, source expansion or privileged
   invocation is authorized by controller review alone.
2. Package 3r's deadline accounting and source proposal are reviewed/accepted;
   original findings/regressions remain in `PACKAGE-3.md`. Package 3b was approved
   and attempted but aborted before release; no smoke requests ran. Complete
   Package 3b-r2's actual startup writer/reader correction before another live
   review. The 3b-r tests pass but missed the initial unselected envelope; keep
   their bounded polling/artifact coverage. No retry/execution is authorized.
   Required runner tests include missing input,
   ambiguous route, redaction, startup/check failure, malformed metrics, 403/HTML,
   redirect/compression/length/hash errors, no body progress, monotonic windows,
   early abort, exact deadline vs timeout, byte/disk cap, SIGINT and orphan cleanup.
   Tests need no Internet and must not invoke real deployment/active services.
   Add selected real-library/real-curl integration against temporary loopback-only
   TLS fixtures, bounded with cleanup; validate actual supported curl options and
   pipe/metric behavior, not just a permissive mock of the connection API. Test
   controller-private versus systemd credential inputs without weakening either.
3. Run focused tests plus `uvx prek run --all-files`; return PACKAGE-3.md with
   commands, local evidence, limits and exact new-lease/worker/smoke proposal.
   Stop before live deployment, privileged worker or external probes. Any later
   smoke first needs explicit sources/route proof and bounded load approval;
   same-host commissioning did not qualify that workstation path.
   Package 3b uses the reviewed three sequential cherry-vless workloads: fresh
   5 s / 1 MiB body cap, continuous 5 s / 2 MiB, segments 12 s / 16 MiB, with
   rates/worker bounds from PACKAGE-3.md. These are not 600 s qualification runs.
   Require truthful partial/failure/cancellation accounting, complete verified
   fresh objects, positive continuous bytes and >=1 complete verified segment.
   Raw route-unverified/exit 0 is not a passing route: assess UID/underlay, chosen
   outbound and exact receipt source separately without rewriting raw records.
   Unexpected failures/missing source evidence stop progression; no automatic
   source broadening, direct retry, lease renewal or production repair. Always
   retain evidence and perform approved own-resource teardown. Return PACKAGE-3b.md.
4. Media, bidirectional UDP and actual Discord remain package 4, campaigns package
   5. Neither syntax checking nor this future TCP screen permits publishing.
