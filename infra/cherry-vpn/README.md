# Budget VPN experiment

Supervised trial: one disposable hourly VM, native SSH forwarding, and optional
Dockerized Naïve and VLESS/REALITY, with Linux as the first client. Existing nt1,
application servers and active client configuration are kept separate. Full
deployment now also registers Cherry in the existing monitoring stack and installs
isolated workstation probes with Grafana/Telegram alerts. No automatic allocation,
rotation or profile publication is introduced.

SSH is a cheap **baseline**, not an obfuscation solution. If it is blocked or
unstable, test Naïve on the same VM next; do not buy a larger VM to solve filtering.
UDP and sustained-throughput testing are not covered by this initial baseline.

## Current status

One Debian 13 B1 VM is **running** in `NL-Amsterdam`, DNS
`akorz-dyn1.duckdns.org`. It replaced the Lithuania server **destroy-first**,
retaining the administrator public-key record and
state-encryption secret but generating a fresh server identity. There is no
intentional overlap or automatic allocation/expiry; the user supervises spend.

The host identity was generated before provisioning, encrypted in the shared
Vault, installed by cloud-init and pinned from the applied encrypted state.
Strict SSH verification succeeded; no console, password bootstrap, or first-use
fingerprint acceptance was needed. State and new saved plans use enforced
PBKDF2/AES-GCM encryption. Back up `secrets.vault.yaml`: losing its state passphrase
makes them unreadable. Never start from empty state to recover a lost controller.

The [`vpn_node` role](../../roles/vpn_node/README.md) has deployed verified
non-root `vpnadmin` sudo access, disabled root/password SSH, enabled unattended
Debian security updates without automatic reboots, restricted the `vpnprobe`
account, and started Dockerized Naïve and sing-box VLESS/REALITY. Naïve obtained
a valid Let's Encrypt certificate; node-side HTTPS returns 200. A host firewall
is not configured. Cherry's image marks cloud-init disabled after provisioning;
bootstrap accepts only that explicit marker/status with Python already available.

**Amsterdam Linux result:** all six direct checks passed (SSH, Naïve and VLESS,
two HTTPS sites), with the VM's egress IPv4 for all three protocols. A second
six-check run using the fetched, published Linux profile in an isolated core also
passed. Direct pinned SSH administration works without the old proxy transport.
Lithuania previously failed all direct checks but passed the SSH-forwarded
reference; its results were retained separately. These observations do not prove
which ISP/transit/filtering component caused the difference.

`cherry-ssh`, `cherry-naive` and `cherry-vless` are now published alongside nt1 in
all three existing private platform profiles. HTTPS contents match local generated
files, URLs/tokens and nt1 defaults are unchanged. Already-enrolled devices receive
the new choices on refresh; selection is manual, not automatic failover.

**This workstation was not enrolled**, by explicit user choice. Its original
`ssh-via-workstation` selection/local fallback remains active, no enrollment file
was created and its update timer remains inactive. Published-profile testing used
a temporary isolated core, not the active service. Private configs/results are
in `private/`. UDP, sustained stability, other client platforms and autonomous
replacement remain unverified.

The catalogue quote remains EUR 0.015/hour; the server API has reported a EUR 0.02
hourly unit price. The user accepted API pricing; these fields are not a verified
all-inclusive bill. The DuckDNS token's missing YAML `!vault |` marker was corrected
without changing its encrypted ciphertext or `external_vars.yml` symlink.

## Monitoring and suspected blocking

Implemented in [`monitoring.yaml`](monitoring.yaml); **not a claim of live deployment**.
It is included at the end of `deploy.yaml`. For an already bootstrapped node, deploy
monitoring alone from the repository root:

```sh
ansible-playbook -i hosts -i monitoring.inventory.yml \
  -i infra/cherry-vpn/private/inventory.yaml \
  --vault-password-file .ansible_pass infra/cherry-vpn/monitoring.yaml
```

Restore/generate the applied private inventory and dedicated keys first. The
controller also needs `private/cherry-outbounds.json`, exported by `deploy.yaml`;
the playbook rejects a profile for another server IP. Do not reconstruct host pins
with `ssh-keyscan`. Load all three inventories for full deployment too. Run without
`--limit` or `--check`: this workflow configures Cherry **and** the workstation.

Requirements: existing Docker/Compose on Cherry and the workstation, passwordless
`vpnadmin` sudo, workstation sudo, the existing monitoring `.env` and Vault-backed
Telegram credentials. The workstation client uses a pinned Naïve-capable sing-box
image; the probe image packages Python and curl. Neither needs host-installed binaries. Metrics source CIDRs come
from `monitoring_workstation_allowed_sources`; verify these match the workstation's
actual scraper egress. Port 9273 remains source-restricted, not open to everyone.

What is checked:

- **Host/container metrics:** the existing Telegraf role, shared node dashboard,
  disk alert and two-minute collector-unreachable Telegram alert, with stable
  `node="cherry"`. Exporter failure alone is **not** evidence of a VPN ban.
- **Real protocol requests:** a separate Compose project deployed through the
  existing `deploy_compose` role runs unprivileged `client` and `probe` containers.
  They share a network namespace: only the probe reaches the client's loopback
  listeners on ports 22340–22342; no ports are published to the workstation.
  Every minute the probe uses Cherry's pinned SSH key,
  Naïve credentials/TLS and VLESS/REALITY credentials. Curl requests gstatic and
  Cloudflare HTTPS through each protocol (six checks, including remote DNS).
  There is no direct outbound fallback, TUN or modification of the active client.
- **Direct controls:** HTTPS to `example.com` and `www.wikipedia.org`, without
  curlrc or inherited proxy variables. Both must pass. Verify these sites are
  reachable directly from the affected ISP; adjust the probe Compose arguments if
  necessary. Controls use ordinary Docker egress. Host TUN/routing can still carry
  these requests: verify a direct bypass
  before treating them as independent controls.
- **Grafana alerts:** both destinations failing for a protocol for two minutes
  while controls pass triggers *Cherry VPN protocol unreachable*. Partial
  destination failure is visible in metrics but does not assert path failure.
  Failed controls produce *checks inconclusive* instead. A missing/stalled probe
  produces *probe unavailable* after three minutes plus a one-minute pending period.
  Evaluation and existing Telegram grouping add delivery latency.

These observations indicate a **suspected path/server/client failure**, never
proof of an IP ban. Compare protocols, inspect the server and repeat from another
network before replacing anything. **Automatic replacement is still not implemented.**
The workstation runs Grafana and the probes: if it is offline, it cannot notify you.
Use an external dead-man monitor if workstation-outage notifications are required.

The playbook saves a managed block in the private monitoring overlay (with backup),
so ordinary `ws-logs/deploy.yml` runs retain Cherry and probe alerts without loading
its private inventory. Rerun full Cherry deployment after replacement to refresh
its metrics address, host pin and isolated probe credentials. It verifies Cherry's
host/container metrics and all six probe series in Prometheus; this checks collection,
not that VPN requests passed. Inspect `vpn_probe_success` and test the existing
**Monitoring Telegram** contact point in Grafana after deployment.

Diagnostics on the workstation:

```sh
cd /srv/deploy/cherry-vpn-monitor
docker compose ps
docker compose logs --since 15m client probe
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=vpn_probe_success'
```

No test Telegram message is sent automatically. Credentials live under root-only
`/etc/vpn-monitor/`, outside the Compose deployment directory. The mode-0600 client
file belongs to the container's unprivileged UID 65534 and is mounted read-only into
only the client; the probe has no credential mount. Observations in
`/var/lib/vpn-monitor/metrics.prom` contain no credentials. To disable probes, run
`docker compose down` in `/srv/deploy/cherry-vpn-monitor`, set the saved workstation
`monitoring_vpn_probe_enabled: false`, and redeploy the monitoring stack; it removes
only the three VPN-specific Grafana rules. Retire Cherry separately through the
normal monitoring inventory process if destroying the VM.

## Secure automatic bootstrap

For a new deployment only, create `secrets.vault.yaml` with `prepare-secrets.py`.
For an existing deployment **reuse that encrypted file** and add/retain its
bootstrap identity and random state-encryption passphrase:

```sh
python infra/cherry-vpn/prepare-bootstrap.py
# Only for existing plaintext DEFAULT LOCAL state, with one active controller:
bash infra/cherry-vpn/tofu.sh migrate-state
```

Preparation is idempotent. Migration first encrypts and verifies recovery copies
in `private/pre-encryption-*.vault`, then rewrites the unchanged snapshot through
OpenTofu's encrypted state writer and verifies resource IDs/outputs/lineage. It
never disables encryption enforcement, accepts plaintext as a normal fallback,
or changes cloud resources. Use the wrapper only; its local controller lock also
protects migration. Non-default backends/workspaces need a separate migration.

The shared Vault now includes `vpn_bootstrap.state_passphrase` and
`vpn_bootstrap.ssh_host_key`. Administrator/probe private keys still never enter
OpenTofu. The **server host private key does** enter cloud-init and therefore the
encrypted state/plans, as explicitly chosen for automated host authentication.
Cherry and guest root can access it. Encryption protects storage, not a compromised
controller/cloud account. Keep `.ansible_pass` separate from state/shared ciphertext.
Avoid debug logs and decrypted `show -json`/`state pull` files; these can expose
secret material despite at-rest encryption. Old plaintext plans are rejected and
must never be reused. A raw binary invocation bypasses the wrapper's controller lock.

Plan/review/apply as below. After apply, generate the pin and private inventory:

```sh
bash infra/cherry-vpn/tofu.sh inventory
# If direct administration is blocked, explicitly select a controller transport:
bash infra/cherry-vpn/tofu.sh inventory \
  --proxy-command 'nc -X connect -x 127.0.0.1:12334 %h %p'
ansible-playbook -i hosts -i monitoring.inventory.yml \
  -i infra/cherry-vpn/private/inventory.yaml \
  --vault-password-file .ansible_pass infra/cherry-vpn/deploy.yaml
```

Inventory generation reads the **applied** host key from encrypted state and
rejects a different merely prepared/pending key. It writes mode-0600 strict
`known_hosts` without trusting a scan, plus JSON-formatted YAML inventory. Preserve
its `cherry_server_id`; reruns retain a saved `vpnadmin` user and controller proxy
for the same VM. Switch the inventory from root to `vpnadmin` after bootstrap.
Do not put an idle timeout on `nc`; SSH keepalives protect long installs.

For a deliberate future replacement, prepare a fresh identity with
`prepare-bootstrap.py --rotate-host-key` (the encryption passphrase is retained),
then create/review a fresh `plan -replace=cherryservers_server.vpn`. Confirm actions
are **delete, create** only for the VM before applying. Re-run inventory generation,
Ansible, isolated direct client tests, and only then publish. Replacement destroys
the old node first and interrupts traffic; there is no unattended rotation.
The encrypted shared Vault and latest encrypted state must travel together to a
new controller; neither independently reconstructs the existing deployment.

## Paused checkpoint — 2026-10-22

Historical checkpoint, superseded by the current status above.

Provisioning was blocked by Cherry's team-owner identity verification requirement.
The attempted apply on 2026-10-21 returned HTTP 403:

```text
Identity Verification of team owner is required to order current plan.
```

Completed locally:

- Pinned OpenTofu provider, smallest-VM/price/stock guardrails and mocked tests.
- Vault-backed API authentication and shared admin/probe SSH keys.
- Idempotent key restoration and project-ID loading from `external_vars.yml`.
- Native SSH-proxy deployment playbook and observation-only regional probes.
- Reviewed plan for Debian 12 on the smallest B1 VPS in `LT-Siauliai`.

The apply created the administrator SSH public-key record, then failed before
creating the VM. Post-failure API checks confirmed **zero servers and zero IPs**
in the project. No VPN service was deployed or tested on Cherry. Existing servers
and client profiles were not changed. No retries or alternate orders were made.

Local continuation material is intentionally **not in Git**:

- `terraform.tfstate` (and backup): includes the created SSH-key record.
- `private/first-attempted.tfplan`: archived failed plan; do not reuse it.
- `cherry-token.vault`: encrypted API token.
- `private/ssh/`: restored working keys, reproducible from the Vault value in
  `external_vars.yml`.
- `terraform.tfvars` and `project.auto.tfvars.json`: current local inputs.
- Repository `.ansible_pass`: keep separate from shared encrypted material.

### Resume checklist

1. Verification is confirmed working for the tested order, and the user has
   confirmed pricing is acceptable. Recheck live pricing before a new order;
   catalogue guardrails are not an all-inclusive spending cap.
2. Restore the encrypted inputs and **current state** on a single controller.
   Do not re-enroll the keys or start with empty state. With the original state,
   the next plan should retain the existing SSH-key record.
3. Recheck project resources, account credit, current hourly rate and stock. The
   old quote was EUR 0.015/hour before tax; it is not a future price guarantee.
4. Run the local tests and restore playbook below. Generate a **fresh** plan, review
   its scope and cost, and get approval before applying; never reuse the archived
   failed plan or retry an ambiguous provider error blindly.
5. After a successful order, verify its SSH host fingerprint, run the isolated
   deployment playbook, and compare the new path with nt1 from affected networks.
   Destroy the node after the supervised trial unless continued spend is approved.

The longer-term design remains one permanent application server plus a disposable
VPN node, OpenTofu for resources, Ansible for configuration, and regional probes.
Independent recovery/config delivery and external Telegram sending are required
before autonomous recovery. The role, encrypted pre-pinned bootstrap and one
supervised destroy-first replacement are now verified live. Direct regional
reachability, sustained/UDP tests and client refresh remain unresolved. Automatic
rotation is **not implemented**. Do not treat this checkpoint as working VPN redundancy.

## Cost and limits

The public API checked during implementation quoted both smallest shared x86
plans at **EUR 0.015/hour before tax** (1 vCPU, 1 GB RAM, 20 GB SSD):

- Six hours: EUR 0.09 compute.
- One day: EUR 0.36 compute.
- Thirty days: EUR 10.80 compute.

Recheck the live catalogue and the account's actual billing before ordering:

```sh
python infra/cherry-vpn/catalogue.py
```

The B1 smallest plan currently lists 5 TB included traffic; B2 lists 1 TB. Confirm
applicable traffic allowance/overage and any address charges in the portal.
These figures are not an all-inclusive quote or a USD conversion.

OpenTofu refuses larger plans, non-EUR/unknown hourly catalogue pricing, rates
over EUR 0.015/hour, and regions without stock. It creates one VM and one SSH
public-key record only. There are no extra IP orders, volumes, snapshots,
Portainer, log stacks or paid monitoring services. OpenTofu does not install
software; the optional full Ansible role installs Docker and two proxy containers.

**This is not a hard total spending cap or an automatic expiry.** Taxes, traffic,
account-specific charges and running time still matter. There is no automatic
retry. Replacement is destroy-first to avoid overlapping compute spend. The operator monitors
node count and ongoing spend; destroy nodes when the trial ends. Power-off is not
a reliable way to stop billing. Do not enable automatic balance top-up for this test.

## Provide Cherry access — without posting secrets in chat

1. Fund the account with the intended small test balance.
2. In the portal create a dedicated project, e.g. `vpn-test`. Keep permanent
   applications out of it. Note its numeric project ID.
3. Create a dedicated key at <https://portal.cherryservers.com/settings/api-keys>.
   It needs to read the project/catalogue and create/read/delete servers and SSH
   key records. Use project scoping if available; otherwise treat it as an
   account-wide credential. Do not grant billing/user administration permissions
   if the portal permits finer restrictions.
4. Encrypt the token with Ansible Vault and the existing repository password
   file. From the repository root:

```sh
chmod 600 .ansible_pass
ansible-vault create --vault-password-file .ansible_pass \
  infra/cherry-vpn/cherry-token.vault
```

In the editor enter **only the token on one line**, without quotes, a YAML key,
or `export`. Save and close. Use an editor without plaintext swap/backup files.
The resulting Vault file and `.ansible_pass` are both ignored by Git. The password
file must never be committed or shared alongside encrypted secrets.

Alternatively, avoid an editor and plaintext temporary files with hidden input:

```sh
python -c 'from getpass import getpass; key = getpass("Cherry API key (hidden): ").strip(); assert key, "Empty token"; print(key)' | \
  ansible-vault encrypt --vault-password-file .ansible_pass \
    --output infra/cherry-vpn/cherry-token.vault
```

Tell the coding agent only **"token encrypted; project ID ..."** and your preferred
region, if any. We review the account quote/plan before creating anything. Never
commit plaintext, put the token in tfvars, or pass it as a command-line argument.

`tofu.sh` uses `ansible-vault view` to capture the decrypted token directly into
`CHERRY_API_KEY` for the child process. No plaintext file is written. Decryption
failure or empty/multiline content stops the wrapper before OpenTofu starts. An
already-set `CHERRY_API_KEY` takes precedence. The token is not a Terraform
variable and is not passed through state inputs. Avoid provider debug logging.
The earlier `~/.config/cherry-vpn/api-key` plaintext file is no longer used; remove
it if you created one.

To change the token:

```sh
ansible-vault edit --vault-password-file .ansible_pass \
  infra/cherry-vpn/cherry-token.vault
```

## Prepare locally — no billable actions

OpenTofu 1.13.1 was downloaded into ignored `.tools/tofu` and checked against its
release SHA-256 during implementation. On a fresh checkout, install OpenTofu
1.9+ using <https://opentofu.org/docs/intro/install/>. The wrapper prefers the
repo-local binary when present, otherwise `tofu` on PATH.

```sh
bash infra/cherry-vpn/tofu.sh init -backend=false
bash infra/cherry-vpn/tofu.sh validate
bash infra/cherry-vpn/tofu.sh test
python -m unittest discover -s playbooks/vpn-probe -p 'test_*.py'
python -m unittest discover -s infra/cherry-vpn -p 'test_*.py'
```

The infrastructure tests use a mocked provider and cannot order resources.

Two dedicated Ed25519 key pairs were generated once and stored in
`external_vars.yml` as `CHERRY_VPN_SSH_KEYS`, a Vault-encrypted JSON value containing
`admin_private`, `admin_public`, `probe_private`, and `probe_public`. That file also
owns `CHERRY_PROJECT_ID`. Do not generate replacement keys on a second controller.

Restore the same keys and project ID on each trusted controller:

```sh
ansible-playbook -i localhost, --vault-password-file .ansible_pass \
  infra/cherry-vpn/restore-keys.yaml
```

The playbook suppresses key output/diffs, verifies the key pairs, and writes local
working copies under ignored `private/ssh/` (directory 0700, files 0600). These
working copies have no passphrase; Vault protects the shared source, not the
restored files. Remove the working copies after use if local at-rest encryption
is required; run the playbook again to restore them. It also writes ignored
`project.auto.tfvars.json` from `CHERRY_PROJECT_ID`.

Edit `terraform.tfvars` to choose a stocked region. `LT-Siauliai` is an initial
nearby candidate, not proof of regional reachability. Only the administrator
**public** key is uploaded as an authorized key through OpenTofu; neither the
administrator nor probe private key enters state. The distinct server host
private key is deliberately included in encrypted cloud-init/state, as described above.
Use the separate unprivileged probe key for tunneling.

### Dropbox inputs and switching controllers

On the current controller, these ignored paths are symlinks into
`~/Dropbox/ssh/cherry-vpn/`:

- `cherry-token.vault`: Vault-encrypted API token.
- `terraform.tfvars`: selected plan, region and local public-key path.

The shared directory is mode 0700 and these files are mode 0600. The existing
`external_vars.yml` symlink already shares the Vault-encrypted SSH keys and
project ID. Keep `.ansible_pass` separate from Dropbox and transfer it securely.

On a fresh controller, after Dropbox has synced and the existing
`external_vars.yml` link is restored, create these links from the repository root
(only when the destinations do not already exist):

```sh
ln -s "$HOME/Dropbox/ssh/cherry-vpn/cherry-token.vault" infra/cherry-vpn/cherry-token.vault
ln -s "$HOME/Dropbox/ssh/cherry-vpn/terraform.tfvars" infra/cherry-vpn/terraform.tfvars
```

Then run `restore-keys.yaml` above to recreate local `private/ssh/` and
`project.auto.tfvars.json`. Do not sync the restored plaintext private keys.
Without shared inputs, initialize `terraform.tfvars` from the example only if it
does not already exist; copying over a symlink would overwrite the shared input.

**Shared SSH keys do not replace state**: without the current state a fresh apply
can order a duplicate server or re-enroll the SSH key. Keep live
`terraform.tfstate` and its backups local, not symlinked into Dropbox. Finish all
operations on the old controller, securely transfer the latest state (encrypt
any cloud backup), and only then operate on the new controller. Use one active
controller at a time; Dropbox is not a cross-controller lock. For regular
multi-controller operation, migrate to a locking, encrypted remote backend.

Keep saved plans local and generate a fresh reviewed plan after switching
controllers. Regenerate the private inventory and trusted `private/known_hosts`
from the applied encrypted state with `tofu.sh inventory` after restoring the
same Vault inputs and SSH keys. Preserve/reapply controller-specific transport
options and the verified administrator username. Never promote an old scan.

## Review, then provision — billable actions start at apply

From the repository root:

```sh
mkdir -p -m 700 infra/cherry-vpn/private
bash infra/cherry-vpn/tofu.sh plan -out=private/first.tfplan
```

Review that the plan adds exactly one smallest hourly VPS, creates the SSH key
only if it is not already tracked, and makes no unrelated changes. Compare its
`hourly_quote` with the account's quote. Only after explicit approval:

```sh
bash infra/cherry-vpn/tofu.sh apply private/first.tfplan
bash infra/cherry-vpn/tofu.sh output ip_addresses
```

Use the public IPv4, not a private address. Keep state private and backed up;
losing it does not stop billing. The local wrapper uses umask 077; state, plans,
private inventory and tools are ignored by Git. `.terraform.lock.hcl` is tracked.
Do not run this project from two controllers simultaneously.

## Configure the native SSH baseline

For new pre-pinned instances, use `tofu.sh inventory` above and skip the following
legacy pin/inventory setup. Strict SSH authentication already has the expected
public key from the applied encrypted state. The baseline playbook below still
works; the full `infra/cherry-vpn/deploy.yaml` also deploys the Docker proxies.

### Legacy instances without a pre-provisioned host identity

Before connecting, compare the server's SSH host-key fingerprint with the one
shown through a trusted provider console (`ssh-keygen -lf
/etc/ssh/ssh_host_ed25519_key.pub` there). `ssh-keyscan` alone does not authenticate
it. Use a separate known-hosts file and keep strict checking enabled afterward.

Once the fingerprint is verified, record it using an interactive SSH connection:

```sh
ssh -i infra/cherry-vpn/private/ssh/admin -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=ask \
  -o UserKnownHostsFile=infra/cherry-vpn/private/known_hosts root@PUBLIC_IP
```

Create `infra/cherry-vpn/private/inventory.yaml`:

```yaml
all:
  children:
    vpn_test:
      hosts:
        cherry_vpn_test:
          ansible_host: PUBLIC_IP
          ansible_user: root
          ansible_ssh_private_key_file: infra/cherry-vpn/private/ssh/admin
          ansible_ssh_common_args: >-
            -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes
            -o UserKnownHostsFile=infra/cherry-vpn/private/known_hosts
```

Run only against that dedicated inventory, **not** the existing private `hosts`:

```sh
ansible-playbook -i infra/cherry-vpn/private/inventory.yaml \
  playbooks/vpn-probe/deploy.yaml
```

The playbook waits for cloud-init before gathering facts, installs sudo and
unattended-upgrades, and creates `vpnadmin` with the existing administrator key.
It verifies non-root login and passwordless sudo in a fresh, non-multiplexed SSH
connection **before** disabling root SSH and password/interactive authentication.
It then enables daily Debian security upgrades (no automatic reboot), restricts
the separate `vpnprobe` account to local TCP forwarding without shell/subsystem
sessions, remote/Unix-socket forwarding, agent forwarding or TTY, and verifies
sudo again after reloading SSH. SSH host-key checking is forced on despite the
repository-wide default. No Docker or monitoring stack is installed.

After success, change `ansible_user: root` to `ansible_user: vpnadmin` in the
private inventory before rerunning the playbook. The administrator key is
unchanged. If verification fails, do not disable root manually; investigate via
the trusted provider console. Reboots needed for security updates remain manual.
A host firewall and automatic shutdown are not implemented.

## Add the trial node to automatically updated client profiles

The generator in `playbooks/sing-box-configs/` accepts an optional
`sing_box_secrets.extra_outbounds` list in its existing encrypted
`secrets.vault.yaml`. Add the verified Cherry outbound there **after** isolated
connectivity testing, then run the existing profile publish playbook. All three
platform selectors gain the Cherry entry, while nt1 entries, defaults, routing,
private enrollment URLs and tokens remain unchanged. Already-enrolled clients
receive the new option on their next refresh; select Cherry explicitly to test it.
No URLTest or automatic switching is enabled.

For the SSH baseline, use sing-box's `ssh` outbound with `user: vpnprobe`, the
public server address, the probe private-key **contents** in `private_key`, and
the independently verified server public host key in `host_key`. Never distribute
the administrator private key. Published profiles contain the tunnel credential:
only use the existing private HTTPS enrollment URLs. This trial credential is
shared across enrolled devices; per-device revocation needs separate keys/accounts.
SSH provides TCP only, even on a TUN client; working UDP needs another protocol.
Do not disable host-key verification to make enrollment work.

See the [profile guide](../../playbooks/sing-box-configs/README.md#additional-vpn-nodes)
for publishing and removal. Merely applying OpenTofu does not deploy the proxy,
update Vault, or publish profiles. Remove the Cherry outbound and republish before
destroying a trial node. After replacement, update its address and verified host
key in Vault and republish. This is a supervised workflow, not automatic rotation.

## Observe without changing the active VPN

In a separate terminal, create an explicit loopback SOCKS listener:

```sh
ssh -i infra/cherry-vpn/private/ssh/probe -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=infra/cherry-vpn/private/known_hosts \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 -N -D 127.0.0.1:12345 vpnprobe@PUBLIC_IP
```

Choose **two HTTPS sites you have verified work directly from the local ISP**.
The sites below are examples, not guaranteed reachable controls:

```sh
python playbooks/vpn-probe/probe.py \
  --proxy cherry=socks5h://127.0.0.1:12345 \
  --control-url https://ya.ru/ --control-url https://www.ozon.ru/ \
  --rounds 60 --interval 30 --output infra/cherry-vpn/private/probes.jsonl
```

You may add an existing loopback HTTP proxy as a second `--proxy NAME=URL` for
comparison. Requests ignore proxy environment variables and `.curlrc`, use TLS
verification, and never switch the current client. **A system TUN can still route
the SSH connection or direct checks through the active VPN.** Verify destination
bypass routes or run from a machine without that TUN before trusting results.

The helper tests two independent HTTPS destinations through each proxy. Three
consecutive rounds with both failing, while both direct controls pass, produce
`suspected_path_failure` — not proof of an IP ban. Missing/failed controls are
inconclusive and reset the streak. Single-destination failure is degradation,
not an instruction to buy another IP. Nothing rotates or sends Telegram alerts.
Streaks are intentionally in-memory for an observation session; persistent
cross-restart incident tracking is needed before using this for automation.

## Stop spending

Stop the foreground SSH tunnel with Ctrl-C, then:

```sh
bash infra/cherry-vpn/tofu.sh destroy
```

Verify in the portal that the test server is gone and there are no leftover
billable IPs/storage. Check even after a failed apply or timeout: a provider may
have allocated a resource before the client received its response. Do not blindly
retry. Reconcile/import any orphan into this state before further allocation.
Do not delete local state until billing cleanup is verified.

Next milestone: run the full role on one VM, test all three protocols from Linux,
publish the verified outbounds alongside nt1, and confirm an existing remote
profile refresh receives them. Then perform a supervised replacement drill.
Automatic rotation and an external controller remain disabled.
