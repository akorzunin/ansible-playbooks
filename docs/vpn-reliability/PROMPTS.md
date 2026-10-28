# Implementation-session prompts

Run these sequentially, with user review between them. Paste the common contract
and one package into each new session. Bring the resulting report back to the
controller. Do not start all sessions concurrently against the same workspace or
network: measurements and changes would interfere.

## Common contract (paste every time)

```text
Work in /home/akorz/Documents/ansible-playbooks. Read AGENTS.md, then
 docs/vpn-reliability/{PLAN,INVENTORY,CONTRACT-v1,PACKAGE-1b,PACKAGE-2,PACKAGE-2b,PACKAGE-3,PACKAGE-3b,PACKAGE-3b-r}.md first.
The inventory and DNS evidence are time-bounded; recheck relevant runtime facts.
Follow the amended contract, not older assumptions. You are an implementation
session; there are no sub-agents. Implement only the package below. Preserve existing user changes,
including .gitignore and .ansible-lint. Prefer small Python stdlib/curl/sing-box
utilities and existing Ansible patterns, without speculative abstractions or new
services. Never read private credentials/state into chat, print bearer/signed
URLs, or commit private artifacts. Inspect secrets locally only as necessary;
report aliases/capabilities, not values. Do not auto-commit.

The target is THIS Linux machine on its affected ISP, YouTube 1080p, Twitch
1080p60 viewing, Discord voice. Existing Cherry VPN is available for testing;
no new VPS. Traffic has no small quota (roughly 5 TB VPN allowance), but runs
must be finite, cancellable, accounted and resource-bounded. Never modify the
active VPN/default route, restart production services, install packages globally,
rotate credentials or publish profiles without explicit approval for that step.

After changes run focused tests and uvx prek run --all-files. Report changed
paths, commands/results, security/routing limitations, sanitized evidence, and
rollback/cleanup. Distinguish not run, unsupported, inconclusive and failed from
passed. Stop at the package's review gate. Package 3r controller review verified
103 tests and hooks passed and accepted the deadline/source corrections. Package
3b then aborted before release on a private controller polling bug. Package 3b-r
has 129 passing tests/hooks but a startup writer/reader mismatch found in review.
Next is Package 3b-r2 local integration correction, not a live retry or campaign.
Earlier unrelated YAML violations were fixed
externally. Recheck current validation rather than repeating a stale baseline.
Do not introduce suppressions or unrelated fixes.
```

## 1. Runtime inventory and executable test contract

```text
Perform read-only discovery; do not deploy or run sustained loads yet.
Inspect playbooks/naiveproxy/check.py and README.md, sing-box-configs generator,
platform templates/updater, node/nt1, monitoring, and available Cherry artifacts.
Maintained tracked Cherry and vpn-probe sources exist. Use those sources;
do not dump Terraform state or recover source by decompiling caches.

Identify the actual existing Cherry test host, safe SSH/inventory method,
protocols/ports/transport capabilities, core/build versions, resource ceilings,
and which endpoints/configs on this machine correspond to it. With approval
for read-only SSH, inspect runtime and produce a sanitized capability table.
If access is missing, ask the user rather than inventing a host or credential.

Record this machine's actual underlying interface/routes, proxy environment,
active VPN/TUN state, IPv4/IPv6 and DNS path. Explain how isolated route tests
will avoid nesting through another tunnel, direct fallback and inherited rules.
Audit VLESS/REALITY compatibility and UDP support without modifying settings.
Explicitly separate repository statements from verified current runtime facts.

Write a concise sanitized inventory and concrete v1 measurement/output contract
under docs/vpn-reliability/. Specify route input source (prefer existing Vault
without logging plaintext), minimal CLI, progress schema, error outcomes,
interval/stall definitions, and 10-minute screening commands. No framework or
dashboard. Flag any PLAN.md assumption contradicted by runtime.

Gate: return the inventory, unresolved access/approval needs and the precise
implementation proposal. No campaign or configuration changes yet.
```

## 1b. DNS baseline and safe launch (complete; retained as original instructions)

```text
Package 1 is accepted as a time-bounded inventory. Implement the controller's
amendments in CONTRACT-v1.md before endpoint deployment or hostname-dependent
screens. Preserve the existing tools. Do not implement the sustained runner yet.

First propose exact transient unprivileged launch/cleanup commands. Prefer a
systemd DynamicUser worker if supported; do not reuse production UID 946, run
network workers as root, create a permanent account, broaden home/private-file
permissions, or touch production routes/services/updater. Verify actual rules:
UID 1000 is intercepted, and DynamicUser alone is not route proof. The owning
controller passes only selected diagnostic credentials through a private channel;
never give the worker Vault passwords or administrator SSH keys. Bound lifetime,
privileges, writable state and private output collection. Get user approval for
the exact privileged invocation before trying it. Unproven paths are marked
route-unverified, not advertised as direct ISP baselines.

Implement a small bounded DNS diagnostic and deterministic offline tests.
The user observed dig @1.1.1.1 youtube.com returning NXDOMAIN but the TCP A query
returning NOERROR. This has not been independently reproduced. Compare identical
queries/options over explicit UDP (no automatic TCP fallback) and TCP from the
verified context. Include positive and expected-NXDOMAIN controls; record complete
RCODE/flags/answer/authority/timing privately. NOERROR without usable answers is
not success. Distinguish libc/NSS resolution from explicit resolver queries.
Propose finite targets/query count/timeouts before live probes. Use a second
resolver/EDNS comparison only as a bounded follow-up, not a broad scan.

Add CA/hostname-verified DoH/DoT checks with independent bootstrap; distinguish
TLS/HTTP failures, malformed DNS and usable DNS answers. Never disable TLS
verification, follow redirects blindly, or fall back silently to plaintext.
If existing tools cannot test a mode, report unsupported and propose the smallest
addition rather than installing global dependencies. Record A/AAAA DNS answers
over IPv4 separately from this machine's lack of IPv6 connectivity.

For VPN DNS, test only through an explicitly verified isolated core, or mark it
not run pending package 3; do not use the active SSH selector and claim a chosen
Cherry path. Separate tunnel bootstrap, resolver bootstrap, explicit tunneled
DNS and actual CONNECT/application destination resolution. Existing IP-based
outbounds may provide independent controls while retaining TLS/REALITY names.
Do not modify /etc/resolv.conf, caches, production configs or timers.

Gate: return DNS diagnostic changes/tests, sanitized paired results if approved,
launch/cleanup evidence, attribution limits and a proposed bootstrap/destination
DNS policy. Resolver migration and endpoint deployment remain unapproved.
```

## 2. Controlled reference endpoint (offline implementation reviewed)

```text
Packages 1/1b are reviewed. Implement endpoint/deployment code and offline tests
only; stop before deployment. Follow CONTRACT-v1.md's Package 2 gate. Implement
the smallest idempotent deployment for controlled noncompressible HTTPS transfers
and a restricted UDP measurement endpoint. Reuse existing components where
practical; justify dependencies. Return exact host, listeners, TLS trust/renewal,
authentication, firewall effects, resource limits, readiness commands and teardown.
Do not rerun DNS probes or privileged launches under Package 1b's past approval.
The existing Cherry test VPN is permitted, but do not disrupt its VPN or
administrator SSH access. Preserve occupied TCP 22/80/443/8443 and production
certificates/configs. Propose a reviewed TLS/listener strategy; no insecure TLS,
private-key copying or existing-proxy reload as an implicit shortcut. If using
a distinct HTTPS port, label that limitation in later protocol comparisons.
No open proxy, unauthenticated reflector, large unbounded files, secret-bearing
logs or wildcard firewall opening.

Include health/readiness, finite transfer sizes/durations, source restrictions
or suitable authentication, bounded replies, request/session/rate limits,
read-only resource use where possible, expiry/teardown and verification. UDP
restrictions must account for direct client and VPN-exit source addresses.
Expose minimal authenticated run/request receipt evidence: server-observed
source, bytes and timing, not an untrusted forwarded source header. Bound retention
and avoid claiming source identity proves protocol. Include negative tests for
unauthorized/expired/replayed requests and session limits. UDP echo alone cannot
measure independent one-way loss/jitter; state supported metrics and sequence/
count evidence per direction. Keep key material in private inputs, not argv/history.

Document that a same-VPN-host endpoint tests access/tunnel capacity, not that
host's Internet egress. Plan a real-destination/available-distinct-host control.
Provide separate small preflight/fresh objects, digest-verifiable segment objects
and a finite continuous object larger than the chosen byte cap. Demonstrate bounded
RAM/disk generation on the 1 GiB host. Demonstrate that endpoint resource/rate
ceilings do not cap below the client's intended load, or document that measurement
ceiling. Return private endpoint descriptor shape and any necessary contract
amendments; do not silently break the proposed runner interface.
Unit-test relevant validation and negative cases. Do not run throughput loads
against public third-party speed-test services without permission.

Gate: return code/tests and PACKAGE-2.md with the exact deployment, bounded smoke
and teardown proposal. STOP before remote installation or listener/firewall changes.
No sustained runner/campaign yet. Deployment and live readiness checks require
separate explicit user approval after review.
```

## 2b. Bounded commissioning (reviewed complete; original instructions retained)

```text
Package 2's offline implementation is reviewed. Follow CONTRACT-v1.md and
PACKAGE-2.md. Do not implement the sustained runner or change production VPN,
DNS, routing, certificates or client profiles.

First add expires_at to the three generated endpoint descriptors, exactly equal
to config.expires, and test it. Preserve all resource/lifetime caps; update the
report/schema proposal. This is metadata for later expiry-aware measurements,
not permission to regenerate or install a live lease yet.

Request user approval for bounded read-only pinned SSH preflight on the existing
Cherry host. Verify current native listeners, Docker bindings and complete relevant
NAT/host policy, assigned bind IPv4, systemd/tool support, existing reference
resources, and safe SSH/VPN health baseline. Do not infer free ports from ss alone.
Propose exact private bind and /32 source values, including actual same-host source
routing; do not paste secrets or private mappings into shared reports. Do not
probe to discover public source addresses without including that in the approved
preflight. Unknown/conflicting policy or needed provider changes mean stop.

Then obtain explicit approval for one exact fresh-lease preparation/install,
inspection, the documented same-host readiness, and teardown. Prepare just in
time: the 900-second lease starts at preparation, not service start. Install only
through the reviewed standalone playbook; no source broadening or production
reload/restart. Verify actual unit identity/sandbox, loaded own nft guard and
listener binding before smoke. Same-host readiness is one attempt: six HTTPS
operations and one 96-byte authenticated UDP request/reply, under its 60-second
cgroup limit. No workstation probes, external load or new targets are included.
Do not retry or relax receipt/hash/auth assertions after failure; preserve evidence
and review whether startup, receipt timing, source policy or expiry caused it.

Collect sanitized outcomes plus private receipts/context as needed before the
lease expires. Same-host success is not external filtering, VPN routing, endpoint
capacity or ISP qualification. An external negative-source test needs its own
approved vantage/plan; otherwise mark it not run. Offline tests are not enforcement
proof. Keep the performance/port/SNI/private-CA confounders explicit.

Always execute the approved own-resource teardown, including after partial start
or failed smoke. Verify endpoint/smoke cgroups, credentials, listeners, own nft
rules, installed units/files and replay state are gone, and preserved production
SSH/VPN health and other policy are unchanged. No dangling endpoint while
Package 3 is written; a new screen later needs a fresh separately approved lease.

Gate: return PACKAGE-2b.md with exact approved actions, sanitized runtime evidence,
failures/limits, cleanup verification, tests/checks and remaining calibration or
source-enforcement work. Stop before sustained runner/campaign or profile changes.
```

## 3. Sustained TCP diagnostic runner (implemented; 3r reviewed)

```text
Package 2b commissioning/cleanup is reviewed. Implement screen.py/test_screen.py
in playbooks/vpn-probe/ using the amended CONTRACT-v1.md. No live endpoint remains.
Work locally: no new lease/deployment, SSH, privileged worker, source-allowlist
change or external request in this package. Do not interpret historic readiness
authorization as approval for workstation traffic. Preserve existing tools and
production configs; no framework, dashboard or generic plugin abstraction.

Implement strict ca_file/run_id/receipt-template/expires_at handling, exact
same-origin receipt URLs, safe config/header serialization and unique operation
IDs. Check remaining lifetime before startup/workload; budget receipt collection
and cleanup. Do not lengthen caps or treat expired/depleted leases as tunnel
failures. Continuous/segment runs need a separately validated small fresh-object
--preflight-endpoint-file from the same lease; never use a 4 GiB object as a tiny
successful preflight or invent descriptor/hash data.

Use an explicit controller/worker handoff: controller privately selects one
outbound and endpoint, worker receives only necessary material under the reviewed
isolated UID/sandbox. No automatic sudo/production UID or grants of Vault/admin
keys. Supply concrete proposed launch/route-evidence/cleanup commands for review.
Record unproven identity/interception context as route-unverified, never infer
exemption just from curl proxy flags. Incorporate 2b's credential lesson: local
private inputs and systemd read-only credential mounts need distinct strict
handling; do not loosen a global permissions check.

Support explicit direct and individual approved VPN routes with isolated
loopback listeners/state and no automatic fallback or production config edits.
Do not require every route to start successfully to produce other results.
Support repeated fresh requests, a continuous large noncompressible HTTPS
transfer, and repeated large-object/segment-like downloads. Record per-second
progress and stage/HTTP/byte-integrity errors, bounded timeouts, stalls and
partial results. Record actual route evidence and avoid claiming a new outer
connection merely because curl was restarted. Each invocation selects one route;
future comparisons run sequentially, with bounded fan-out within that route.
Capture progress even at zero goodput; use the planned timeline after failures.
Keep control/preflight bytes separate from workload windows and preserve all
failed attempts. Fresh or short smoke success is not 600-second qualification.

Write private incrementally flushed JSONL, manifest and a sanitized summary
with early/middle/late windows, failures, time/bytes-to-degradation, sustained
window goodput, stall durations and recovery. Never omit failures from totals.
Check HTTP status/redirect/content/length so error pages or cache compression
cannot appear as successful throughput. Handle startup failure, malformed curl
output, subprocess timeout, mid-transfer stall, SIGINT and orphan cleanup.
Protect temporary configs, secrets and signed URLs in logs/exception paths.

Collect receipt finalization separately from body success. Follow the contract's
two-read bounded active-receipt policy, unique IDs, total-operation ceiling and
expiry/deadline handling. Do not redownload objects or hide retries. Missing or
still-active receipts mean incomplete evidence, not invented source identity.

Add deterministic tests for input/redaction, actual curl output/headers, startup
and malformed metrics, partial failures/stalls/zero windows, timeouts versus normal
deadlines, byte/disk/process limits, receipt races/mismatch/expiry and SIGINT/orphan
cleanup. Include real curl subprocess integration against a temporary loopback-only
TLS fixture using scoped test trust and strict cleanup; no Internet or production
services. Test selected real-library behavior, not only MagicMock: Package 2b's
connection-context bug was hidden by its original mock. Keep body/metric/stderr
pipes drained concurrently with bounded buffers and final summaries on failure.

Gate: return PACKAGE-3.md with changed paths, CLI/worker-launch proposals, tests,
sanitized local artifacts, remaining limits and an exact finite live-smoke plan
for a fresh lease and explicitly approved sources. STOP before executing that plan.
External reachability/source enforcement and endpoint-capacity calibration remain
live gates; no performance/DPI conclusions or production changes from local tests.
```

## 3r. Correct runner deadline accounting (reviewed complete; original instructions)

```text
Read the controller review at the top of PACKAGE-3.md and the amended contract.
Implement only the two review corrections below; preserve all other user/package
changes. No new lease, SSH, privileged launch, source-allowlist change or external
request. Keep this local; do not jump to the proposed live smoke or campaigns.

R1: Reproduce Runner.pump assigning completed-window to a curl that has already
naturally exited 18, then Transfer.finish returning completed-window/error=null
for only 3 of 100 expected bytes. Fix the smallest cause/accounting path. Preserve
an already-observable natural exit, EOF or protocol failure before considering
runner-owned cancellation. Record causal provenance and raw curl exit; ambiguous
races must not erase a failure. Do not simply classify every SIGTERM/nonzero exit
as failure: genuine parent-owned planned cancellation must remain distinguishable.
Do not loosen integrity/HTTP/deadline checks or discard partial failed samples.

Add deterministic boundary regressions for already-exited curl 18/56, natural
unexpected timeout, actual parent-owned cancellation of a still-running transfer,
error/malformed response at the deadline, and complete versus partial segments.
Use real loopback TLS/curl integration where it can test the actual boundary
without relying on flaky sleeps. Verify both request rows and summary failure/
partial-byte/window accounting; rerun all existing tests and required hooks.

R2: Correct the live-smoke proposal's endpoint-source assumption. A containerized
VLESS exit connecting to a native service on its own host may present a container/
bridge source instead of the public bind/exit IPv4. Specify read-only namespace,
route/NAT/network-mode preflight and exact source-plan review before installation.
An actual /32 source addition requires explicit approval; no automatic broadening
or direct fallback. Unknown source/policy means stop/inconclusive, not VPN failure.
No live preflight or source-discovery probe is part of this corrective package.

Gate: update PACKAGE-3.md (or add PACKAGE-3r.md) with changed paths, regression
reproduction/fix evidence, full test/check results and the amended unexecuted
smoke proposal. STOP for controller review before any live action. Do not refactor
unrelated runner code, add abstractions or implement UDP/media features here.
```

## 3b. Bounded runner live smoke (attempted; aborted before release)

```text
Package 3r is reviewed and accepted. Follow PACKAGE-3.md's revised concrete
live-smoke proposal and CONTRACT-v1.md. No sustained campaign, protocol tuning,
source broadening, direct fallback, DNS repair or production/client changes.

Request approval for bounded pinned read-only Cherry/workstation preflight first.
Verify actual VLESS core PID/container/network namespace, host-local destination
route and relevant NAT/filter path; derive the endpoint-facing source separately
from bind/public-exit IP. Check local UID interception, updater/policy context,
server resources and listener ownership. Do not send source-discovery traffic.
Unknown source/policy means stop with a bounded observation proposal, not guessing.

Privately present the exact minimal /32 and obtain explicit approval for that
source, one fresh <=900 s lease/install, isolated DynamicUser workers, the three
specified tiny workloads, evidence collection and teardown. Do not prepare a
lease until approval. The proposed endpoint permits only the reviewed source;
a container /32 is not automatically authorized by past host-local readiness.

Use the reviewed launch/gate/watch/collection procedure in PACKAGE-3.md. Inspect
the ready event's actual Python PID/UID, sandbox, policy exemption and sockets
before release; gate creation alone is not proof. Check the selected VLESS log
and receipts against the exact approved source. Keep raw route-unverified records
and write a separate controller assessment; exit 0 alone is not a smoke pass.

Run sequential cherry-vless workloads only: fresh 5 s at 256 KiB/s / 1 MiB body
cap; continuous 5 s at 256 KiB/s / 2 MiB; segments 12 s at 1 MiB/s / 16 MiB.
Total <=19 MiB client-read bodies, not a wire/billing guarantee. Keep endpoint
caps unchanged. After each, inspect artifacts: no unexpected request failure,
complete hash-verified fresh objects, positive continuous bytes with truthful
cancellation/partial accounting, and >=1 complete hash-verified segment. Record
censored final partial work, receipts, skipped/missed observations and all errors.
Stop on unexpected failure, source mismatch or missing route evidence; no blind
same-lease retry or automatic direct request. Short smoke is not a speed/DPI test.

Collect artifacts while the dynamic runtime exists; preserve partial output if
collection/startup fails. Always execute approved own-worker/staging/reference
teardown, including after partial install, within the reviewed outer deadlines.
Verify no own processes/listeners/units/credentials/state/nft table remain and
production SSH/VPN/DNS/routing/updater are unchanged. Do not pause the updater.

Gate: return PACKAGE-3b.md with approvals/actions, per-workload evidence,
separate route assessment, failures/limits, validation and verified cleanup.
Stop before calibration, sustained screening, other protocols, UDP/media or
publishing. Further fixes/retries need explicit scoped authorization and must
preserve failed attempts, not manufacture a pass.
```

## 3b-r. Readiness polling and abort evidence (implemented; review found mismatch)

```text
Read PACKAGE-3b.md's controller review and CONTRACT-v1.md's readiness/abort gate.
Correct only the session-private controller defect and evidence-loss path.
No lease preparation, SSH, privileged/systemd launch, gate release, source change,
external request or live retry. Do not alter screen.py's network/qualification
semantics, endpoint caps, VPN/DNS/routing or production/updater state.

Put the minimal polling/allowlisted-artifact handling into a small tracked helper
under playbooks/vpn-probe/ with focused tests. Existing reviewed launch commands
can remain explicit; no generic service manager, new dependency or framework.
The correction must be used by the proposed procedure, not an unused parser next
to another untested private orchestration script.

Read JSONL incrementally with bounded byte/time/poll limits. Missing file, empty
bytes, blank lines and a partial final line mean pending until a complete record
or deadline. Test delayed creation and a ready record split across writes.
Complete malformed JSON, wrong schema/non-ready records, permission/read errors,
truncation, early process exit and timeout must remain distinguishable. Never
call json.loads on a blank poll or treat every exception as not-ready. A valid
ready record supplies the candidate Python PID for existing context inspection;
the helper must not auto-release a gate or claim route proof.

Implement/test the startup-error and cancellation collection path: while owned
runtime still exists and it is safe, attempt bounded private collection of only
manifest.json/events.jsonl/summary.json/SUMMARY.md before unit removal. Refuse
symlinks/nonregular files, bound file/total/time use, keep 0700/0600 destinations,
and record missing/partial/no-terminal artifacts accurately. No full-directory
archive, core config, handoff, key or credential copy. Do not invent raw outcomes.

If graceful cancellation is used, signal only an actually verified owned worker,
retain the approved hold/deadline and collect before runtime deletion. If no PID
is verified, or immediate stop is necessary, do not guess; preserve available
files and explicitly mark any evidence loss. Copy/read/timeout errors must never
skip the always-run own-resource teardown. Test call ordering and cleanup for
these failures with fake units/processes and temporary files; no root/systemd
or network sockets are needed for these regressions.

Rerun focused/all existing tests, required hooks and whitespace checks. Return
PACKAGE-3b-r.md or an explicit correction section with changed paths, regression
evidence and exact revised polling/collection/cleanup procedure for review.
STOP. No retry is authorized; the consumed lease/old approval cannot be reused.
```

## 3b-r2. Align actual startup writer/reader (next; local only)

```text
Read the controller review in PACKAGE-3b-r.md. Fix only the reproduced startup
contract mismatch. No SSH, lease, privileged/systemd launch, release-gate creation,
external request, production change or live retry. Preserve all prior evidence.

Reproduce using the actual screen writer/startup ordering, not rows manufactured
from the controller READY fixture: execute emits run-start while run/endpoint are
unselected, then read_inputs/envelope.update supplies the approved identity, then
route-evidence/ready is emitted. Current poll_ready rejects that first real row
as wrong-schema even when the next ready event is valid.

Align this narrow bootstrap transition explicitly. Prefer the smallest change;
if the runner's initial emission must change, limit it to startup metadata and
preserve diagnostic artifacts on pre-input failure. Do not relax ready-event
run/route/endpoint validation, ignore arbitrary identity mismatches, swallow
malformed complete records or infer a candidate from bootstrap/default fields.
No change to network/deadline/qualification or collection authority is needed.

Add an offline writer/reader integration regression using screen.Artifacts/
execute's actual startup sequence or a locally gate-held process that never
releases the gate. Test that legitimate startup reaches the expected candidate,
while wrong run/endpoint/route in ready records, malformed startup and terminal
pre-input failure stay distinguishable and cannot grant readiness. Do not merely
patch the fixture to skip the unselected first record; assert actual wire rows.
Keep the existing empty/partial/error/bounded-copy/always-teardown regressions.

Rerun all focused tests, hooks and whitespace checks. Update PACKAGE-3b-r.md or
add PACKAGE-3b-r2.md with the failing reproduction, minimal fix, new integration
evidence and revised startup contract/procedure. STOP for review before any
fresh execution request. Do not refactor unrelated code or add a framework.
```

## 4. Actual service tests and the UDP/voice path

```text
Extend the reviewed runner minimally for real destination/service evidence.
YouTube/Twitch homepage HTTP success is not a pass. Provide reproducible media
checks using current permitted tooling or an explicit manual-browser runbook:
record selected rendition, actual CDN delivery, startup, buffer/rebuffer events,
quality changes, segment deadlines and 30-minute playback. Separate expired
signed URLs, ads, auth/challenges and extractor breakage from network failures.
Never put account cookies/tokens or signed URLs into shared reports. If a media
tool is necessary, propose it before adding/installing it.

Implement sequence-numbered bidirectional UDP measurements through a VERIFIED
route to the approved endpoint: loss, reordering, RTT, documented jitter
estimator, burst loss and receive gaps. Test unloaded and concurrently with
video/load on the SAME route. SOCKS5 UDP-associate can isolate synthetic UDP if
supported; verify installed-core behavior. Ordinary curl CONNECT/proxychains
and direct iperf3 do not test tunneled UDP. Never relabel UDP-over-TCP as native
outer UDP. Test rejected/unsupported UDP paths explicitly.

This machine already has UID-scoped TUN/nftables interception, and Package 1
observed an SSH selector incapable of UDP relay. Recheck it. Prefer proving a
reviewed existing application path; propose temporary scoped TUN/netns only if
needed. Ask approval before changing routes, selectors or installing tools.
Provide rollback and actual route/leak evidence; do not assume the current TUN
is suitable or that the production updater can safely remain unexamined.
Do not implement the Discord protocol, self-bots, DAVE, or a new WebRTC stack.
Use a current client, user-controlled call and willing peer to verify both audio
directions. Generic UDP/STUN success is only a prerequisite, not Discord acceptance.

Gate: return tested automation, manual acceptance steps, route evidence and
unsupported constraints. No production profile publishing.
```

## 5. Baseline campaign and DPI-related qualification

```text
Use reviewed utilities and docs. First reproduce the current failure without
changing server/client parameters. Run direct/path and server-side controls,
then isolated candidate routes. Capture host resource metrics alongside client
progress. Screen candidates, then run 10-15 minute sustained tests, cooldown/
recovery and actual 30-minute media/voice checks for plausible finalists. Repeat
in different time windows. Keep traffic/time accounting and do not saturate all
routes at once. Actual Discord checks require the user's participation.

Research current upstream VLESS/REALITY/Naive behavior and Russian filtering
measurements with linked sources/dates, including contrary evidence. Treat
net4people #490/#546 and Cloudflare's 16 KB report as distinct hypotheses,
not proof of the mechanism here. Audit real settings, resources, MTU, clocks,
authentication, DNS and client/server capability before attributing failure to DPI.

Propose a short experiment matrix that changes one factor at a time: ordinary
HTTPS vs tunnel, fresh/reused outer connections, concurrency/load/cooldown,
then justified transport/port/settings changes. Get user approval before any
server or active-client change or packet capture. Keep captures private/bounded.
No indiscriminate port scans, arbitrary SNI rotation, or protocol zoo. Avoid
invalid comparisons where simultaneous runs or different destinations explain
results. If independent paths cannot be held constant, mark the confounder.

Gate: return a sanitized report with evidence-linked conclusions, availability
matrix by protocol/server/destination, candidate recommendation, uncertainties
and remaining experiments. Claim observed stability, never DPI invisibility.
Do not publish based on small-request success or service startup alone.
```

## 6. Qualified configuration and safe distribution

```text
Only proceed after the user accepts package 5's evidence and selected route(s).
Update existing Vault-backed connections, generator and tests using repository
patterns; do not create a second credential source or rotate stable profile URLs.
Retain useful TCP fallbacks but do not advertise them as UDP-capable. Distinguish
protocol diversity from independent exit redundancy. Ask before adding any host.

Preserve distribution's direct recovery path. Review DNS/rule-set bootstrap,
broad duckdns.org bypass, core compatibility and route selection. Do not turn
URLTest back on based on a small successful probe. Propose only the minimal
capability-aware routing needed for the accepted workload; explain if no single
route meets all three services rather than silently sending UDP direct.

Identify the actual active updater first: Package 1 found a different installed
timer/script than the repository updater. Propose consolidation or migration with
explicit approval; do not create competing writers/restart loops. Improve the
reviewed Linux canary updater with a bounded, explicitly routed semantic health
gate and tested last-known-good rollback. A running process can still
have an unusable tunnel. Avoid oscillation, secret leakage, and making remote
hosting availability a condition for keeping a cached working profile. Test
unchanged/invalid profiles, unreachable hosting, syntactically valid but broken
tunnel, restart failure, interruption and rollback. Clarify that a short updater
check cannot replace the sustained qualification campaign.

Gate: show the diff/rollback and obtain approval before publishing. Canary on
THIS machine, verify connected/disconnected refresh and actual services, then
report stability before considering Android/Windows or wider distribution.
```
