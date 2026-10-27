# Implementation-session prompts

Run these sequentially, with user review between them. Paste the common contract
and one package into each new session. Bring the resulting report back to the
controller. Do not start all sessions concurrently against the same workspace or
network: measurements and changes would interfere.

## Common contract (paste every time)

```text
Work in /home/akorz/Documents/ansible-playbooks. Read AGENTS.md, then
 docs/vpn-reliability/{PLAN,INVENTORY,CONTRACT-v1}.md first. The inventory is a
 time-bounded snapshot; recheck relevant runtime facts. Follow the controller's
 amended launch/DNS contract, not older assumptions. You are an implementation
 session; there are
no sub-agents. Implement only the package below. Preserve existing user changes,
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
passed. Stop at the package's review gate.
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

## 1b. DNS baseline and safe launch (next after Package 1 review)

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

## 2. Controlled reference endpoint on the Cherry test infrastructure

```text
Use the amended contract and reviewed Package 1/1b reports. Implement the smallest
idempotent deployment for a controlled noncompressible HTTPS transfer endpoint
and a restricted bidirectional UDP measurement endpoint. Reuse existing server
components where practical, and justify any added dependency. Show the exact
host, listeners, firewall changes and resource limits before requesting approval
to deploy. Existing Cherry test VPN is permitted, but do not disrupt its VPN or
administrator SSH access. No open proxy, unauthenticated reflector, large
unbounded files, secret-bearing logs or wildcard firewall opening.

Include health/readiness, finite transfer sizes/durations, source restrictions
or suitable authentication, bounded replies, request/session/rate limits,
read-only resource use where possible, expiry/teardown and verification. UDP
restrictions must account for direct client and VPN-exit source addresses.
Expose only the minimal sanitized server-side receipt evidence needed to prove
which path arrived. Keep key material in private/Vault inputs, not argv/history.

Document that a same-VPN-host endpoint tests access/tunnel capacity, not that
host's Internet egress. Plan a real-destination/available-distinct-host control.
Provide separate small preflight/fresh objects, digest-verifiable segment objects
and a finite continuous object larger than the chosen byte cap. Demonstrate bounded
RAM/disk generation on the 1 GiB host. Define endpoint receipt semantics and how
authenticated run IDs link source/route evidence without logging bearer tokens.
Unit-test relevant validation and negative cases. Do not run throughput loads
against public third-party speed-test services without permission.

Gate: deploy only after reviewing the exact change with the user, then return
endpoint aliases, readiness evidence, limits, access instructions and teardown.
```

## 3. Sustained TCP diagnostic runner

```text
Use the amended contract, reviewed 1b launch/DNS evidence and reference endpoint.
Implement screen.py/test_screen.py in playbooks/vpn-probe/, using the useful
isolation patterns from playbooks/naiveproxy/check.py. Preserve that old tool
unless replacing it clearly reduces duplication without breaking its documented
workflow. Do not build a generic plugin framework.

Support explicit direct and individual approved VPN routes with isolated
loopback listeners/state and no automatic fallback or production config edits.
Do not require every route to start successfully to produce other results.
Support repeated fresh requests, a continuous large noncompressible HTTPS
transfer, and repeated large-object/segment-like downloads. Record per-second
progress and stage/HTTP/byte-integrity errors, bounded timeouts, stalls and
partial results. Record actual route evidence and avoid claiming a new outer
connection merely because curl was restarted. Run capacity comparisons
sequentially, with configurable bounded fan-out within the chosen route.

Write private incrementally flushed JSONL, manifest and a sanitized summary
with early/middle/late windows, failures, time/bytes-to-degradation, sustained
window goodput, stall durations and recovery. Never omit failures from totals.
Check HTTP status/redirect/content/length so error pages or cache compression
cannot appear as successful throughput. Handle startup failure, malformed curl
output, subprocess timeout, mid-transfer stall, SIGINT and orphan cleanup.
Protect temporary configs, secrets and signed URLs in logs/exception paths.

Add deterministic local/fake-process tests; no live Internet required for unit
tests. Run a short approved reference smoke check, not a full campaign. Explain
outer path verification limits if the active machine routing prevents isolation.

Gate: return commands, tests, sample sanitized output and smoke evidence.
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
