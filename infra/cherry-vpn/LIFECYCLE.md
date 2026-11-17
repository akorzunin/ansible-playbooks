# Dynamic nodes: supervised creation and deletion

A node's role identity is `dyn1`, `dyn2`, etc. Provider-specific names belong only
to the provisioning adapter. Use `-e dyn_node=dynN` on every Ansible entry point;
the default is `dyn1` for compatibility. DNS is `akorz-dynN.duckdns.org` and
published choices are `dynN-ssh`, `dynN-naive`, `dynN-vless`, plus chained SSH
when the workstation hop exists. Neither Hysteria nor VLESS-over-Naïve is part of
the dynamic setup.

**Repository changes alone do not migrate running services.** In particular,
the current dyn1 connection can continue using its existing `cherry-*` config
until a separately supervised migration. Do not restart an agent's transport
while that agent is using it.

## Prerequisites

- Existing shared `hosts`, monitoring groups, DuckDNS credentials, project ID,
  administrator/probe keys, Vault password, shared VPN/profile Vaults.
- OpenTofu >=1.9,<2, pinned provider, Ansible/Docker collections, Python, curl,
  ssh-keygen and the matching sing-box core for local checks.
- Restore the **latest encrypted state and bootstrap Vault** for existing nodes.
  Never initialize a replacement backend to recover lost state.
- One active controller. Wait for Dropbox sync before switching machines;
  [backup/restore details](README.md#encrypted-state-and-controller-handoff).
- Review regional availability and account pricing. Each VM is billable until
  deleted, even if configuration/tests fail. Multiple nodes multiply spend.

## Initialize an additional node (no cloud allocation)

The legacy dyn1 backend stays at `infra/cherry-vpn/`; it must not be initialized
again. For a genuinely new name:

```sh
# Region is optional; omitted means inherit the shared terraform.tfvars region.
bash infra/cherry-vpn/tofu.sh --node dyn2 initialize-node --region NL-Amsterdam
```

This explicitly creates a new encrypted empty state with an independent
bootstrap Vault, copies approved tfvars, and backs up recovery inputs to Dropbox.
It refuses an existing local node or shared node directory. No server is
allocated. After interrupted initialization, inspect/recover the partial local
and shared files; do not blindly delete state and retry. The region is saved per
node. To choose another region for an **existing** node, destroy it first, then
edit its node inputs and provision again; lifecycle refuses updates/replacements.

For dyn1, edit its original `terraform.tfvars` only after destroying the VM.
Existing dyn1 provider hostname/key registration names are deliberately retained
to avoid an in-place infrastructure update; new nodes use `dynN` provider names.

## Provision and publish

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  infra/cherry-vpn/provision.yaml -e dyn_node=dyn2
```

The playbook:

1. Requires recovery files, decrypts inputs, rejects unrelated tracked resources
   and verifies writable encrypted backup storage. No Hysteria Vault is needed.
2. Restores separate administrator/probe keys. Prepares a host identity only if
   no server is tracked; retains the state-encryption passphrase.
3. Saves and reviews a plan that permits only create/no-op for this node's VM
   and provider SSH-key registration. Shows region/plan/price. Live price/stock
   allocation checks run only for a new VM, not an existing node or deletion.
   If a tracked VM disappeared outside this workflow, unexpected recreation is
   refused; reconcile its state explicitly before requesting another allocation.
4. Requires typing **`deploy dyn2`**; noninteractive approval fails closed.
5. Applies and backs up state even on apply failure. Pins the applied host key,
   bootstraps non-root administration, deploys SSH/Naïve/VLESS, updates only this
   node's DNS and registers `dyn2` host/container monitoring.
6. Tests authenticated HTTPS/exit IPv4 and direct VLESS UDP/STUN. Registers only
   this node, publishes using existing tokens, then retests published choices.

Other nodes and active clients are not reconfigured. Refresh an enrolled client
and explicitly select a new choice. Failed UDP tests stop publication; STUN
success does not establish Discord voice or long-term path quality.

## Migrate legacy dyn1 naming

Run the provision entry point with `-e dyn_node=dyn1` **only in a supervised
maintenance window**, with an independent management path available. Its plan
must be no-op for the existing VM; do not approve a surprise creation.

Registration atomically removes managed `cherry-*` entries and adds `dyn1-*`.
Legacy direct/SSH defaults map to their dyn1 equivalents; retired Hysteria or
VLESS-over-Naïve defaults map to `dyn1-vless`. Other defaults, unrelated exits and
enrollment tokens are preserved. The old managed Cherry monitoring block is
removed in favor of the per-node block. Existing Hysteria is stopped and its
server configuration removed; Caddy certificates and other services stay intact.

Static workstation/Discord configs are **not** updated by profile publication.
After confirming the new profiles, deploy them separately using their new
`dyn1-vless` default. Do not switch the running agent's connection mid-session.
Old client configs, ignored exports and offline clients may retain legacy names.

## Retire one node

Specify a known surviving profile tag and its inventory hostname; there is no
hard-coded GE2 fallback (GE2 may already be retired):

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  infra/cherry-vpn/destroy.yaml -e dyn_node=dyn2 \
  -e dyn_fallback=dyn1-vless -e dyn_fallback_node=dyn1
```

After plan review, type **`destroy dyn2`**. The playbook removes only dyn2 profile
entries, uses the fallback only if dyn2 was the default, publishes/tests surviving
exits, removes dyn2's managed inventory blocks and refreshes monitoring, then
applies the saved deletion plan. Finally it backs up state, confirms no managed
resources remain in that backend, clears only `akorz-dyn2` DNS, and deletes stale
inventory/SSH pins. Keys, Vaults, encrypted plans and state backups are retained.
It refuses to publish an empty/broken selector or proceed without a surviving
exit. Deleting the final exit requires a separately designed client shutdown.

## Failure recovery

Administrator verification uses a fresh, isolated multiplexed SSH connection with
bounded connection retries. Explicit controller-side completion checks stop VPN,
monitoring and publication if bootstrap or VPN deployment is skipped after an
unreachable-host error. A missing client export is a deployment error, not a UDP
failure. Old monitoring labels may linger in historical data or dashboard caches;
check active Prometheus targets before assuming a duplicate scrape.

Any phase failure aborts later phases. Read the actual state and provider portal
before retrying after API timeouts: orphan resources may still be billable.
Configuration/publication failures do not roll back billing. Keep encrypted
backups; never bypass the plan guard with raw apply or discard state to retry.
DNS currently moves before certificate/service readiness: this is a supervised,
downtime-tolerant workflow, not health-gated zero-downtime rotation.
