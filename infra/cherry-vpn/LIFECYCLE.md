# dyn1: deploy and destroy through Ansible

Run these commands **from the repository root**, on one active controller only.
`dyn1` is the disposable Cherry VM at `akorz-dyn1.duckdns.org`; its client choices
retain the existing `cherry-*` names. **GE2 is not provisioned, reconfigured or
removed.** Its profile entries and the current profile default are preserved.
The shared profile host/SSH allowlist and monitoring stack are updated.

## Before the first run on this controller

- Install Ansible and the collections in `requirements.yml`, OpenTofu 1.9+
  (or the existing ignored `infra/cherry-vpn/.tools/tofu` binary), Python with
  PyYAML, Docker, and the Naïve-enabled sing-box core used by the existing VPN
  checks. See the [VPN node guide](../../roles/vpn_node/README.md).
- Restore `hosts`, `external_vars.yml`, `.ansible_pass`, and existing encrypted
  Cherry/profile Vault files. The wrapper **also** reads `.ansible_pass` from the
  repository root; supplying only `--ask-vault-pass` is insufficient.
- Restore the shared Cherry inputs with `bash install.sh`; check
  `infra/cherry-vpn/terraform.tfvars` for the desired **region**, smallest plan,
  and `ssh_public_key_path = "private/ssh/admin.pub"`. Do not put an API token or
  duplicate `project_id` there. `CHERRY_PROJECT_ID` and the administrator/tunnel
  keys come from `external_vars.yml`; the API token comes from
  `infra/cherry-vpn/cherry-token.vault` (or `CHERRY_API_KEY`).
- Restore the **latest encrypted state**, including the intentionally empty state
  left after the previous destruction. Never recreate an empty state to recover
  a missing controller. Wait for Dropbox sync, then, if no local state exists:

  ```sh
  bash infra/cherry-vpn/tofu.sh restore-state
  ```

  A conflicting local state is refused. Follow the [state recovery instructions](README.md#dropbox-inputs-and-switching-controllers)
  rather than overwriting it. Retain the original Vault state-encryption secret.
- Ensure GE2 works and SSH/sudo access to the existing profile host and monitoring
  server works. Their inventory groups are required. These playbooks do not
  repair the shared infrastructure or migrate the external VPN-monitor service.

No cron, automatic expiry, replacement or cross-controller locking is provided.
Do not run concurrent lifecycle commands, raw OpenTofu commands, or another
publisher while a run is in progress. Dropbox snapshots are not a locking backend.

## Deploy

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  infra/cherry-vpn/provision.yaml
```

The playbook:

1. Checks recovery inputs, initializes the pinned provider and backs up encrypted
   state. Missing state stops the run **before allocation**.
2. Restores existing SSH keys. With no VM tracked, prepares a fresh server host
   identity without changing the state-encryption passphrase or VPN credentials.
3. Saves an encrypted plan and shows a non-secret summary: exact resource actions,
   project, region, smallest plan, image and catalogue compute quote. It refuses
   updates, replacement, imports and unrelated resources. **Check the project ID
   and current account price**: the catalogue ceiling is not an all-inclusive bill.
4. Waits for you to type **`deploy dyn1`**. Any other answer aborts without apply.
5. Applies that exact plan and backs up state, even if apply fails. **Billing starts
   here**, not when VPN configuration finishes.
6. Generates SSH pins from applied encrypted state, waits for SSH, verifies
   `vpnadmin`/sudo before disabling root SSH, and deploys the existing VPN role
   and host/container monitoring. DNS/ACME uses only the dyn1 hostname.
7. Tests isolated authenticated exits before updating the encrypted profile source.
   It replaces only `cherry-*` entries, preserving GE2, other exits, enrollment
   URLs/tokens and the current default. Then it publishes and tests the generated
   direct/chained choices, including the workstation SSH hop.

Refresh a client's existing remote profile, then explicitly select a `cherry-*`
choice. **No active workstation client, TUN, system proxy or profile default is
switched.** Publication cannot refresh an offline device. Short HTTPS checks do
not prove sustained availability, direct-ISP reachability or working voice/UDP;
see the [isolated checks](../../roles/vpn_node/README.md#isolated-checks-and-maintenance).

Rerun the same command after a configuration failure; it reuses the tracked VM
and credentials. Successful SSH bootstrap saves `vpnadmin` for retries. A no-op
infrastructure plan still leads to configuration, checks and publication. A
requested region/plan/host-identity change is **not** an implicit replacement:
use the destroy flow first, then deploy again (downtime, no overlapping spend).

## Destroy

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  infra/cherry-vpn/destroy.yaml
```

After reviewing the deletion summary, type **`destroy dyn1`**. The playbook:

1. Removes only Cherry's entries from the encrypted profile source and republishes
   surviving exits. If Cherry was the default, falls back to
   `ge2-vless-via-naive`; otherwise preserves the existing default. Missing or
   invalid surviving exits stop the run without deleting the VM.
2. Checks GE2 connectivity without configuring GE2. Removes the managed dyn1 SSH
   and Cherry monitoring blocks from `hosts`, reloads inventory, and redeploys
   monitoring without that target. Unmanaged Cherry monitoring entries are refused.
3. Applies the reviewed destroy plan and backs up encrypted state even on failure.
4. Requires no managed Cherry resources remaining in state, clears only
   `akorz-dyn1` DuckDNS records, and removes stale generated inventory/SSH pins.
   Keeps keys, encrypted Vaults, plans and state/backups for recovery and reuse.

**Check the Cherry portal afterward:** the dedicated project should have no
server, billable IP or storage left. A clean state alone cannot prove that an API
timeout did not leave an orphan. Retain backups; wait for Dropbox sync before
switching controllers. Refresh enrolled clients; manually stop any isolated test
clients/static Cherry configurations you started outside these playbooks.

## If a run fails

- A failure aborts later phases, but **is not a rollback**. A created VM keeps
  billing. Run `destroy.yaml` to retire it, or fix the error and rerun provision.
- The planning task hides raw output. If it fails, run
  `bash infra/cherry-vpn/tofu.sh plan -input=false` locally to inspect normal
  redacted stock/price/API diagnostics. Planning alone does not allocate a VM;
  do not dump `show -json` or turn on debug logging.
- On apply timeout/failure, inspect the provider portal and encrypted state before
  retrying. Reconcile/import an orphan into the existing state before allocating
  again. Never delete state or buy another VM to work around a failed response.
- If configuration succeeds but exit checks fail, new profiles are not published.
  If publication/final checks fail, some clients may already have refreshed;
  repair and rerun. Existing published dyn1 entries can remain stale after a
  failed new deployment; publication is not transactional.
- Destroy deliberately stops before infrastructure deletion if profile retirement,
  surviving-exit checks or monitoring updates fail. **The VM is still billable.**
  Fix the shared service and rerun the same command. If stopping spend is urgent,
  explicitly review a standalone destroy plan with `tofu.sh plan -destroy`, apply
  that saved plan, and run `tofu.sh backup-state`; then rerun `destroy.yaml` to
  finish cleanup. Check the portal for orphans in either case.
- Do not use `--check`, `--limit`, tags, `--start-at-task`, or auto-answer scripts.
  The supported entry points are complete, interactive, supervised runs. Do not
  enable Ansible/OpenTofu debug logging or dump decrypted plans/state.

For historical tests, provider setup and recovery details, see [README.md](README.md).
