# Package 3b-r — local controller polling and abort-evidence correction

**Local correction complete; STOP for controller review. No live retry authorized.**
Package 3b remains an aborted/inconclusive attempt with evidence loss. Its missing
worker records cannot be reconstructed. The old lease/approval is consumed.
No historical private evidence or credentials were read for this correction.

## Controller review — retry gate held for startup interoperability

Controller independently reran 101 probe + 28 reference tests (129 total) and
repository hooks: all passed. Source/report review accepted the bounded polling,
allowlisting and teardown approach, but reproduced a blocking writer/reader
contract mismatch not covered by the new fixture-only readiness tests.

`screen.execute()` emits run-start before read_inputs/envelope.update. Its actual
Artifacts writer therefore produces `run="unselected"`, `endpoint="unselected"`
and the selected route on that first row. `controller.record()` requires the
approved run/route/endpoint on every row, so poll_ready immediately returns
wrong-schema, before inspecting the later valid ready event.

No-network reproduction used screen.Artifacts with execute's exact startup
ordering: emit run-start/input, update the envelope, emit a valid expected
route-evidence/ready row, then call poll_ready. Result: wrong-schema, candidate
null, poll 1. No source configuration, secret, network or live unit was used.
Current tests build non-ready rows from READY with already-selected identity,
which misses the real writer's initial envelope.

Next is Package 3b-r2: align the initial startup-record contract narrowly and add
an offline writer/reader integration regression. A valid ready event must still
match the approved run/route/endpoint exactly; do not ignore arbitrary non-ready
identity mismatches or malformed records. Preserve pre-input failure artifacts
and distinguish terminal/invalid startup from pending. No new launch authority,
permission or resource change is needed. Return the local correction for review;
no fresh lease, privileged helper/systemd integration or smoke retry is approved.
The original aborted attempt and its missing evidence remain unchanged.

## Changed paths and correction

Only these new repository paths belong to this package:

- `playbooks/vpn-probe/controller.py` — stdlib readiness reader, allowlisted
  private snapshot collector, and `collect_before_teardown` ordering boundary.
- `playbooks/vpn-probe/test_controller.py` — 26 offline regressions.
- `docs/vpn-reliability/PACKAGE-3b-r.md` — this report and replacement procedure.

The three paths have Git intent-to-add entries so diffs/hooks include them;
no file content is staged for commit. Existing user/package changes are preserved.
`screen.py`, endpoint/deployment
code, network/qualification semantics and all resource/lease caps are unchanged.
No service manager, launch framework, dependency, automatic signal to a worker,
release-gate creation, privilege escalation or network operation was added.

### Readiness

The reader consumes only newly appended bytes and newline-terminated records.
Missing paths, empty bytes, blank/whitespace input and unfinished JSONL tails are
pending; no blank or unfinished record reaches `json.loads`. A split ready event
becomes a candidate only after its terminating newline arrives. Tails stay in
memory, not logs. A valid non-ready record is counted once and polling continues.
A complete `run-end` stops polling even if the wrapper is still holding runtime.

Results distinguish `malformed-json`, `wrong-schema`, `permission-error`,
`read-error`, `unsafe-file`, `truncated`, `replaced`, `disappeared`, `early-exit`,
`process-error`, `byte-limit`, `poll-limit` and `timeout`. Pending reason,
non-ready count and tail length survive deadline/exit results. Complete records
already in the snapshot are checked even after a candidate, so an observed
terminal/error record cannot hide behind readiness. Error text/raw records are
not returned.

The expected run/route/endpoint envelope is required. The ready event must have
schema 1, explicit `ready:true`, valid PID/UID/GID/groups/network namespace and
the runner's unverified route fields. `ready-candidate` supplies **only a candidate
Python PID/context for independent inspection**, never signaling authority,
gate-release authority, route proof or a workload verdict. The liveness callback
must explicitly return a bool; a failed check is not an empty poll. Neither a
launcher exit code nor systemd MainPID alone substitutes for this check.

### Collection and teardown

`collect_before_teardown` attempts collection, then invokes own-resource teardown
in `finally`, including on setup/copy/process failures or controller cancellation.
Collection errors propagate or have explicit incomplete/error statuses; they do
not become successful worker outcomes. A teardown exception also propagates;
endpoint teardown belongs in a separate outer `finally`.

Only `manifest.json`, `events.jsonl`, `summary.json`, `SUMMARY.md` are read. All
path components are opened without following symlinks; files must be regular,
single-link files. FIFOs, directories, symlinks and hardlinks are refused. No
recursive archive, core config, handoff, CA/key or credential export exists.
The destination is **new**, under a trusted controller-owned 0700 parent;
directory/files are created 0700/0600. Existing destinations are not overwritten.
Artifacts are private snapshots, not redacted publishable data.

Default/hard collection ceilings: 1 MiB/file; 4 MiB artifact bytes plus 8192 bytes
reserved for the atomic controller report; 64 KiB read buffers; <=5 s child-copy
wait plus <=400 ms for kill/reap attempts. Only the helper's own copier child may be
killed. It never signals a readiness PID. Missing files, partial limits/EOF,
source changes, refusal/read/write errors and collector crash/timeout remain explicit.
After timeout, unreported output is marked `partial-unknown`, not complete.
`collection.json` is **controller evidence**, not a synthesized worker summary:
`snapshot_only:true`, `worker_complete:"unknown"`, even when all files were copied.
An unfinished JSONL tail is preserved byte-for-byte, not repaired. No worker
outcome is inferred from filenames, copied bytes or service success.

Known ceiling: this is for the reviewed **local regular runtime/output mounts**,
not arbitrary remote/FUSE filesystems. Readiness deadlines are checked around
filesystem calls; byte/poll bounds also apply. The collector isolates copying in
an owned child, but a kernel-uninterruptible filesystem operation cannot promise
bounded reaping. Upgrade to separately supervised IO/controller execution if such
mounts are ever needed; do not extend the gate, hold, unit or lease to compensate.
Use a single-threaded controller for the Linux fork-based copier.

## Offline regression evidence

The original defect is reproduced by absent/empty/blank input: the replacement
never calls `json.loads` on it and reaches a bounded pending timeout. Delayed
creation and a ready event split across three writes become a candidate on poll
5, after newline completion. Other tests cover complete malformed JSON/UTF-8,
wrong schema/identity/PID, valid non-ready rows, retained partial tails, terminal
rows during wrapper hold, read/permission failures, truncation/replacement/removal,
early exit before/after reading, liveness-check errors and byte/poll ceilings.

Collection tests use temporary files/fake units/processes, with socket creation
explicitly forbidden. They establish allowlisting and modes; missing terminal
files; file/aggregate/disk ceilings; symlink/ancestor/FIFO/directory/hardlink
refusal; source disappearance/change; read/permission/write failures; process startup
failure/crash; and a genuinely blocked copier killed by the parent deadline.
Partial bytes remain present when the fake teardown deletes runtime. The revised
abort procedure is tested with and without a verified worker: optional verified
cancellation precedes collection, collection precedes runtime removal, and outer
reference cleanup still runs. Exceptions and KeyboardInterrupt cannot skip own
teardown. No fake candidate PID is signaled, no release gate is created.

One initial test run failed because its assertion relied on dictionary insertion
order after the controller report was serialized with sorted keys. The assertion
now checks the explicit artifact order; copy accounting was correct. This failed
iteration is not counted as a pass.

Executed from repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe -p 'test_controller.py'
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python -W error::ResourceWarning -m unittest discover \
  -s playbooks/vpn-probe/reference -p 'test_*.py'
uvx prek run --all-files
uvx prek run --files playbooks/vpn-probe/controller.py \
  playbooks/vpn-probe/test_controller.py docs/vpn-reliability/PACKAGE-3b-r.md
git diff --check
```

Results: **26 focused; 101 probe + 28 reference = 129 tests passed**. The focused
26 are included in the 101, not additional. Repository-wide hooks, explicit
new-file hooks and whitespace checks passed. Existing runner tests include their
reviewed temporary loopback TLS/curl fixtures; the new controller tests require
no sockets, systemd, root, external access or runtime credentials. These are local
regressions, not privileged deployment or live source/route enforcement evidence.

## Revised controller procedure — NOT EXECUTED

This replaces Package 3's step 5 readiness read and step 6 tar collection, and
applies to **every** startup, polling, workload, cancellation and error exit.
Retain its explicit reviewed launch/sandbox/watch/teardown commands and all
unchanged bounds: gate/startup <=30 s, wrapper hold 15 s, worker RuntimeMaxSec=100,
TimeoutStopSec=5, controller launch cutoff 600 s from preparation, teardown <=240 s
and verification <=60 s within the <=900 s lease. No RuntimeDirectoryPreserve,
permission widening, new persistent state or extended lifetime is proposed.

1. **Review first.** After accepting this local correction, separately request
   fresh pinned read-only preflight approval, then exact current endpoint-facing
   /32, fresh lease/install, worker, three tiny workloads, collection and teardown
   approval. Recheck source/namespace/NAT, policy, ownership and production context.
   Unknown context stops the attempt. Do not reuse Package 3b's lease or approval.
2. Prepare controller-owned private log/output parents before launch. For the
   narrow privileged collector, use a root-owned 0700 evidence parent, separate
   from worker runtime and credential staging; retain its files privately for
   controller inspection without widening permissions. Stage reviewed/hash-pinned
   `controller.py` with the existing root-owned source staging, not a privileged
   import from a worker-writable directory. Worker receives only the previously
   reviewed runner/selected handoff/CA, **not** this controller helper or admin
   inputs. Refuse existing own unit/staging/runtime/release paths as before.
3. Start the unchanged gate-held worker and promptly call **this helper's**
   `poll_ready`, against `/run/vpn-screen/result/events.jsonl`, with the expected
   fresh run ID, `cherry-vless`, and endpoint alias. Use timeout <=10 s, interval
   50 ms, <=200 polls, <=1 MiB read, further shortened by the already-approved
   startup/controller deadline. Reserve time for independent inspection within
   the original 30 s gate wait; no restarted countdown. Liveness checks use finite
   read-only checks of this attempt's launched unit/cgroup and, once known, actual
   Python child; activating/running is not itself readiness. A terminal unit or
   Python exit is false; inspection errors must raise, not return guessed true.
4. On `ready-candidate`, inspect its **actual Python PID** using the existing
   controller checks: fresh UID not 0/946/1000, start identity/executable, owned
   cgroup, only primary group, zero capabilities, NNP, namespace, credential mount,
   sandbox, policy/underlay and sockets. Independently verify ownership/liveness;
   retain a pidfd/start identity if graceful cancellation may be needed. Do not
   signal based solely on a ready record. Gate release remains an explicit,
   separately approved action **only after** all inspection succeeds within the
   existing deadline. This helper creates no gate. Any other poll result stops
   progression, preserves its distinct status and enters the abort path.
5. After normal completion or **any** error/cancellation, collect while runtime is
   still present, before unit stop/removal. If necessary and safe, gracefully
   cancel only an independently verified owned Python worker using its retained
   process identity/pidfd, not wrapper MainPID or a guessed/reused numeric PID.
   Allow <=5 s for terminal evidence within existing unit/hold/deadlines. Do not
   terminate the holding wrapper first. If ownership is unverified, do not signal
   a candidate; snapshot what exists immediately. If immediate stop is required
   for safety, stop only the owned unit without waiting for collection; explicitly
   record that exception/evidence loss, then collect any remaining allowlisted
   files. Already-exited/missing runtime is likewise explicit, not a raw outcome.
6. Use the following ordering in the existing approved controller, not a private
   `json.loads(empty_poll)` or `tar` fallback. Administrative callbacks below are
   the existing explicit, bounded, owned-resource operations; they are **not new
   launch/stop authority**. The regression tests exercise this nesting with fake
   operations. Calls run in the separately approved administrative context.

   ```python
   # Import the staged, reviewed controller.py as controller.
   # archive is a new path under the controller-owned private evidence parent.
   try:
       try:
           readiness = controller.poll_ready(
               '/run/vpn-screen/result/events.jsonl', owned_attempt_alive,
               {'run': approved_run_id, 'route': 'cherry-vless',
                'endpoint': approved_endpoint_alias},
               timeout=poll_seconds_remaining, interval=.05, max_polls=200,
               max_bytes=1048576)
           # Preserve readiness result privately before branching.
           if readiness['status'] != 'ready-candidate':
               raise RuntimeError('readiness-' + readiness['status'])
           # Independently inspect the candidate; only separately approved
           # inspection/release/watch/workload follows. Never retry the launch.
       finally:
           try:
               if graceful_cancel_needed_and_safe and independently_verified_worker:
                   cancel_verified_python_and_wait_at_most_5s()
           finally:
               collection = controller.collect_before_teardown(
                   '/run/vpn-screen/result', archive, teardown_owned_worker_and_staging,
                   timeout=collection_seconds_remaining,
                   file_limit=1048576, total_limit=4202496)
               # Retain collection.json; assess incomplete/error statuses explicitly.
   finally:
       teardown_reference_and_verify_preservation()
   ```

   `poll_seconds_remaining` is positive and <=10; `collection_seconds_remaining`
   is positive and <=5 and also fits the **remaining**, not restarted, 15 s hold,
   runtime/controller/lease deadline, with kill/reap overhead reserved. Start
   collection promptly: do not wait for `systemd-run --wait` to return first.
   If no collection time remains, record evidence loss in the preopened private
   controller log and teardown immediately; never wait longer or launch a second
   collection to manufacture terminal files. Exceptions from polling, cancellation,
   collection or worker teardown remain failures, with their original status in
   controller logs; outer reference cleanup still executes. The worker-teardown
   callback itself uses `try/finally` for its existing stop, absence inspection and
   owned staging/release removal; a failed stop is reported, not treated as absence.
7. Preserve launcher status/logs and partial artifacts. Missing/partial/invalid
   terminal files mean incomplete worker evidence; a copied snapshot or launcher
   success cannot invent a raw terminal outcome. Assess raw request/receipt and
   UID/underlay/outbound/exact-source evidence separately before another workload.
   Stop on unexpected failure or missing proof; never broaden sources, rerun an
   object, renew a lease or retry directly. Three tiny workloads remain unchanged;
   none ran here and no capacity/DPI/UDP/media conclusion follows.
8. Always perform the previously reviewed own-worker/staging/reference teardown,
   including partial install/startup. Verify no owned process/cgroup, runtime,
   credential mount, account, listener, unit, replay state or nft table remains;
   compare production SSH/VPN/DNS/routes/policy/updater preservation. Retain private
   evidence, unlink only this attempt's selected handoffs/lease material, and close
   owned administrative connections. Unlink is not secure storage erasure.

## Limits, rollback and review gate

**Not run:** privileged helper/systemd integration, fresh preflight, SSH, lease
preparation/install, worker/gate release, endpoint/client traffic or live retry.
No VPN/DNS/routes/firewall/updater/production changes or credential access occurred.
No temporary test files/processes remain; tests remove their private directories
and reap owned copier children. No commit or publication was made.

Rollback only the three new paths above (and their intent-to-add entries, if
present), preserving all pre-existing work. There is no live resource to roll
back. Original Package 3b evidence/limitations remain unchanged.

**Return for review. Any fresh live attempt needs new scoped approvals.**
