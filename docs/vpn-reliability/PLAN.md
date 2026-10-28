# VPN reliability: controller plan

## Decisions and boundaries

- This Linux machine is the initial acceptance environment: the user reports it
  has the strongest restrictions. Defer Android/Windows work until this path works.
- Target YouTube 1080p, Twitch 1080p60 viewing, and stable Discord voice.
- The existing Cherry-hosted test VPN may be used for experiments. Discover its
  actual running configuration before proposing changes; do not provision a new VPS.
- No small traffic quota is required: ISP traffic is unlimited and VPN allowance
  is approximately 5 TB. Record consumption and estimate each campaign's cost;
  use finite durations, rate/concurrency limits, cancellation, and disk limits.
- This session coordinates; separate implementation sessions return changes and
  evidence for user review. No deployment, credential rotation, active-client
  changes, or publishing from the controller session.

## What repository inspection established

Initial observations below are corrected by the Package 1 runtime snapshot in
`INVENTORY.md`; use it, reviewed `PACKAGE-1b.md`/`PACKAGE-2.md`/`PACKAGE-2b.md`,
the controller findings in `PACKAGE-3.md`, and `CONTRACT-v1.md` for implementation. Runtime must be rechecked before experiments. No sustained
measurements exist yet.

- `playbooks/naiveproxy/check.py` already compares isolated SSH/VLESS/Naive
  processes, but uses small HTTPS requests, machine-local input paths and a shared
  routing base. It has no sustained-transfer, UDP, or actual media acceptance test.
  Parallel routes can also compete for capacity and affect each other's results.
- `playbooks/sing-box-configs/README.md` records SSH/Naive successes and a VLESS
  timeout despite TCP reachability. Reproduce this; do not treat an open port or
  a valid JSON config as a working tunnel.
- nt1 protocols share one exit, but Package 1 verified Cherry is a separate host
  with three configured routes. Workstation SSH hops do not add independent exits.
  Neither host's present tunnel connectivity has been qualified.
- Current SSH and deployed Naive paths do not relay UDP. Upstream Naive's optional
  UDP-over-TCP requires compatible server support; a client flag alone cannot add it.
- The Linux template is mixed-only, but the running service loads a local TUN/
  nftables fragment intercepting UID 1000. The active selector was SSH, which
  cannot relay the captured UDP. Proxy flags and route lookups alone do not prove
  an unnested path. HTTP requests cannot qualify normal Discord UDP routing.
- Profile hosting/update transport is documented as working. Package 1 found a
  different installed updater active, not the repository updater. Neither is
  established to check semantic connectivity. Inventory the actual updater and
  detect environment changes during runs; do not stop it without approval.
- Local tools inspected: sing-box 1.14.2 with Naive/QUIC support, curl 8.22.0
  with HTTP/2 and HTTP/3. iperf3 was not found on PATH. Recheck in each session.
- Package 1 verified maintained tracked Cherry and vpn-probe source now exists.
  Reuse it, preserving existing small-request tools. Cherry uses an explicit
  private outbound export; the profile Vault alone does not contain its routes.
  Do not expose Terraform state or private credentials.
- Existing user edits in `.gitignore` and `.ansible-lint` must be preserved.

## Corrected order

1. Inventory the actual path and agree on the measurement contract. Package 1
   is reviewed as a snapshot, with launch/DNS amendments in `CONTRACT-v1.md`.
   Package 1b is now reviewed: baseline DNS diagnosis and transient-worker launch
   completed with user approval, without production changes. See `PACKAGE-1b.md`.
2. Package 2b commissioning/cleanup is reviewed. Same-host endpoint readiness
   passed after three runtime fixes; failures remain in its ledger. No endpoint
   remains. Package 3r corrections are reviewed. Package 3b's approved attempt
   aborted before gate release; cleanup passed and no workload requests ran.
   Package 3b-r controller helper is implemented, but review found a startup
   envelope mismatch. Next is 3b-r2: narrow actual writer/reader integration
   correction, before any fresh smoke approval. No sustained campaign.
3. Add real destination/media tests and an explicit UDP path, on this machine.
4. Run baseline and repeated campaigns; reproduce degradation before changing protocols.
5. Audit configurations and run controlled protocol/DPI-related experiments.
6. Publish only a qualified candidate, with canary and semantic rollback.

DPI investigation starts with a configuration audit early, but protocol tuning
must not replace baseline measurement. A passing run means observed availability
under tested conditions, never proof of invisibility to DPI.

## Measurement design

### Separate the legs

| Path | What it helps isolate |
| --- | --- |
| This machine -> controlled HTTPS/UDP endpoint, direct | Local ISP/path baseline, with actual underlying routing verified |
| This machine -> one explicit VPN route -> controlled endpoint | Protocol and tunnel behavior under time/load |
| VPN host -> reference endpoint or real destination | Exit uplink, destination reachability, host resource limits |
| This machine -> same VPN route -> real media destination | End-to-end service usability |
| This machine -> normal application through a verified UDP path | Actual voice behavior, not proxy-only reachability |

The implemented reference was commissioned on TCP 9443/UDP 9444 and removed:
a private-CA/IP-SAN TLS control without DNS bootstrap. Its own-host loopback
readiness passed; external reachability/source rejection and capacity did not run. Its port, SNI and trust differ from public
HTTPS/VPN handshakes: do not call it a same-port DPI comparison. Its 900 s lease,
600 s UDP-session and 4 GiB object ceilings support commissioning/short screens,
not the 30-minute voice acceptance below. Longer qualification needs a later
reviewed design, not silent limit increases. Receipts expire with the process.

An endpoint on the VPN host measures access/tunnel behavior but does not exercise
that host's Internet egress. Complement it with a distinct controlled host if
already available, or real destination transfers. No unapproved new VPS required.
A server-side success does not prove the client's path is healthy.

### Isolation and evidence

- Select exactly one route per capacity test; compare routes sequentially with
  rotated/repeated ordering. Concurrent-route tests are separately labeled stress
  tests, not independent throughput benchmarks. Concurrent voice + video on one
  route is an intended workload.
- Use isolated sing-box processes with explicit outbounds, loopback-only listeners,
  private temporary credentials, independent state and reliable cleanup. Remove
  inherited direct destination rules and automatic selectors from test profiles.
- `--noproxy ''` and explicit proxy options prevent proxy-environment surprises,
  but do not bypass an existing OS TUN/VPN. Record route lookup, interfaces and
  active tunnels; establish the actual outer path before claiming an ISP baseline.
- Prove routing using outbound logs and endpoint-observed source where possible;
  record DNS resolution location and IPv4/IPv6 behavior. Source IP alone cannot
  distinguish protocols using the same exit. Never silently fall back to direct.
- Record inner application protocol and outer tunnel transport separately.
  UDP over TCP can work but may suffer head-of-line delays under packet loss.
- Capture wall-clock UTC and monotonic elapsed time, run/route/endpoint aliases,
  tool/build versions, sanitized config fingerprint, stage-specific errors,
  HTTP status, bytes, per-second goodput, TTFB, stalls, reconnects and recovery.
  Define timeout/error/unsupported/skipped outcomes; never drop failed samples.
- Separate startup/DNS/TCP/TLS/authentication failures from response errors and
  post-start degradation. Proxy timing fields do not always expose each leg:
  mark unavailable stages unknown, rather than inventing attribution.
- Keep raw JSONL incrementally flushed, a human summary, and a manifest. Report
  first/middle/last windows, time/bytes-to-first-failure, longest stall and
  reconnection time, not just average throughput or percentiles of successes.
- Sample host CPU, memory, OOM/restarts, interface drops and TCP retransmissions
  alongside runs. Existing Naive documentation describes a 64 MiB hard container
  limit: resource exhaustion is an alternative hypothesis, not automatically DPI.
- Keep credentials, profile URLs, signed media URLs, cookies, tokens, host keys,
  private IP mappings and packet captures out of committed/public artifacts.
  Use private mode-0700 output, mode-0600 files, and sanitized shareable summaries.

### DNS is a separate qualification axis

Package 1b reproduced the user's observation for YouTube A and AAAA: UDP returned
NXDOMAIN, whereas TCP and CA/hostname-verified DoH/DoT returned usable answers.
Positive/negative controls behaved as expected. The explicitly approved transient
worker was locally exempt from interception; no authenticated remote observer
was available. This is transport-dependent behavior in one short window, not
ISP attribution or sustained encrypted-DNS qualification. libc worked in that
worker/window, not proof that ordinary-user/application DNS is repaired.

Treat UDP/53 on the observed path as unsuitable for the tested YouTube lookups.
Direct DoH/DoT are bootstrap candidates, not a selected production resolver.
Independent tunnel bootstrap and per-route application DNS remain unqualified.
Keep the failed UDP evidence; no need for second-resolver/EDNS follow-up merely
to advance to endpoint implementation. Future probes need their own approval.

Test separately, preserving failed responses and timing:

- **System resolver:** libc/NSS behavior versus explicit DNS requests; record
  local cache/stub/forwarder provenance where known. Do not flush or replace it.
- **Direct DNS:** paired UDP/TCP A and AAAA queries to a small fixed resolver set,
  with automatic TCP fallback disabled for the UDP case; record RCODE, answer,
  authority, flags including TC/AD, TTLs, query options and timeouts. Include
  positive controls and an expected NXDOMAIN control; compare EDNS separately.
  NOERROR can be NODATA; require usable answers for positive controls. CDN answer
  equality is not required. AAAA lookup does not require IPv6 connectivity.
- **Direct DoH/DoT:** certificate- and hostname-verified encrypted resolver access,
  with explicit independent bootstrap addresses or reviewed bootstrap resolver.
  Preserve SNI/hostname validation; never disable TLS verification or silently
  fall back to plaintext. Test reachability over time, not one successful query.
- **VPN DNS:** make an explicit DNS request through each tested route, with proof
  of transport and selected outbound. TCP-based DNS/DoH/DoT can exercise SSH;
  ordinary UDP DNS additionally requires a verified UDP-capable route. A DNS
  resolver on the exit is distinct from an external resolver reached via VPN.
- **Destination resolution:** verify what resolves HTTP CONNECT destinations or
  TUN application names. Fetching DoH through a tunnel does not itself configure
  application DNS. Resolver IP evidence alone cannot prove the tunnel protocol.
- **Tunnel bootstrap:** resolve VPN server and encrypted-resolver hostnames without
  needing the failed tunnel. Existing IP-based outbounds can be controls, retaining
  the expected TLS/REALITY name and verification. Never pin arbitrary observed
  answers or make production changes as a diagnostic shortcut.

Record two axes: diagnostic completion and DNS usability. An observed NXDOMAIN/
SERVFAIL/timeout is valid diagnostic evidence, not a passed usable resolver. Keep
bootstrap failure distinct from destination failure; never collapse DNS into a
throughput failure or silently switch resolvers/families. The final design must
include independent bootstrap and qualified destination DNS, not merely a healthy
VPN port. Direct encrypted DNS remains observable/restrictable by IP/SNI and is
not guaranteed to survive filtering.

### Workload ladder

1. **Preflight:** config/core capability, actual route, DNS, TCP/TLS, known HTTP
   response, observed exit, and controlled endpoint health. Retry boundedly and
   preserve failures; do not require success to write a report.
2. **Screen:** repeated fresh connections and a continuous noncompressible HTTPS
   transfer, long enough to exceed any initial burst. Reject HTML error pages,
   unexpected lengths, redirects to unrelated origins and cached/compressed fake
   throughput. Persist progress even when the transfer stalls or times out.
3. **Sustain:** 10-15 minutes per candidate, single long-lived transfer plus a
   separate repeated-object/segment workload; 1 connection first, then a bounded
   fan-out (e.g. 4). Record actual outer connection reuse rather than assuming
   a new curl process creates a new tunnel connection.
4. **Cooldown/recovery:** after failure, probe with bounded spacing and a later
   fresh attempt. Preserve time since last load. Do not continuously hammer an
   endpoint and thereby hide a temporary block's recovery.
5. **Services:** 30-minute YouTube and Twitch playback at pinned target quality,
   recording startup, quality changes, buffer/rebuffer events, segment deadlines
   and service-specific errors. Repeat with fresh media sessions. Real CDN media
   traffic is required; fetching the service homepage is not acceptance.
6. **Voice:** 30-minute bidirectional sequence-numbered UDP test, unloaded and
   during same-route streaming/load, followed by an actual Discord voice call.
   Record loss, reordering, RTT distribution, inter-arrival jitter (define the
   estimator), consecutive loss and longest receive gap. Do not infer one-way
   latency from unsynchronized clocks or mistake DNS/STUN success for media.
7. **Soak:** qualify finalists over 1-2 hours and repeat in multiple time windows,
   including busy hours. Do not run all protocols at full rate simultaneously.

HTTP/3 testing is separate from UDP relay testing. curl through HTTP CONNECT does
not establish arbitrary UDP/QUIC support. iperf3 also does not natively use a SOCKS
proxy: it needs an explicitly verified TUN/routed path. A SOCKS5 UDP-associate
probe is a possible isolated alternative if the installed core supports it;
verify it rather than assuming it works. Normal Discord still needs an application
UDP path, potentially an approved temporary TUN/netns setup. Do not switch this
machine's default routes as a side effect of running diagnostics.

## Initial acceptance hypotheses (tune against measured streams)

These are proposed engineering targets, not vendor guarantees or existing results.

- Controlled downlink screen: at least 10 Mbit/s in sustained 10-second windows
  after warm-up, with stall windows counted. Use actual chosen media bitrate plus
  50-100% headroom for the final workload, not this fixed screen alone.
- YouTube 1080p and Twitch 1080p60: start within 10 seconds; no post-warm-up
  rebuffering or involuntary quality reduction over a 30-minute run. Distinguish
  unavailable source quality, ads and authentication challenges from tunnel errors.
- Synthetic voice: loss <1%, p95 RTT <200 ms, defined jitter target <30 ms,
  no receive gap >200 ms after warm-up, both unloaded and under video load.
  A real two-way Discord call must also pass; synthetic results alone are insufficient.
- Failures are classified as transport, destination-policy/application, unsupported,
  route-unverified, or inconclusive. A 403/challenge is not automatically packet loss.
- A missing UDP route disqualifies a candidate as the sole all-service solution,
  even if it remains useful as a TCP fallback.
- Repeat results before promotion. Keep conclusions scoped to this ISP, machine,
  protocol/build, endpoint and observation window.

## DPI-related audit and experiments

Inventory the actual Cherry and nt1 protocol/transport/flow/TLS/REALITY parameters
privately; do not assume the user's "VLS" identifies a complete configuration.
Check client/server compatibility, time sync, SNI/target reachability, authentication,
REALITY keys/short IDs, flow and UDP encoding, fallback behavior, DNS/bootstrap,
ports/firewalls, MTU and server resources before blaming filtering.

Compare ordinary valid HTTPS and tunnel traffic to controlled infrastructure;
inspect handshake metadata and outer connection patterns if capture is approved.
Test fresh vs reused connections, low vs higher concurrency, duration and volume,
then cooldown. Vary one factor at a time. Same-host/port comparisons may be
confounded by different services; explicitly document that limitation. Endpoint/IP,
ASN, port and time effects must not be mistaken for protocol effects.

Start with existing VLESS/REALITY and Naive as available; retain SSH as a TCP
control, not a promise of DPI resistance. Propose additional protocols only when
an observed failure suggests a testable improvement and sing-box compatibility is
established. Do not add a protocol zoo or blindly copy fragmentation/mux/SNI recipes.
All changes need review, rollback, host health checks and preserved admin access.

## Distribution gate

Only after an end-to-end candidate passes: update Vault-backed source connections
and generator/tests, preserve stable enrollment URLs, validate matching installed
cores, canary this machine and test refresh while connected and disconnected.
Exercise unreachable hosting, invalid profile, healthy process but broken tunnel,
and candidate rollback. Preserve a last-known-good profile and independent recovery
path. A semantic health check needs explicit route identity and bounded retries to
avoid oscillation. Broader duckdns.org bypass and direct rule-set/DNS dependencies
need review; do not broaden bypasses or enable automatic route switching blindly.
An independent exit server is a separate reliability decision from adding protocols.

## Evidence and review workflow

Use `PROMPTS.md` one work package at a time. Every session returns changed paths,
commands/tests, sanitized results, unresolved limits and rollback instructions.
Do not auto-commit or publish. Run `uvx prek run --all-files` after changes plus
focused unit tests. Bring the report back to the controller before the next gate.

Status: Packages 1/1b/2/2b reviewed within their documented scope. Package 2b
same-host readiness and complete teardown are accepted; all failed attempts and
identity-sampling limitations remain explicit. Runtime fixes cover nft host
literals, strict systemd credential loading and real HTTPSConnection cleanup;
descriptor expiry is implemented. Independently reran 60 tests and hooks: passed.

Package 3r is now accepted after review of deadline/error attribution, nine new
boundary regressions and the corrected container-source proposal. Independently
reran 103 tests and repository hooks: passed. The original reproduced bug and all
failed iterations remain documented. The code-review hold is cleared; execution
approval is not granted by this review.

Package 3b: one exact container /32 and lease were approved; endpoint installation
and inspection passed, but private-controller polling attempted JSON decode of
an empty initial poll. The worker was stopped before release, with zero workload
requests. Teardown/production preservation are documented. Raw worker artifacts
were not collected before runtime deletion: this is explicit evidence loss, not
an invented raw route-unverified result. See PACKAGE-3b.md.

Package 3b-r added a tracked readiness/collection helper and 26 offline tests;
controller independently reran all 129 tests and hooks: passed. However, actual
screen.Artifacts startup rows reproduced a new interoperability blocker: the
reader rejects the initial unselected run-start before the valid ready event.
Its fixture-only tests did not cover the actual runner's startup envelope.

Next: Package 3b-r2 narrow startup-contract fix and writer/reader integration
regression, then review before a fresh lease/retry. Keep strict ready identity,
pre-input failure artifacts and the new bounded polling/teardown behavior.
No network/protocol repair is indicated by these orchestration defects.
Source derivation is time-bounded and not yet confirmed by a receipt. No endpoint
or reusable credentials remain. No workstation reachability,
external source rejection, VPN path/DNS/UDP relay, capacity calibration, sustained
campaign or production DNS migration is qualified yet. The user's full test-node
access authorization during readiness is recorded in Package 2b; it is not an
assumed approval for new workstation paths, sources, load or production changes.
Recheck runtime context and validation before future experiments.

## Research sources

Reviewed 2026-10-26; sources are hypotheses/specifications, not local measurements.

1. [Cloudflare: Russian Internet users are unable to access the open Internet](https://blog.cloudflare.com/russian-internet-users-are-unable-to-access-the-open-internet/)
   (2025-06-26): observed approximately 16 KB transfer limits for affected
   Cloudflare paths. Does not establish the mechanism on this ISP or arbitrary VPSs.
2. [net4people #490](https://github.com/net4people/bbs/issues/490): community
   reports of initial-data-then-stall behavior; varying hosts/ISPs, not a universal threshold.
3. [net4people #546](https://github.com/net4people/bbs/issues/546) (opened
   2025-11-14): separate TLS policing reports, load/concurrency and cooldown
   symptoms; later updates contradict early universal workaround suggestions.
4. [XTLS/REALITY](https://github.com/XTLS/REALITY): upstream design/configuration;
   design goals do not demonstrate invisibility or availability on our path.
5. [sing-box VLESS](https://sing-box.sagernet.org/configuration/outbound/vless/)
   and [Naive](https://sing-box.sagernet.org/configuration/outbound/naive/): UDP
   capability, runtime requirements and transport-specific settings. Naive warns
   that extra tunnel concurrency changes traffic-analysis properties.
6. [Discord voice connections](https://docs.discord.com/developers/topics/voice-connections):
   bidirectional UDP voice requirement. Use a current real client for acceptance,
   not a new custom Discord implementation; generic WebRTC/STUN is not equivalent.
7. [YouTube playback troubleshooting](https://support.google.com/youtube/answer/3037019?hl=en):
   5 Mbit/s reference for 1080p, not a guarantee for every codec/frame rate.
8. [Twitch broadcasting guidelines](https://help.twitch.tv/s/article/broadcasting-guidelines?language=en_US):
   6 Mbit/s reference for 1080p60 encoding, not a universal viewer requirement.
   Measure the actual viewing rendition and buffering behavior.
9. [iperf3 invocation](https://software.es.net/iperf/invoking.html): interval
   reporting, reverse direction, UDP and JSON output; routing still needs verification.
