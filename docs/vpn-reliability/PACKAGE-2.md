# Package 2 — restricted reference endpoint (implementation only)

**Runtime follow-up:** `PACKAGE-2b.md` records explicitly authorized commissioning,
corrective fixes, a passing same-host smoke and verified teardown. This document
retains the original offline review/proposal below, not current runtime status.
The follow-up fixes nft host-literal rendering, systemd credential-file handling
and HTTPSConnection cleanup; caps and source restrictions are unchanged. No
endpoint remains installed, and future leases need separate execution approval.

**STOP before deployment.** No SSH, DNS probe, privileged launch, host firewall
inspection/change, listener installation, production restart or live load was
performed. No sustained runner was implemented. Packages 1/1b remain time-bounded
snapshots, not new execution approval. Existing user edits were preserved.

## Controller review

Offline implementation accepted for bounded commissioning, not runtime enforcement
or performance qualification. Controller independently reran all 53 tests (21
reference + 32 existing probe) and repository-wide hooks; all passed. Source,
units, deployment/teardown and smoke were reviewed; no live command was run.

Next is Package 2b: obtain user approval for exact remote read-only preflight,
then the private bind/source plan, one fresh lease, install, same-host readiness
and teardown. Current listener/NAT ownership, assigned IP, source routing and
host policy remain runtime gates. Unknown/conflicting policy means stop, not
silently broaden sources or reconfigure production.

Package 2b added `expires_at` to generated descriptors, equal to the server
config's `expires`, with a deterministic test. The later runner must check
remaining lifetime and record endpoint expiry separately from tunnel failure.
The CA/run/receipt-template extensions below are accepted for the future strict
parser, with exact same-origin receipt checks and scoped CA trust; no insecure
fallback or redirects. Package 2b can make/test this small metadata amendment
before commissioning, without changing lifetime or resource caps.

Known ceiling: lease <=900 s, individual UDP session <=600 s, and 4 GiB object
budget are deliberately suitable for bounded commissioning/one short screen,
not an entire comparison campaign or a 30-minute voice acceptance run. Future
longer qualification needs an explicitly reviewed lifetime/budget design; do not
extend limits implicitly. Receipts are ephemeral and must be collected before
expiry/teardown. Same-host readiness does not certify endpoint throughput or
external source filtering. Tiny or timing-dependent smoke failures are evidence;
do not retry or weaken checks without reviewing the cause.

## Changed paths and dependencies

- `playbooks/vpn-probe/reference-deploy.yaml`: standalone, opt-in Ansible install
  and teardown, targeting only existing **`cherry_vpn_test`**, as `vpnadmin`, with
  pinned known-host checking and existing dedicated administrator key. Does not
  import Cherry bootstrap/VPN/monitoring deployment or install packages.
- `playbooks/vpn-probe/reference/endpoint.py`: stdlib HTTPS/UDP service.
- `reference/{prepare.py,firewall.py,smoke.py}` in the same directory: offline
  private lease/certificate preparation, narrowly owned nft guard, opt-in finite
  readiness check. No secrets on argv or request logging.
- `reference/{reference.service,firewall.service,test_endpoint.py,test_deployment.py}`:
  systemd limits and offline tests. This report is the only documentation added;
  the five input documents and existing tools were not edited.

Runtime dependencies: existing Python 3, systemd, nftables, OpenSSL and Ansible.
Python implements payload generation, TLS, HTTP and UDP without packages.
OpenSSL only creates/verifies dedicated certificates; nftables protects native
host listeners. No Docker image, ACME client, reverse proxy or monitoring service.
Tests additionally reuse the repository's available PyYAML.

## Exact proposed listeners and path scope

| Listener | Bind | Purpose |
| --- | --- | --- |
| TCP **9443** | One explicit Cherry IPv4, `config.json.bind_ipv4` | TLS 1.2+ HTTP/1.1, one request per connection |
| UDP **9444** | The same explicit IPv4 | Registered-session authenticated 96-byte echo |

No wildcard bind, IPv6 listener, HTTP/3, HTTP redirect or proxy/forwarding route.
Preserve occupied TCP **22/80/443/8443**, production certificates, proxies, DNS,
SSH policy, VPN configuration and the workstation updater. These new ports are
**proposals**, not currently verified free. The deployment checks native socket
occupancy; review must also check Docker bindings and NAT (including deployments
without a Docker userland proxy) before authorizing it.

This is a **distinct-port HTTPS control**, not a same-port 443 DPI comparison.
Same-Cherry-host transfers measure access/tunnel capacity, **not Cherry Internet
egress**. Cherry-exit connections to its own public IPv4 can be locally routed,
not Internet hairpins; receipts may show the host IP or another reviewed local
source. Never broaden restrictions automatically to make a test pass. A later
separately approved real-media transfer or already available distinct controlled
host supplies an egress control; no new VPS or public speed-test load is proposed.

## TLS trust, lifetime and private descriptors

`prepare.py` takes a private JSON plan on stdin, creates a **new** 0700 directory,
streams hashes, and creates a new Ed25519 CA and leaf. The leaf has the explicit
IPv4 SAN, serverAuth, CA:false and a one-day validity. The CA lasts two days;
its private key is unlinked after signing, never deployed. No production key
is read/copied. Certificate/CA/key/config/descriptor files are 0600. Failure may
leave partial private files; remove only that newly created directory.

URLs use the **literal reviewed IPv4**. TLS validates its IP SAN and dedicated
CA. IP-literal clients normally omit DNS SNI: port, SNI and certificate therefore
differ from the VPN TLS handshakes, another comparison confound. There is no
endpoint hostname bootstrap, production DNS change, observed-DNS
pinning, insecure mode or system trust-store installation. This does not qualify
VPN-server/application DNS. curl must receive a private `cacert` configuration
option; Python smoke uses `ssl.create_default_context(cafile=...)`. Do not use
`--insecure`. Endpoint expiry is at most **900 seconds from preparation** and
is enforced independently of certificate validity. No renewal/rotation timer:
a new approved lease requires teardown and fresh credentials/certificates.

Each of `fresh.json`, `segment.json`, `continuous.json` preserves the v1
contract's descriptor fields and proposes these **explicit Package 3 amendments**:

- `ca_file`: absolute private path to this lease's CA, passed only to the selected
  worker. If staged into credentials, rewrite this path in the worker's selected
  descriptor; never silently fall back to global/insecure trust.
- `expires_at` (Package 2b metadata amendment): integer Unix UTC seconds, exactly
  equal to the server config's `expires` in all three descriptors. The later
  runner must record expiry/remaining lifetime and reject insufficient leases
  as endpoint constraints, not tunnel failures. No lifetime cap is changed.
- `run_id`: authenticated fixed lease/run ID. Every HTTP operation must supply
  `X-Run-ID` and a **new** `X-Request-ID` (`[A-Za-z0-9_-]{1,64}`).
- `receipt_url` is a template ending `/receipts/{request}`; substitute the object
  request ID, but authenticate that read with `receipt_auth_header` and its own
  unique operation ID. No redirect/template-origin substitution is permitted.

Other fields: `schema_version:1`, `alias:reference-on-vpn`, `family:ipv4`,
`expected_status:200`, `content_type:application/octet-stream`,
`cache_policy:"no-store, no-transform"`, `location:vpn-host`, exact `object_bytes`
and SHA-256. URLs/headers/addresses remain private. Package 3 must deliberately
accept these new fields; the older strict proposed parser must not silently
ignore them. There is no implemented runner to change here.

## Objects, resource ceilings and accounting

| Object path | Declared complete length | SHA-256 |
| --- | ---: | --- |
| `/objects/fresh` | 4096 | `87ff26b2a35693e6b9c7312997400dd28c5e8e95c2a5d8a091f06b86d4e1888a` |
| `/objects/segment` | 8388608 | `78a9a5583f2e0eb536658cb1c365c38e39944cf688ee20cc38c961479fa0263c` |
| `/objects/continuous` | 4294967296 | `c8fe8e43111a2c15fbe547db97f3360ab4a2bf48d76869051be6ff007360104f` |

Continuous is 4 GiB, greater than the proposed client's aggregate 3 GiB cap.
Client cancellation/partial objects do **not** acquire a full-hash verdict.
SHAKE256, domain-separated by block counter, generates deterministic cryptographic
pseudorandom bytes, not zeros/sparse files/a small repeating buffer. Only 64 KiB
blocks are generated; peak transient payload is about two blocks per iterator.
Preparation hashes the entire finite stream once, without storing it; serving
regenerates it incrementally. No compression, ranges, caching or user-chosen size.
Complete segments must verify length/hash; HTTP errors cannot be throughput.

- Endpoint cgroup: **192 MiB RAM**, no swap, **75% of one CPU**, **24 tasks**,
  **64 FDs**, 2 MiB individual output-file ceiling, **900 s runtime**, stop <=5 s,
  no restart/boot enablement. Worker is DynamicUser, zero capabilities, no extra
  groups, no-new-privileges, strict read-only system/home protection, private tmp
  and devices. Only its own StateDirectory is persistently writable.
- At most **8 HTTP workers**, backlog 8, **4 active object transfers**. Before TLS:
  32 admitted connections per one-second window, **2048 total per lease**; excess
  connections close without response. TLS handshake timeout 3 s; absolute header
  deadline 5 s, <=8192 header bytes/32 lines. No bodies/pipelining/duplicate headers.
- Object body cap **8388608 bytes/s aggregate** (8 MiB/s, 67.11 Mbit/s), shared
  across transfers, versus the client's 4 MiB/s. At most **4294967296 object body
  bytes reserved per lease**, including failed-send reservations. No refund lets
  disconnect/retry evade it. Per-transfer deadline 660 s plus at most one 2 s send;
  lease expiry and cgroup lifetime remain outer bounds. Slow receivers time out.
- At most **1024 authenticated operation IDs/receipts**, four UDP sessions; all
  receipts/keys/bitmaps are in bounded RAM, never an unbounded journal or file.
  Object receipts are final on completion/disconnect, or `active` while running.
  They expire with the process/lease (<=900 s); teardown removes the replay marker.
  The only persisted worker file is a tiny `spent` marker in a private state dir.
  It blocks restart even after a crash: no reset of budgets or replay state.
- Headers/control replies are outside the object body budget, bounded separately
  by 2048 connections/1024 operations and <=8 KiB receipt bodies. UDP has a separate
  <=120000 replies x 96 bytes = **11.52 MB** cap across four sessions. Total body
  ceiling is thus about 4.32 GB including conservative control allowance, before
  TLS/IP overhead. NIC/provider accounting remains a later measurement, not a
  guarantee about billing. No payload files or request logs consume disk.

**Performance ceiling:** configured rate is twice the client's intended cap, but
75% CPU, Python SHAKE/TLS and Cherry's shared 1 GiB/one-core host can impose a
lower ceiling. No host capacity claim is made. A passing tiny readiness check
cannot certify 4 MiB/s serving. Later approved calibration/resource sampling must
establish that the reference is not the bottleneck; otherwise report the endpoint
ceiling/inconclusive result, not tunnel failure. Do not increase limits silently.

## Authentication, receipts and UDP wire contract

One lease has separate random **256-bit HTTPS bearer** and **receipt-read bearer**
secrets, delivered in private files/systemd credentials, not argv/history. Every
operation is bound to the configured run ID and a unique authenticated operation
ID; repeats return 409, expiry/source mismatch 403, bad token 401, capacity 429.
A spent lease cannot restart. Request tokens are never echoed in receipts/logs.
The receipt bearer cannot download objects or create sessions.

Object receipts bind run/request/object to the **socket peer IPv4**, UTC start,
monotonic elapsed seconds, bytes successfully handed to the socket, and outcome.
They ignore X-Forwarded-For. Socket-accepted bytes are not proof of client receipt;
failed sends can undercount partially accepted data. A source IP cannot identify
which protocol was used behind a shared exit. Receipts need outbound/underlay
proof from the later runner, not a source-only route claim.

`POST /udp-session` (HTTPS object bearer, zero body) creates one of at most four
sessions, <=600 s and never beyond lease expiry. It returns a random 128-bit
session ID and independent 256-bit HMAC key over TLS. The UDP source **must match
that HTTPS session's observed IPv4 and the allowlist**; the first valid datagram
pins its source port. A changed NAT port requires a new bounded session, not an
automatic rebind. TCP/UDP routes with different exits need separate review.

Wire format: network order Python `!4s16sId32s32s`, **96 bytes**:
magic `VRU1`, binary session ID, uint32 sequence (0..29999), float64 client
monotonic timestamp, 32 payload bytes, HMAC-SHA256 over the preceding 64 bytes.
Replies replace magic with `VRR1` and recompute HMAC, keeping the same length.
Unknown sessions/keys, wrong source/port/magic/size, nonfinite timestamps,
expired sessions and duplicate sequences get **no reply**. No unsolicited sender,
reflection destination selection, proxying or amplification. Session bitmap
prevents replay and supports reordering. Ceiling is 100 pps/session with burst 10
(400 pps aggregate), deliberately above intended 50 pps to tolerate jitter;
30000 distinct accepted sequences/session bounds total volume.

Receipt bearer `GET /udp/<session-hex>` returns source, received/sent unique
counts, accepted sequence bitmap, duplicates/reordering/rate drops, highest
sequence, first/last server monotonic arrival and run ID. Combine client sent
IDs with this bitmap for forward count/loss evidence, and successful server
send count with client authenticated unique receipts for return count evidence.
Rate drops/send errors must remain distinct from network loss. Package 4 must
collect its own receive times/IDs and define estimators. **Echo alone is RTT and
round-trip loss**, not independent one-way latency/jitter; no clock synchronization
or one-way latency is claimed. This is not HTTP/3 or Discord acceptance, and no
UDP measurement client/campaign was implemented (only the one-packet smoke).

## Firewall effects and pre-deployment review

Plan sources are **1–8 explicit IPv4 /32s**, including the approved direct client
public source and Cherry's actual local/exit source. Add nt1 only if that exact
exit/test is approved. No broad subnet, wildcard opening or dynamic source lookup.
For same-host smoke, include Cherry's explicit public source; if actual routing
chooses another source, stop for review, do not infer permission to add it.

`vpn-reference-firewall.service` owns only **`inet vpn_reference`**, input hook
priority **-10**, policy accept. Exact allowed sources return to the remaining
host policy for TCP 9443/UDP 9444; **all other sources, including IPv6, drop on
those two protocol/port pairs**. All other ports/protocols are unaffected. An
atomic own-table replacement never flushes/replaces other tables. Existing later
host/provider policy may still deny allowed traffic. Native sockets avoid Docker
publish/FORWARD bypass; the application independently rechecks sources and auth.
The root oneshot has only CAP_NET_ADMIN and no network worker; it is bounded to
10 s start/stop, each nft invocation <=5 s. Guard failure prevents endpoint start;
removing/stopping the guard stops the endpoint first. No provider firewall API,
persistent nft configuration or production Docker rules are changed.

**Not yet verified:** current listener owners, interface-assigned bind IP,
complete host nft/iptables/Docker NAT and provider policy, systemd on Cherry,
source/hairpin behavior, source-allowlist effectiveness. Before deployment,
review these with separately approved read-only pinned SSH and ensure the new
ports are not DNATed/owned elsewhere. Preserve administrator access. If provider
policy needs a change, return that exact change for approval; none is implemented.
After installation, inspect actual loaded nft rules/counters, sockets/cgroup and
negative source/auth behavior. A declared allowlist or offline string test is
**not enforcement proof**. No runtime readiness/security result exists yet.

## Proposed commands — NOT EXECUTED; separate approval required

### Preparation and installation

After approving exact bind/source addresses and the deployment, prepare just in
time (900 s lease includes preparation/deployment/readiness). Private parent and
files: 0700/0600, umask 077. Do not put the real plan/vars in the repository.

```sh
umask 077
CONTROL=$(mktemp -d /tmp/vpn-reference-controller.XXXXXXXX)
# Write "$CONTROL/plan.json":
# {"bind_ipv4":"<reviewed Cherry IPv4>",
#  "sources":["<direct public IPv4>/32","<Cherry source IPv4>/32"],
#  "run":"r001"}
PYTHONDONTWRITEBYTECODE=1 python playbooks/vpn-probe/reference/prepare.py \
  --output "$CONTROL/lease" < "$CONTROL/plan.json"
# Write "$CONTROL/deploy-vars.json" with reference_approved:true,
# reference_state:"present", reference_private_dir:"<absolute CONTROL>/lease".
ansible-playbook -i infra/cherry-vpn/private/inventory.yaml \
  playbooks/vpn-probe/reference-deploy.yaml -e "@$CONTROL/deploy-vars.json"
```

An identical active-lease rerun is idempotent; preview refuses changed managed
files before copying them. No active lease is restarted. Spent/crashed/expired
leases require teardown, never marker deletion/reuse. Installation does not run
smoke automatically. Partial failures must retain evidence and use teardown,
not restart blindly. Long-lived deployment is deliberately unsupported.

### Bounded same-host readiness proposal

After deployment approval and unit/rule review, run **only on Cherry** using
pinned SSH, with the following separately approved launch. This is not a rerun
of Package 1b or an authorization for workstation probes. Inspect the actual
MainPID/UID/groups/capabilities, source sockets and cgroup as appropriate; no
production UID, home/state access or client routing changes.

```sh
sudo -n systemd-run --unit=vpn-reference-smoke --wait --pipe --collect \
  -p DynamicUser=yes -p User=vpn-reference-smoke -p SupplementaryGroups= \
  -p LoadCredential=config.json:/etc/vpn-reference/config.json \
  -p LoadCredential=ca.pem:/etc/vpn-reference/ca.pem \
  -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
  -p PrivateDevices=yes -p ProtectProc=invisible -p NoNewPrivileges=yes \
  -p CapabilityBoundingSet= -p AmbientCapabilities= \
  -p RestrictSUIDSGID=yes -p RestrictNamespaces=yes -p LockPersonality=yes \
  -p 'RestrictAddressFamilies=AF_INET AF_UNIX' -p UMask=0077 \
  -p MemoryMax=64M -p MemorySwapMax=0 -p TasksMax=4 \
  -p RuntimeMaxSec=60 -p TimeoutStopSec=5 -p KillMode=control-group \
  -p LimitFSIZE=1048576 -p StandardError=null \
  /usr/bin/python3 -I /opt/vpn-reference/smoke.py
```

One attempt only: **six HTTPS operations**, each socket timeout 4 s, at most
16385 received body bytes/operation, and **one 96-byte UDP request/reply** with
4 s timeout; 60 s cgroup outer bound. Checks bad bearer ->401, fresh length/hash,
replayed ID ->409, authenticated object receipt, session registration, HMAC echo
and direction counts. No retry, DNS, segments/continuous load or public targets.
Output is a sanitized passed/failed JSON record, not raw receipts. It consumes
one of the four UDP sessions. It does not test external source filtering, the ISP,
VPN routing, UDP relay or capacity. Cancel only `vpn-reference-smoke.service`;
confirm that unit/cgroup is collected afterward. Never stop production services.
External negative-source checks and any tiny workstation smoke need their own
approved sources and isolated-worker launch; **not implicitly authorized here**.

### Teardown and verification

```sh
# Write "$CONTROL/teardown-vars.json":
# {"reference_approved":true,"reference_state":"absent"}
ansible-playbook -i infra/cherry-vpn/private/inventory.yaml \
  playbooks/vpn-probe/reference-deploy.yaml -e "@$CONTROL/teardown-vars.json"
```

Teardown stops/disables **only** endpoint then guard, explicitly removes any
own nft table left by a partial start, removes `/opt/vpn-reference`,
`/etc/vpn-reference`, the two own unit files and both public/private systemd
state-directory paths, then daemon-reloads. It is idempotent and does not need
an unexpired lease/local key files. No production rollback/restart is needed.
Confirm no 9443/TCP or 9444/UDP reference socket, own cgroup/dynamic identity,
credential mount, own nft table or state directory remains; compare preserved
SSH/VPN listeners/health and other firewall tables to reviewed baseline. Do not
remove an unrelated process merely because it subsequently uses these ports.
Automatic lease expiry closes endpoint listeners but deliberately leaves the
guard and spent marker until explicit teardown. Reboot starts neither unit.
Retain private evidence first, then delete only this invocation's exact CONTROL
directory. Unlinking keys is not guaranteed secure storage erasure.

## Offline validation and limitations

Executed without Internet/network listeners, using fake sockets/clocks and
in-memory TLS BIOs (temporary test keys were removed):

- `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s
  playbooks/vpn-probe/reference -p 'test_*.py'`: **21 passed**.
- Existing `playbooks/vpn-probe` discovery: **32 passed**, unchanged tools.
- Local full-object streaming hash experiment: **8.014 s**, tracemalloc peak
  **134460 bytes**, **zero payload disk bytes**. The 1 MiB generated sample's
  zlib compressed/input ratio was **1.0003109** (no useful compression); distinct
  blocks, finite sizes and reproducible hashes are also unit-tested. This is
  workstation CPU evidence, not Cherry/TLS throughput evidence.
- `uvx prek run --all-files`: **passed** on this workspace; the previously
  documented 13 unrelated YAML violations did not reproduce. Explicit
  `uvx prek run --files` over all ten new paths: **passed**, including Ansible
  syntax/lint. Initial new-playbook lint found two issues (read-only systemctl
  query and shell pipefail); both were corrected without suppressions.
- `git diff --check`: **passed**. Original four modified input documents remain
  untouched; no unrelated changes were made.

Negative coverage includes strict config/source/expiry, separate receipt auth,
replay/request/connection/session/concurrency/rate/byte limits, no proxy/ranges/
bodies/duplicate headers, forwarded-source rejection, interrupted receipts,
UDP wrong key/source/port/magic/size/sequence/expiry, duplicates/reordering,
crash replay marker, private input permissions/symlinks, TLS untrusted CA and IP
mismatch, own-table-only policy and teardown ordering. nft syntax/kernel effects,
remote systemd deployment/idempotence and provider behavior are **not run**;
static tests and Ansible syntax/lint are not runtime enforcement evidence.

Rollback of this implementation: remove only this package's new playbook,
`reference/` directory and `PACKAGE-2.md`. No remote cleanup is currently needed.
No commit/publishing performed. Stop here for deployment review.
