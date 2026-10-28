# Package 2b — temporary endpoint commissioning

**Same-host readiness passed; cleanup verified. STOP at review gate.**
The first attempt was inconclusive. With subsequent explicit user authorization,
follow-up attempts exposed and fixed three runtime bugs. The final fresh lease
passed installation, endpoint identity/sandbox/guard/binding inspection, six
HTTPS operations and one authenticated UDP exchange. All temporary resources
were removed. This is not VPN/ISP, external filtering or throughput qualification.
No sustained runner or production VPN/DNS/profile changes were made.

## Controller review

Accepted for the documented same-host commissioning and cleanup scope. Controller
reviewed the attempt ledger, runtime corrections and sanitized evidence; no live
commands were repeated and private raw evidence was not reread. Independently
reran 28 reference + 32 probe tests (60 total) and repository hooks: all passed.
No blocking finding for advancing to runner implementation/offline validation.

Failed attempts remain failures. The missed post-exec smoke identity sample is
explicitly limited, not promoted to verified process evidence. Endpoint identity,
loaded guard, allowed local traffic and teardown are documented; external source
rejection, workstation routing and serving capacity remain unqualified.

Next: Package 3 runner implementation and deterministic/local integration tests,
not live throughput. Implement/test exact descriptor expiry and scoped trust,
separate small preflight inputs and bounded final-receipt collection. Use real
library/subprocess boundaries in selected local tests so permissive mocks cannot
hide another runtime incompatibility. Return PACKAGE-3.md plus a concrete new
lease/worker/finite-smoke proposal; stop before execution for review. Commissioning
credentials are gone. Past readiness authorization is not approval for a new
workstation path, source expansion or sustained campaign.

## What was installed and what readiness means

A temporary native Python service on the existing Cherry test node:

- TCP **9443**, scoped-CA/IP-SAN HTTPS serving known finite noncompressible data.
- UDP **9444**, authenticated registered-session 96-byte echo.
- Its own source-guard nft table, short-lived credentials and bounded systemd
  units. No VPN software, new VPS, reverse proxy, system trust or DNS changes.

Readiness checks the endpoint itself: verified TLS, a complete 4096-byte object's
length/hash, bad-token and replay rejection, authenticated object receipt,
UDP-session registration, one HMAC-verified echo and direction-count receipt.
It does not test a tunnel, Internet egress, sustained transfer or media/Discord.
The endpoint was deliberately removed after the check, not left running.

## Approval and execution boundaries

1. User approved bounded pinned read-only Cherry SSH preflight. Provider policy
   was initially unknown, so installation stopped pending clarification.
2. User explicitly selected **“Provider permits it”** and **“Approve one lease”**
   after the exact private bind/source plan and install/readiness/teardown plan
   were presented. Provider permission is operator confirmation, not an API audit
   or assurance about variable ISP filtering.
3. The first install timed out, was torn down, and was reported inconclusive.
   When asked about further investigation, the user then authorized:
   **“You have full access to test node on Cherry servers, You can do whatever
   you need to do to prepare readiness.”** This subsequent authorization covered
   the corrective follow-up below; it was not treated as production VPN/DNS,
   sustained-load, external-source or profile-publication permission.

Host/account: existing `cherry_vpn_test` inventory and `vpnadmin`, dedicated
administrator key and known-host pin. Raw mappings/keys were not printed.
All attempts used the inventory IPv4 as the bind and **only that same IPv4
as one `/32` source**. No workstation/nt1 source, wildcard, subnet broadening,
public-address discovery, external negative-source test or provider rule change.
Each attempted install had fresh tokens/certificates, a new run alias and the
unchanged **900 s lease from preparation**; no lease was restarted/reused.

SSH used strict pinned/key-only authentication, `-F /dev/null`, BatchMode,
IdentitiesOnly, ConnectTimeout=8, no agent/port forwarding. Initial Ansible
connection reuse was disabled; follow-up used a private per-invocation control
socket, 60 s persistence and pipelining. Inherited proxy variables were cleared.
Administrative SSH is not measurement-path evidence.

## Changes

- `playbooks/vpn-probe/reference/prepare.py`: all three descriptors now include
  integer Unix UTC `expires_at`, directly equal to server `config.expires`.
- `reference/test_endpoint.py`: fixed-clock descriptor equality tests, nft host
  rendering regression and strict credential-loading positive/negative tests.
- `reference/firewall.py`: render validated `/32` inputs as **single host literals**
  in the plain nft `ipv4_addr` set. No interval/broader source allowance.
- `reference/endpoint.py`: separate systemd credential loading from controller
  input loading. This host supplies root:root `0440` credentials with a read ACL
  for the dynamic UID. Accept only the selected `config.json` in the absolute,
  non-symlinked, read-only credential mount, safe ownership/group/mode and size.
  Controller `private_json` still requires owner-only inputs; deployed originals
  remain root-owned 0600. No permission widening or system trust-store change.
- `reference/smoke.py`: use `contextlib.closing` for HTTPSConnection, which has
  no context-manager protocol. Add stage/status/count and redacted receipt
  evidence; never echo bearer/session keys, addresses, bodies or raw errors.
  Original assertions, six-operation/one-packet counts and deadlines remain.
- `reference/test_smoke.py`: fake-network success/failure evidence tests plus a
  real HTTPSConnection constructor/close regression with connect mocked out.
- `playbooks/vpn-probe/reference-deploy.yaml`: skip redundant preview for a new
  installation, retaining changed-file refusal for an active lease. Teardown
  clears retained failure state **only for the two removed reference units**.
- `reference/test_deployment.py`: test those deployment/teardown boundaries.
- `docs/vpn-reliability/PACKAGE-2.md` and this report: metadata/runtime amendments.

Here `reference/` abbreviates `playbooks/vpn-probe/reference/`. All pre-existing
user edits and previously untracked Package 2 files were preserved; no commit.
No lifetime, RAM/CPU/task, object/rate/byte, request/session or UDP caps changed.

The future runner must accept `expires_at`, record expiry/remaining lifetime and
reject insufficient lifetime as an endpoint constraint, not a tunnel failure.
That runner was not implemented.

## Preflight and diagnosis

Initial read-only snapshot: **2026-10-27 18:47:59 UTC**, collection about 0.52 s.
A new baseline was taken at **19:36:27 UTC** for follow-up, and each attempt
rechecked policy/listeners/reference resources immediately before preparation.

- Bind IPv4 is assigned. Routing to it is `type local`, `dev lo`, same preferred
  source: local-loopback smoke, not Internet hairpin/egress/ISP testing.
- Native sockets, actual/configured Docker bindings/network modes, full nft and
  nft-backed IPv4/IPv6 iptables-save plus both legacy backends were inspected.
  Legacy rulesets were empty. No native/Docker/NAT conflict on 9443/9444.
- Existing Docker DNAT covered 80/443/8443 and monitoring 9273, not these ports.
  Existing SSH/VPN/monitoring listeners and production tables were preserved.
- SSH/Docker and both VPN containers were running; VPN restart counts were zero,
  no current OOM flag. Telegraf is present/running, unlike the older inventory.
- Tools: systemd **257.9**, Python **3.13.5**, nftables **1.1.3**, OpenSSL **3.5.7**.

Initial teardown logs retained useful evidence even though initial partial
install output was lost: two temporary directories had been created, but neither
unit file existed. Each ordinary remote operation took roughly 10–15 s, and
teardown itself took 123 s. A read-only `/usr/bin/true` Ansible transport check
with pipelining/reuse completed in **1.72 s**. One preliminary diagnostic CLI
invocation used an unsupported option and failed locally, before contacting the
host; corrected syntax passed. No endpoint lease was involved in that typo.

## Attempt ledger — failures retained, not converted to successes

All dates below are **2026-10-27 UTC**. Installation remained bounded to **240 s**
per attempt; follow-up stdout/stderr were written incrementally to private files,
with controller process-group TERM/KILL handling before cleanup on timeout.
Every attempt invoked the standalone teardown playbook in `finally`.

| Attempt | Start | Installation/readiness result | Cleanup |
| --- | --- | --- | --- |
| 1 | 18:55:28 | Install controller timed out at 240 s; exact task unknown because partial output was not retained. Smoke not run. | Exit 0; no live reference resources remained. |
| 2 | 19:38:12 | Install failed after 97 s: nft rejected `/32` prefix elements in a plain address set. Guard failed closed; smoke not run. | Exit 0; a dormant systemd failure record was subsequently cleared by the corrected teardown. |
| 3 | 19:45:31 | Install command returned 0 in 31 s, but endpoint exited before inspection. Strict controller-style file checks rejected systemd credentials. Smoke not run. | Exit 0. |
| 4 | 19:50:43 | Install 34 s, endpoint inspection passed. Smoke failed in 0.35 s with only the old generic failure output. | Exit 0; failure cause initially unknown. |
| 5 | 19:54:31 | Instrumented diagnostic: install 28 s, inspection passed; first smoke operation raised TypeError before HTTP response or any guard-counted packet. | Exit 0; no same-lease retry. |
| 6 | 19:59:32 | Install 29 s, inspection and corrected smoke passed; details below. | Exit 0 in 11 s; full sequence ended 20:00:26. |

Causes were reviewed between attempts; no auth/hash/receipt assertion or source
restriction was relaxed to get a pass:

- **Firewall:** read-only `nft --check` reproduced the prefix syntax failure both
  normally and in the actual guard sandbox. Both passed after host-literal
  rendering. No rules were applied by those syntax diagnostics.
- **Credentials:** an offline DynamicUser worker reproduced root:root `0440`
  credentials with a named worker read ACL. Config loading and private-state
  writing passed in that sandbox after the dedicated loader correction.
- **Smoke:** stage evidence isolated the failure to HTTPSConnection construction/
  context entry. A no-network worker reproduced it; the actual connection class
  lacks `__enter__`. The old MagicMock had hidden this. After `closing`, a worker
  with connect replaced by a deliberate exception reached that boundary without
  TypeError or packets, before the final live attempt.

The no-network diagnostics had finite transient units and private root staging;
only their own staging/state was removed. They did not launch VPN cores or
contact public test destinations. The first generic smoke failure remains a
failed sample, although later reproduction explains the same checker defect.

## Final successful lease and runtime evidence

Run alias **`commission-2b-r6`**. Preparation began **19:59:33 UTC**; expiry was
**20:14:33 UTC**, exactly 900 s from preparation. All three descriptor expiries
matched config expiry. Scoped CA/IP-SAN certificate verification passed locally
and remotely. No payload file or production certificate was used.

Only the reviewed standalone installation/teardown playbook was used:

```sh
python playbooks/vpn-probe/reference/prepare.py \
  --output "$CONTROL/lease" < "$CONTROL/proposed-plan.json"
ansible-playbook -i infra/cherry-vpn/private/inventory.yaml \
  playbooks/vpn-probe/reference-deploy.yaml -e "@$CONTROL/install-vars.json"
# Always, including partial installation or smoke failure:
ansible-playbook -i infra/cherry-vpn/private/inventory.yaml \
  playbooks/vpn-probe/reference-deploy.yaml -e "@$CONTROL/teardown-vars.json"
```

Private vars contained `reference_approved:true`, `reference_state:present` and
that invocation's `reference_private_dir`; teardown used `reference_state:absent`.
No source values or credentials were passed as command-line literals.

Before smoke, actual endpoint `/proc` and unit properties established:

- Separate non-root dynamic UID/GID, not production UID; only its primary group,
  all capability sets zero, NoNewPrivs=1, host network namespace, no proxy env.
- Active/running, no restart/boot enablement, spent marker present. Exact prepared
  metadata matched the remote lease. Only the reviewed IPv4 bound to 9443/TCP
  and 9444/UDP, both owned by this endpoint PID.
- MemoryMax **192 MiB**, swap 0, CPUQuota **750 ms/s**, TasksMax **24**, FDs **64**,
  output file limit **2 MiB**, runtime **15 min**. Strict system/home protection,
  private tmp/devices, ProtectProc, capability and privilege settings loaded.
- Own `inet vpn_reference` table had exactly one host source, input priority -10,
  expected TCP/UDP source-return and unmatched-drop rules. Actual-UID route
  lookups for both listeners were local via loopback with the reviewed source.

Smoke used the documented DynamicUser/systemd-run launch, **64 MiB**, **4 tasks**,
**60 s** runtime, no capabilities, no-new-privileges and empty supplementary-group
configuration. One successful run, elapsed **0.442 s**:

| Operation | Observed result |
| --- | --- |
| Bad bearer | HTTP 401, zero body |
| Fresh object | HTTP 200, 4096 bytes, correct complete SHA-256 |
| Replayed request ID | HTTP 409, zero body |
| Authenticated object receipt | HTTP 200; complete, 4096 bytes, source matched bind |
| UDP registration | HTTP 200, one session |
| UDP exchange | One 96-byte request and reply; HMAC/payload/sequence verified |
| Authenticated UDP receipt | HTTP 200; received=1, sent=1, source matched bind |

Six HTTPS operations total; response body sizes were **0, 4096, 0, 212, 230,
7698 bytes**, total **12236**. UDP was **96 bytes each direction**. These exclude
TLS/IP/administrative overhead. NIC/provider accounting was not collected and
is unknown, not zero. Preparation's local 4 GiB streaming hash is not a transfer.

Loaded guard counters increased from zero to **48 packets / 13849 bytes** on
allowed TCP and **1 packet / 124 bytes** on allowed UDP; both drop counters
remained zero. These are hook counters, not provider billing. They establish
that allowed local traffic traversed the loaded guard, **not that a disallowed
external source was rejected**. That negative-source test was not run.

Sampling limitation: the smoke `/proc` poll caught systemd's short pre-exec
root process, not the post-exec worker, so that sample is not claimed as worker
UID/capability evidence. Configured DynamicUser/privilege/resource properties
were captured; the successful smoke's first code gate rejects effective UID 0.
Endpoint process identity was directly verified separately as described above.
No direct-ISP or VPN route claim is made from this local-loopback check.

## Final cleanup and production preservation

Final remote scan: **20:01:30 UTC**. Verified absent:

- Both reference listeners; own installed/transient units, cgroups, accounts,
  credentials/mounts, source staging, installation files and replay/state paths.
- `inet vpn_reference`; no reference guard or marker left after lease teardown.
- Endpoint/smoke processes, Ansible modules and invocation-window remote Ansible
  temporary entries. The guard-check, startup-check and request-check units also
  showed `not-found`, `inactive`, MainPID=0, no credential/state remnants.

Against follow-up baseline, complete non-reference nft policy matched after
excluding counters/handles; legacy policy, IPv4/IPv6 routes/rules and address
identity matched. Native listener ownership, SSH/Docker PID/start state, Docker
IDs, process/start/restart/OOM state and bindings matched, including both VPN
containers and Telegraf. These are process/policy health checks, not end-to-end
VPN connectivity acceptance. No production service was restarted or changed.

All invocation controller directories, lease keys/config/descriptors and public
CA material were removed after retaining non-credential evidence. Own SSH control
connections were closed; no local Ansible process remained. Unlinking is not
secure storage erasure. No credentials are retained for reuse.

Private raw evidence is outside the repository, directories 0700/files 0600:

- Initial attempt: locator `/tmp/vpn-reference-2b-controller-path`.
- Follow-up attempts/diagnostics/final comparisons and source hashes: locator
  `/tmp/vpn-reference-2b-followup-evidence-path`, about **1.1 MiB**.

Both locators are owner-only. Context contains private address mappings and must
not be published. After review, delete only each locator's exact evidence
directory and locator. Temporary evidence is not a durable archive.

## Tests, limits and handoff

Executed focused tests and repository checks:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s playbooks/vpn-probe/reference -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s playbooks/vpn-probe -p 'test_*.py'
uvx prek run --all-files
# Also explicit --files over all changed package paths, and git diff --check.
```

Final results: **28 reference + 32 existing probe tests passed (60 total)**;
repository-wide hooks, explicit package hooks and diff whitespace checks passed.
Regression coverage includes exact expiry equality, nft literal rendering,
read-only credential/mode/group/path rejection without weakening controller
inputs, active-lease preview protection, own-unit failure reset, real HTTP
connection cleanup, receipt-active failure without retries, and UDP timeout
stage/count retention. Unit tests open no network sockets.

Commissioning is complete only for this tiny same-host test. Still **not run**:
external source rejection/reachability, workstation/ISP path, VPN routing/DNS,
UDP relay, throughput calibration, sustained TCP, media/Discord or IPv6 traffic.
The same-host endpoint does not exercise Cherry Internet egress. Distinct port,
IP-literal SNI/private-CA trust and local source behavior remain confounders.
A 75%-CPU Python service on this shared host may bottleneck later tests; the
passing smoke does not establish capacity. Keep 900 s lease, 600 s UDP session
and 4 GiB ceilings unchanged; later work needs a fresh separately approved lease.

Stop before Package 3/campaign/profile work. Rollback only this session's expiry
and runtime corrections, new smoke tests and documentation if rejected; preserve
previously existing Package 2/user files. Remote cleanup is already complete.
No auto-commit or publication occurred.
