# Budget VPN experiment

Supervised trial: one disposable hourly VM, native SSH forwarding, and optional
Dockerized Naïve, VLESS/REALITY and Hysteria 2/Brutal, with Linux as the first client. Existing nt1,
application servers and active client configuration are kept separate. Full
deployment also registers Cherry host/container metrics in the existing monitoring stack.
VPN protocol monitoring is maintained separately in `github.com/akorzunin/vpn-monitor`. No automatic allocation,
rotation or profile publication is introduced.

SSH is a cheap **baseline**, not an obfuscation solution. If it is blocked or
unstable, test Naïve on the same VM next; do not buy a larger VM to solve filtering.
UDP and sustained-throughput testing are not covered by this initial baseline.

## Current status

**Retired on 2026-11-01:** dyn1 (server `1044039`, `84.32.231.93`) and its
Cherry SSH-key registration were destroyed through a reviewed OpenTofu plan.
The project API subsequently returned zero servers, IPs and storage. The
`akorz-dyn1.duckdns.org` record was cleared; shared SSH inventory and monitoring
membership were removed, with VPN probe alerts disabled. Encrypted state was
backed up to Dropbox; retain state and private backups.

All three public profiles were verified to match the generated Aurora-only
profiles, defaulting to `aurora-vless`, with the existing URLs/tokens unchanged.
Two isolated Aurora HTTPS checks passed. Enrolled clients must refresh; the dyn1
SSH hop to nt1 and any static Cherry/Discord configurations no longer work.
Native controller and workstation Docker proxy configurations were not changed.
**Do not run apply/deploy to restore access:** the configuration below can create
a new billable VM and requires fresh review and approval.

### Historical deployment status (before retirement)

One Debian 13 B1 VM was running in `NL-Amsterdam`, DNS
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

Monitoring was added separately on 2026-10-26: Telegraf runs in
`/srv/monitoring/telegraf`, and the existing workstation Prometheus scrapes this VM
as `dyn1`. Shared dashboards, node-availability and disk-space alerts cover it.
VPN containers were not restarted. Monitoring membership is manual: update it
when replacing/deleting the VM; see the [monitoring guide](../../playbooks/ws-logs/README.md).

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

Cherry SSH, Naïve, VLESS, VLESS-over-Naïve and Hysteria 2 are published in all
three existing private platform profiles. Blocked nt1's direct and chained routes
have been removed. URLs/tokens are unchanged; all platforms now default to
`cherry-vless-via-naive`. Current Cherry credentials live in the profile Vault,
so publish without `sing_box_extra_outbounds_file` to avoid duplicate tags.
Already-enrolled devices receive these changes on refresh; there is no automatic failover.

**This workstation was not enrolled**, by explicit user choice. Its original
`ssh-via-workstation` selection/local fallback remains active, no enrollment file
was created and its update timer remains inactive. Published-profile testing used
a temporary isolated core, not the active service. Private configs/results are
in `private/`. At that stage, UDP, sustained stability, other client platforms and
autonomous replacement remained unverified; see the later Hysteria 2 trial below.

The catalogue quote remains EUR 0.015/hour; the server API has reported a EUR 0.02
hourly unit price. The user accepted API pricing; these fields are not a verified
all-inclusive bill. The DuckDNS token's missing YAML `!vault |` marker was corrected
without changing its encrypted ciphertext or `external_vars.yml` symlink.

## Hysteria 2 / Brutal in the dynamic-node flow

Initially deployed on dyn1 on 2026-10-28 through [`hysteria2.yaml`](hysteria2.yaml).
Hysteria 2 is now also part of the normal [`deploy.yaml`](deploy.yaml) flow, after
Naïve obtains its certificate and before combined client export and monitoring.
It reuses the existing `vpn-hysteria2` Compose project in `/srv/deploy/vpn-hysteria2`
and the same digest-pinned sing-box 1.14.4 image as VLESS: no trial-to-full migration
or second listener is needed. It publishes **UDP/443**; Naïve keeps TCP/443 and
VLESS keeps TCP/8443.

The user found it less stable than SSH. Keep it as an additional manual option,
not a replacement or new default. The normal flow exports all four protocols and
configures eight monitoring checks (two destinations per protocol); publication
remains explicit. No active-client change is made.

The Hysteria-only entry point below is retained for scoped redeployment without
reconfiguring the other services, DNS or monitoring:

Requirements: the existing pinned private inventory, non-root `vpnadmin` sudo,
Docker/Compose, `vpnproxy` account and Naïve's valid domain certificate. The
container mounts only that domain's certificate directory read-only, not Caddy's
ACME account keys. Caddy still owns renewal; sing-box reloads changed certificate
and key files. A provider firewall, if added, must allow UDP/443.

```sh
ansible-playbook -i infra/cherry-vpn/private/inventory.yaml \
  --vault-password-file .ansible_pass infra/cherry-vpn/hysteria2.yaml
```

Both entry points load the same `infra/cherry-vpn/hysteria2.vault.yaml`. **Restore
this encrypted file** with `secrets.vault.yaml` on new controllers; replacements
reuse it and never generate a new password. For a new project only, prepare it
before deployment with `python infra/cherry-vpn/prepare-secrets.py --hysteria2`.
This writes directly into Vault using `.ansible_pass` and refuses existing files
or symlinks. The original trial password is preserved. Plaintext exports under
`private/` must not be committed. Run deployment without `--check`.

Initial client targets are **20 Mbps download / 5 Mbps upload**, not measured
capacity. Both positive client bandwidth fields select Brutal rather than BBR;
server caps are set in the opposite directions. Tune the two
`vpn_node_hysteria2_download_mbps` / `vpn_node_hysteria2_upload_mbps` variables with
`-e` when rerunning, based on sustained path measurements rather than ISP line rate.
Do not increase them merely to make a speed test look faster.

Normal deployment appends `cherry-hysteria2` to `private/cherry-outbounds.json`
and adds port `12343` to the combined `private/cherry-test.json`. Existing protocol
order and the test profile's SSH default are preserved. The existing publisher
accepts this fourth outbound without changing platform defaults or enrollment URLs.

Additional Hysteria-only artifacts remain available (do not run both test clients
simultaneously, since they share port `12343`):

- `private/cherry-hysteria2-test.json`: isolated Linux mixed HTTP/SOCKS listener,
  `127.0.0.1:12343`, no TUN or API. Uses the existing Linux bypass mark `0x2024`
  so the outer QUIC connection avoids the active VPN. Requires sudo for `SO_MARK`;
  verify `ip route get 84.32.231.93 mark 0x2024` uses the physical uplink on this
  workstation. Recheck the bypass mark if the active VPN routing changes.
- `private/cherry-hysteria2-outbounds.json`: portable outbound, verified TLS/SNI,
  no Linux-specific mark; not merged into any published profile.

Start the isolated client in a terminal, then test from another:

```sh
sudo sing-box run -c infra/cherry-vpn/private/cherry-hysteria2-test.json
# In another terminal:
curl --disable --fail --noproxy '' --proxy http://127.0.0.1:12343 \
  --connect-timeout 10 --max-time 20 https://api.ipify.org/
```

For a Twitch trial, configure **both HTTP and HTTPS proxy** to `127.0.0.1:12343`
in a separate browser profile. Keep the same stream/quality and compare stall
frequency/duration against the existing VPN over longer sessions. Stop the test
client with Ctrl-C afterward. This does not switch the machine's active VPN.

**Initial observations:** direct marked workstation-to-dyn1 QUIC succeeded with
certificate verification enabled, returned egress `84.32.231.93`, and passed a
second independent HTTPS check. Two 30,000,000-byte Cloudflare downloads completed
in 12.36 / 12.34 seconds (about 19.4 Mbps payload throughput). An intentionally
invalid password was explicitly rejected. A second deployment reported zero
changes; existing Naïve/VLESS container IDs and uptimes were preserved. These
short checks do **not** establish long-term consistency or Twitch playback quality.
The temporary smoke clients were stopped; only the server remains running.

To temporarily stop/remove only the Hysteria 2 container and its dedicated network
(the next normal deployment will restore it):

```sh
ansible -i infra/cherry-vpn/private/inventory.yaml cherry_vpn_test \
  -e ansible_host_key_checking=true -e ansible_become_flags=-n -b \
  -m ansible.builtin.command \
  -a 'docker compose -p vpn-hysteria2 -f /srv/deploy/vpn-hysteria2/compose.yaml down'
```

Credentials, certificate state and other VPN services are left intact.

## Host monitoring

[`monitoring.yaml`](monitoring.yaml), included by `deploy.yaml`, installs Telegraf,
persists Cherry membership in the shared private `hosts`, redeploys the shared
stack, and verifies host/container metrics. It does not check VPN protocols.

```sh
ansible-playbook -i hosts -i infra/cherry-vpn/private/inventory.yaml \
  --vault-password-file .ansible_pass infra/cherry-vpn/monitoring.yaml
```

Restore the applied private inventory and dedicated keys first. Load both
inventories and run without `--limit` or `--check`. Existing Docker/Compose,
passwordless `vpnadmin` sudo, workstation sudo, and shared Grafana/Telegram
credentials in `external_vars.yml` are required. Port 9273 remains restricted to
`monitoring_workstation_allowed_sources`; verify the scraper's actual source CIDRs.
Exporter failure alone is not evidence of VPN blocking. Retire monitoring membership
separately when destroying a VM.

The former workstation probe and its standalone diagnostics have been removed;
VPN protocol monitoring is now a separate Go project, `github.com/akorzunin/vpn-monitor`.

## Secure automatic bootstrap

For a new deployment only, create `secrets.vault.yaml` with `prepare-secrets.py`
and `hysteria2.vault.yaml` with `prepare-secrets.py --hysteria2`.
For an existing deployment **reuse both encrypted files** and add/retain the main Vault's
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
ansible-playbook -i hosts -i infra/cherry-vpn/private/inventory.yaml \
  --vault-password-file .ansible_pass infra/cherry-vpn/deploy.yaml
```

Inventory generation reads the **applied** host key from encrypted state and
rejects a different merely prepared/pending key. It writes mode-0600 strict
`known_hosts` without trusting a scan, plus JSON-formatted YAML inventory. Preserve
its `cherry_server_id`; reruns retain a saved `vpnadmin` user and controller proxy
for the same VM. Switch the inventory from root to `vpnadmin` after bootstrap.
Full `deploy.yaml` also refreshes the managed `dyn1` block in the shared `hosts`
after verifying administrator SSH/sudo, preserving unrelated Vault records and
the inventory symlink. Run it after each replacement so manual access follows the
new IP, administrator key and strict host-key file. `ssh-sel.nu` must honor
`ansible_ssh_private_key_file` and `ansible_ssh_common_args`; the dotfiles version
now does (including quoted proxy options).
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

`install.sh` links these ignored paths into `infra/cherry-vpn/` from
`~/Dropbox/ssh/cherry-vpn/` (or `$DROPBOX_SSH_DIR/cherry-vpn/`):

- `cherry-token.vault`: Vault-encrypted API token.
- `terraform.tfvars`: selected plan, region and local public-key path.

The shared directory is mode 0700 and these files are mode 0600. The existing
`external_vars.yml` symlink already shares the Vault-encrypted SSH keys and
project ID. Keep `.ansible_pass` separate from Dropbox and transfer it securely.

The Dropbox layout is:

```text
ssh/
  hosts
  external_vars.yml
  # Optional legacy service inputs use their repository-relative playbooks/ paths.
  cherry-vpn/
    cherry-token.vault
    terraform.tfvars
    terraform.tfstate          # encrypted snapshot, not a live backend
    terraform.tfstate.backup   # encrypted recovery snapshot, when present
```

On a fresh controller, wait for Dropbox to sync, then run from the repository root:

```sh
./install.sh
# Alternatively: DROPBOX_SSH_DIR=/path/to/Dropbox/ssh ./install.sh
```

This restores the base and Cherry links plus any shared legacy service inputs
(see [Setup](../../README.md#setup)). Reruns retain correct links and refuse to
overwrite any existing file or different/broken link. On the working controller,
use `./install.sh --migrate` once to move existing local inputs into this layout
and replace them with links; conflicting shared copies are refused. Both Cherry inputs are required when
`cherry-vpn/` exists; when absent, the installer reports skipping OpenTofu links.

Install OpenTofu as described above and securely restore `.ansible_pass` separately.
`secrets.vault.yaml`, containing the state-encryption secret and host identity, is
already tracked as Vault ciphertext; use the revision matching the deployed node.
Do not generate new credentials to recover an existing deployment.

Then run `restore-keys.yaml` above to recreate local `private/ssh/` and
`project.auto.tfvars.json` with paths for this checkout, and run
`bash infra/cherry-vpn/tofu.sh init -backend=false` to download the pinned provider.
Do not sync `.terraform/`, `.tools/`, or the restored plaintext private keys.
Without shared inputs, initialize `terraform.tfvars` from the example only if it
does not already exist; copying over a symlink would overwrite the shared input.

**Shared SSH keys do not replace state**: without the current state a fresh apply
can order a duplicate server or re-enroll the SSH key. Store encrypted snapshots
in Dropbox, while OpenTofu continues using regular local files (not symlinks).

After finishing operations on the old controller, including any failed apply
that might have changed state, publish the latest snapshot:

```sh
bash infra/cherry-vpn/tofu.sh backup-state
```

Wait for Dropbox to finish uploading, stop using the old controller, and wait for
sync on the new controller. After the setup/restore-keys/init steps above, run:

```sh
bash infra/cherry-vpn/tofu.sh restore-state
bash infra/cherry-vpn/tofu.sh state list
```

Transfer commands use the same Dropbox directory discovery as `install.sh`.
For a custom directory, pass the same **absolute** `DROPBOX_SSH_DIR` to each
command. They need neither OpenTofu nor the Vault password just to copy ciphertext.
Only the default local backend/workspace is supported. Both the current state
and its backup (when present) must already be encrypted; plaintext is refused.
Writes are atomic per file and mode 0600. No SSH private keys, plans or Vault
passwords are copied.

`restore-state` refuses to replace any different local state or backup. When
returning to a previously used machine, deliberately archive its old local state
and backup under `private/` first, then restore the synced snapshot. Never discard
an unbacked-up newer local state. `backup-state` explicitly replaces the shared
snapshots, so do not run it from a stale controller. It is not automatic: back up
after every operation that changes state and before switching machines.

Use one active controller at a time. The wrapper's local lock protects transfer
against local wrapper operations, but **Dropbox is not a cross-controller lock**
and cannot prove sync is complete or prevent stale-controller uploads. For
simultaneous controllers, use a locking, encrypted remote backend instead.

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
  infra/cherry-vpn/bootstrap.yaml
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

## Stop spending

Stop any manually started test clients, then:

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
