# Budget VPN experiment

First stage: one disposable hourly VM, a native SSH proxy baseline, and local
observation. Existing nt1, application servers, client profiles and monitoring
are not changed. No automatic allocation, rotation, profile publication or
Telegram dependency is introduced.

SSH is a cheap **baseline**, not an obfuscation solution. If it is blocked or
unstable, test Naïve on the same VM next; do not buy a larger VM to solve filtering.
UDP and sustained-throughput testing are not covered by this initial baseline.

## Paused checkpoint — 2026-10-22

Provisioning is blocked by Cherry's team-owner identity verification requirement.
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

1. Resolve account verification with Cherry, or explicitly choose another provider
   and adapt the infrastructure before ordering anything. Do not assume another
   Cherry plan avoids the account restriction.
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
before autonomous recovery. Naïve deployment on the test node, sustained/UDP tests,
profile integration, supervised replacement and automatic rotation are **not yet
implemented**. Do not treat this checkpoint as working VPN redundancy.

## Cost and limits

The public API checked during implementation quoted both smallest shared x86
plans at **EUR 0.015/hour before tax** (1 vCPU, 1 GB RAM, 20 GB SSD):

- Six hours: EUR 0.09 compute.
- One day: EUR 0.36 compute.
- Thirty days: EUR 10.80 compute. Do not leave a short experiment running all month.

Recheck the live catalogue and the account's actual billing before ordering:

```sh
python infra/cherry-vpn/catalogue.py
```

The B1 smallest plan currently lists 5 TB included traffic; B2 lists 1 TB. Confirm
applicable traffic allowance/overage and any address charges in the portal.
These figures are not an all-inclusive quote or a USD conversion.

OpenTofu refuses larger plans, non-EUR/unknown hourly catalogue pricing, rates
over EUR 0.015/hour, and regions without stock. It creates one VM and one SSH
public-key record only. There are no extra IP orders, volumes, snapshots, Docker,
Portainer, log stacks or paid monitoring services.

**This is not a hard total spending cap or an automatic expiry.** Taxes, traffic,
account-specific charges and running time still matter. There is no automatic
retry. A deliberate replacement can briefly run two nodes. Start with a six-hour
session, set a reminder, and destroy the test node afterward. Power-off is not a
reliable way to stop billing. Do not enable automatic balance top-up for this test.

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
cp infra/cherry-vpn/terraform.tfvars.example infra/cherry-vpn/terraform.tfvars
```

The playbook suppresses key output/diffs, verifies the key pairs, and writes local
working copies under ignored `private/ssh/` (directory 0700, files 0600). These
working copies have no passphrase; Vault protects the shared source, not the
restored files. Remove the working copies after use if local at-rest encryption
is required; run the playbook again to restore them. It also writes ignored
`project.auto.tfvars.json` from `CHERRY_PROJECT_ID`.

Edit `terraform.tfvars` to choose a stocked region. `LT-Siauliai` is an initial
nearby candidate, not proof of regional reachability. Only the administrator
**public** key is uploaded through OpenTofu; neither private key enters state.
Use the separate unprivileged probe key for tunneling.

For another controller, securely transfer/sync `external_vars.yml`, the encrypted
`cherry-token.vault`, the Vault password separately, and the latest OpenTofu
state. Recreate `terraform.tfvars` with the same region/plan. **Shared SSH keys do
not replace state**: without the current state a fresh apply can order a duplicate
server. Use one active controller at a time; do not use a live Dropbox-synced state
file as a substitute for cross-controller locking. Transfer state only between
stopped sessions and back it up securely.

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

The playbook waits for cloud-init, creates a locked-password unprivileged account,
authorizes its separate key, and disables password/interactive authentication.
The account permits local TCP forwarding but no shell sessions, remote TCP
forwarding, agent forwarding or TTY. Root key-based administration remains.

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

Next milestone, only after a successful regional test: Naïve on this same VM,
then a supervised replacement drill, then remote-profile integration. Automatic
rotation and an external controller remain deliberately disabled for the $10 trial.
