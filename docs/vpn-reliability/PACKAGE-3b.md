# Package 3b — bounded live attempt; stopped before traffic

**Outcome: inconclusive smoke; controller readiness polling failed. Teardown verified.**
One approved fresh lease was installed and inspected. One gate-held fresh worker
launch was cancelled before release. No smoke requests ran; continuous and
segments were not launched. No retry, renewal, sustained campaign, production
change, commit or publication followed. This is not a VPN failure or a passing
runner commissioning result.

## Controller review

Accepted as an **aborted, inconclusive attempt with documented cleanup**, not a
runner commissioning pass or VPN failure. Controller reviewed this sanitized
report without rereading private evidence or running live commands. Independently
reran 75 probe + 28 reference tests (103 total): passed. Those tests do not cover
the session-private controller defect.

The current container-source derivation is useful, time-bounded preflight evidence;
it is not authenticated endpoint receipt evidence or permission to reuse a lease.
Actual worker identity/underlay and all three workloads remain unverified/not run.
No raw worker outcome can be reconstructed from launcher success or missing files.
Preserve the evidence-loss limitation and all original attempt records.

Next is Package 3b-r, local controller hardening only: move the minimal readiness
polling and partial-artifact collection paths into a small tracked helper with
offline regressions. Missing/empty/blank/incomplete JSONL is pending until a bounded
deadline; malformed complete records, read failures and early exit are distinct.
Attempt bounded collection of existing allowlisted artifacts before deleting the
dynamic runtime. Collection failure must never prevent teardown; missing files
remain missing/incomplete, not invented summaries. Do not copy credentials/core
configuration or broaden permissions for collection.

Return the corrected/tested controller procedure for review before requesting any
fresh lease or retry. Old one-lease approval is consumed, not reusable. No runner,
VPN, DNS, routing or endpoint-cap change is indicated by this pre-gate failure.

## Approvals and exact scope

The user separately selected:

1. **Approve read-only**: bounded pinned Cherry/workstation inspection, <=180 s
   each and <=16 MiB private evidence; no discovery probes or changes.
2. **Permitted unchanged**: operator confirmation that provider policy permits
   the temporary native TCP 9443/UDP 9444 endpoint/path without provider changes.
   This is not an independent provider-policy audit.
3. **Approve exact plan**: after the derived source was presented in an owner-only
   local file, authorize precisely its sole container `/32`, one <=900 s lease,
   PACKAGE-3.md's DynamicUser/gate/watch/collection procedure and own-resource
   teardown. No host `/32`, bridge subnet, direct fallback or additional sources.

Exact private bind/source/worker/load plan:
`/tmp/vpn-screen-3b.1cmGnWvN/EXACT-APPROVAL.json`, SHA-256
`a8e6848904f8adf55137b64c1ee8640b377fcff27f791b008e0d237ed2c7c111`.
Addresses and credentials are deliberately omitted here. Approval covered these
sequential cherry-vless invocations, not a campaign:

| Workload | Duration | Aggregate rate | Client body cap | Actual execution |
| --- | ---: | ---: | ---: | --- |
| fresh | 5 s, <=12 requests | 262144 B/s | 1 MiB | Gate-held launch only; cancelled |
| continuous | 5 s | 262144 B/s | 2 MiB | Not launched |
| segments | 12 s | 1048576 B/s | 16 MiB | Not launched |

Total approved client-read bodies <=19 MiB, including controls; not a wire/billing
cap. Endpoint limits were unchanged. No host-local readiness, direct client,
source-discovery, DNS or UDP probe was authorized/run in this attempt.

## Read-only source and route preflight

Pinned SSH used the existing Cherry inventory, dedicated administrator key and
known-host file, strict key checking, key-only authentication, no forwarding,
no ProxyCommand/ProxyJump, finite timeouts and cleared proxy environment.
Privileged inspection remained in the controller, not the network worker.

- Actual server core: sing-box PID **3954**, namespace distinct from the host,
  in `vpn-node-vless-1`, bridge network `vpn-node_default`. Process command/start,
  UID **999**, container identity, attached address/gateway and namespace links,
  routes, rules, sockets and policy were inspected. Server outbound is one direct
  outbound with no source binding, detour or mark; route final is direct.
- Namespace TCP/9443 destination lookup, also repeated for actual UID 999,
  selects the container's exact IPv4 via eth0/bridge gateway. Host destination
  lookup is local. Host/native and namespace nftables, nft-backed IPv4/IPv6
  iptables and empty legacy backends establish a host INPUT path: no matching
  9443 DNAT or source translation. Internet-egress POSTROUTING masquerade does
  not establish the source of this locally delivered connection.
- Therefore the required source is the **container `/32`**, distinct from the
  assigned host bind/configured public exit IPv4. No public egress-discovery
  request was sent. This is read-only source derivation, **not endpoint-observed
  source corroboration**: no authenticated receipt was obtained.
- Native/Docker/NAT ownership had no 9443/9444 conflict. Existing
  SSH/Naive/VLESS/monitoring listeners and container identities were recorded;
  no current OOM flag or restart change was observed. Approximately 460 MiB host
  memory was available at preflight. Provider permission was operator-confirmed.
- Workstation retains UID-1000 TUN interception and the active installed updater.
  All three relevant output interception chains return non-1000 UIDs; complete
  rules/routes, Docker/libvirt policy, priority-1 local table and late TUN fallback
  were inspected. Underlay tc filters were empty; no XDP attachment was reported.
  **No actual smoke-worker UID/underlay exemption was verified**, because the
  launch stopped before its ready event and actual-Python-PID inspection.
- Local tools: Python **3.14.8**, curl **8.23.0**, sing-box **1.14.4**, systemd
  **262**. Remote endpoint tooling and clock synchronization were rechecked.

An initial local read-only collector failed on `/proc/0/ns/net` for a container
without a live PID. A corrected read-only snapshot skipped that non-live process
and completed. The failure is retained; this was not a lease/workload retry.

## One-lease action ledger

Times are **2026-10-27 UTC**, from retained controller records.

| Time | Action/result |
| --- | --- |
| 22:40:54 | Prepare `smoke-3b-r1` once using reviewed `reference/prepare.py` |
| 22:41:27 | Reviewed standalone Ansible installation returned 0 |
| 22:41:28 | Endpoint process/sandbox, exact guard/source and binding inspection passed |
| 22:41:28 | Fresh handoff prepared offline; reviewed gate-held worker launched |
| 22:41:28 | Readiness poll failed; gate remained absent; only own worker stopped |
| 22:41:28 | Worker unit/runtime/identity/staging cleanup verified |
| 22:41:38 | Standalone reference teardown returned 0 |
| 22:41:40 | Reference absence and production-preservation comparisons passed; fresh material unlinked |

Lease expiry was **22:55:54**, 900 s from preparation, not service start. Teardown
returned about **44.6 s** after preparation began; verification/material removal
finished about **46.6 s** after preparation. No lease was restarted or renewed.
The reviewed 600 s launch cutoff, <=240 s teardown and <=60 s verification bounds
were not approached.

Actual install/teardown commands used the reviewed playbook and private vars:

```sh
python playbooks/vpn-probe/reference/prepare.py \
  --output "$CONTROL/lease" < "$CONTROL/approved-plan.json"
ansible-playbook -i infra/cherry-vpn/private/inventory.yaml \
  playbooks/vpn-probe/reference-deploy.yaml -e "@$CONTROL/install-vars.json"
# In finally, including after the failed gate-held launch:
ansible-playbook -i infra/cherry-vpn/private/inventory.yaml \
  playbooks/vpn-probe/reference-deploy.yaml -e "@$CONTROL/teardown-vars.json"
```

Ansible used strict pinned authentication, private bounded connection reuse and
pipelining. No production deployment or package installation was invoked.

### Endpoint inspection that did pass

Actual endpoint PID **71133**, separate DynamicUser UID **64662**, only its primary
group, zero capabilities and NoNewPrivs=1; host network namespace and no proxy
environment. Exact approved bind/source/run/expiry matched prepared configuration.
Only that bind's TCP 9443 and UDP 9444 listeners belonged to this PID. Spent marker
was present. The loaded own input guard had the single approved host literal,
priority -10, two source-return and two unmatched-drop rules; all four counters
were zero at this inspection, before the worker launch.

Loaded resource/sandbox properties matched the reviewed endpoint: 192 MiB RAM,
no swap, 75% CPU, 24 tasks, 64 FDs, 2 MiB file ceiling, 900 s runtime, no restart,
strict system/home protection and no-new-privileges. This establishes installed
endpoint context, not HTTPS usability, source rejection or serving capacity.

### Failure and missing evidence

The **session-private controller helper**, not `screen.py`, polled readiness with
`print(file_contents_if_present_else_empty)`. Its first empty poll produced a
blank line; the controller attempted `json.loads` on that blank line and raised
`JSONDecodeError: Expecting value`. This was a local orchestration defect, before
ready-event/Python-PID validation or gate release. No source/policy/transport
failure was diagnosed. No implementation was fixed or retried after this failure.

The launch log records only **32 ms** service runtime, stop by **SIGTERM**, and a
systemd result of success. That result is **not a runner or smoke pass**. The
actual post-exec Python PID/UID was not sampled. No gate-release action occurred;
reviewed runner code does not start a network child before that gate.

**Evidence loss:** cancellation removed the dynamic runtime before any runner
manifest/JSONL/summary could be archived. The controller did not preserve possible
partial worker files on this startup-error path. Launcher/poll/error/cleanup logs
remain, but no raw runner outcome or complete manifest can be reconstructed.
There are no request rows, verified objects, positive continuous bytes, complete
segments, receipts or selected-outbound/socket observations to assess. Do not
replace these missing records with an invented raw `route-unverified` result.

## Separate route assessment and traffic accounting

**Live route unverified / smoke inconclusive.** Source derivation and endpoint
inspection passed; actual worker identity, underlay sockets, selected outbound
log and authenticated endpoint source were not observed. The per-second local
and five-second remote workload watchers never started; before/after equality
cannot exclude transient changes. No throughput, DPI,
DNS, UDP relay, media or Internet-egress conclusion follows. The endpoint is on
the VPN host with distinct-port/IP-SAN/private-CA trust; these remain confounders.

Smoke application requests/client-read bodies: **0 / 0 bytes** (gate never
released). This is not a packet-level capture. Shared before/after NIC deltas:

| Host/interface | Received bytes | Transmitted bytes |
| --- | ---: | ---: |
| Workstation Ethernet | 47652952 | 9106021 |
| Cherry public interface | 8025638 | 386528 |

These include SSH/deployment and unrelated traffic; they are not per-route
transfer totals or provider billing. Per-test wire overhead/provider consumption
is unknown. Preparation streamed a local 4 GiB hash without transferring/storing
a 4 GiB payload. No further load or recovery probe was sent.

## Verified teardown and preservation

Always-run cleanup completed, including after the startup failure:

- Local `vpn-screen.service` collected/not-found, MainPID=0; no worker cgroup,
  process, dynamic account, runtime, credential mount, staging or release path.
- Remote endpoint/guard/smoke units not-found, MainPID=0; no reference listeners,
  processes, cgroups, dynamic accounts, credentials/mounts, installation/unit
  files, replay/state directories or `inet vpn_reference` table.
- Complete non-reference semantic nft policy, legacy/iptables policy, IPv4/IPv6
  routes/rules, link/address identity and relevant config/resolver/updater
  metadata matched baseline. Counters/DHCP lifetimes were excluded from semantic
  comparisons, not interpreted as material changes.
- Preserved remote SSH/VPN/monitoring listener ownership, SSH/Docker state and
  container IDs/PIDs/start/restart/OOM/network context matched baseline.
  Workstation production core identity and updater state/metadata matched.
  These are process/policy preservation checks, not end-to-end VPN health tests.
- Fresh lease keys/config/descriptors/CA and selected handoffs were unlinked;
  own SSH control connections closed. Original private export/key/pins were not
  modified. Unlinking does not guarantee secure storage erasure.

## Artifacts, validation and next gate

Only repository addition by this session: **`docs/vpn-reliability/PACKAGE-3b.md`**.
No runner, endpoint, deployment or production source was changed. Existing
modified/untracked package/user files were preserved; source hashes still match
the code used for execution.

Private evidence locator: mode-0600 `/tmp/vpn-screen-3b-controller-path`, pointing
to the directory above (approximately 1 MiB before validation logs). Directories
are 0700, files 0600. It retains approval, read-only snapshots, exact one-use
controller commands, source hashes, failed launch/poll traceback, install/
teardown logs and absence/preservation/accounting evidence. Private mappings
must not be committed or pasted; no reusable lease credentials remain. Temporary
storage is not a durable archive. Retain evidence privately before `/tmp` cleanup.

Validation executed:

```sh
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe/reference -p 'test_*.py'
uvx prek run --all-files
uvx prek run --files docs/vpn-reliability/PACKAGE-3b.md
git diff --check
```

Focused tests: **75 probe + 28 reference = 103 passed**, both before live
execution and again at final validation. They include temporary loopback TLS
fixtures, not live Cherry traffic; they did
not test this session-private controller's empty readiness poll.
`uvx prek run --all-files`, explicit report hooks and `git diff --check` all
**passed** after writing the report. No suppressions or unrelated fixes were added.

**Stop for review.** Any follow-up needs explicit scoped authorization: correct
empty/not-yet-written readiness handling and partial-artifact collection before
stopping the dynamic runtime, validate those controller paths offline, then
request a fresh lease/attempt with current exact source/worker/load approval.
Do not rerun objects, renew this lease, broaden sources or change production to
manufacture a pass. Continuous/segments, calibration and all later packages
remain unexecuted.

Rollback: no live resources remain to roll back. Remove only this new report if
rejected, preserving all pre-existing work. After private evidence review, delete
only the exact locator-named controller directory and locator; no production
rollback or credential rotation is required.
