# VPN node

Reusable configuration for a **dedicated Debian x86_64 node**, not nt1. The role
never creates cloud resources, rotates nodes, republishes profiles or changes the
active client. Native SSH stays on the host; Naïve and VLESS run in Docker.

| Public port | Service |
| --- | --- |
| TCP 22 (or inventory SSH port) | Key-only administration and `vpnprobe` TCP forwarding |
| TCP 80 | ACME certificate issuance / HTTPS redirect |
| TCP 443 | Authenticated Naïve HTTP/2 proxy |
| TCP 8443 | VLESS/REALITY + Vision, sing-box server |

VLESS can relay UDP over its TCP connection; it does not require a public UDP
listener. SSH and this Naïve setup are TCP-only. UDP and ISP/mobile behavior still
need separate client tests. Naïve owns port 443; an SNI router would be needed to
also offer REALITY on 443. There is no Docker socket, management API or panel
exposed to clients, and no host firewall is installed by this role.

## Inputs and deployment

Use a public IPv4 and a dedicated DNS hostname (`vpn_node_domain`). With
`DUCKDNS_TOKEN` loaded from external variables, the role updates **only** that
DuckDNS hostname to the explicit node IPv4. The hostname must already belong to
the token's account. Tokens stay in encrypted inputs, are URL-encoded, never
logged, and never forwarded through HTTP proxies or redirects. Encrypted scalar
values must use YAML's `!vault |` tag, not a plain string containing Vault armor.
Other DNS providers must be configured separately. DNS is polled after updating;
A records must point **only** to this IPv4, with no AAAA records (IPv6 deployment
is not implemented). Existing records are never automatically cleared. Allow
inbound TCP 80/443/8443 and SSH in any provider firewall. `vpn_node_reality_server_name`
defaults to `www.google.com`; its TLS 1.3 handshake endpoint must be reachable from
the node. Do not repoint nt1's hostname or reuse production credentials.

Restore the existing administrator/probe SSH keys first (see the Cherry guide).
Generate the shared proxy credentials **once**, encrypted directly into Vault:

```sh
python infra/cherry-vpn/prepare-secrets.py
```

Requires Python, OpenSSL and Ansible Vault on the controller. The script writes
`infra/cherry-vpn/secrets.vault.yaml` mode 0600 with `vpn_node_credentials`:
`naive_username`, `naive_password`, `vless_uuid`, `reality_private_key`,
`reality_public_key`, `reality_short_id`. No plaintext file or command-line secret
is produced. Existing files/symlinks are refused, not regenerated. Keep this
**encrypted** file with shared deployment inputs across controllers and transfer
the Vault password separately. Replacing a VM must not silently rotate these
credentials. Do not commit generated plaintext client files.

The Cherry entry points use `akorz-dyn1.duckdns.org` and load `DUCKDNS_TOKEN` from
`external_vars.yml`. To update DNS immediately after creating a VM, without
making an SSH connection:

```sh
ansible-playbook -i localhost, --vault-password-file .ansible_pass \
  infra/cherry-vpn/update-dns.yaml -e vpn_node_public_address=PUBLIC_IP
```

DNS ownership is **not** SSH host authentication. The Cherry project now prepares
an Ed25519 server key before provisioning and installs it through cloud-init.
Run `prepare-bootstrap.py` and, for legacy local state, `tofu.sh migrate-state`
as described in the Cherry guide. State/plans are encrypted because they contain
that server private key; the master secret and host identity live in the shared
Vault alongside (but separate from) proxy credentials. Then `tofu.sh inventory`
pins the **applied** identity and generates the isolated inventory. No console,
password bootstrap, scan acceptance or first-use trust is needed for a node
created by this workflow. Older unpinned nodes still need independent verification.

The optional `inventory --proxy-command 'nc -X connect -x 127.0.0.1:12334 %h %p'`
selects a controller-specific transport while retaining strict end-to-end SSH
verification. Do not set a netcat idle timeout; long package installs need a
persistent connection. Dependence on the active local VPN is not an autonomous
recovery path. After pinning:

```sh
ansible-playbook -i hosts -i monitoring.inventory.yml \
  -i infra/cherry-vpn/private/inventory.yaml \
  --vault-password-file .ansible_pass infra/cherry-vpn/deploy.yaml
```

This entry point bootstraps `vpnadmin`, proves fresh key-only non-root login and
passwordless sudo, then enables administrator-only multiplexing and invokes
`vpn_node`. SSH reload is followed by a reset and fresh sudo access check.
Cloud-init's disabled exit code is accepted only with the explicit provider
marker, exact disabled status and working Python; other failures still stop. After success, change the private
inventory's `ansible_user` from `root` to `vpnadmin` for reruns. Do not use the
production `hosts` inventory for node configuration. `--check` is refused: this
bootstrap needs a real new-connection test before disabling root SSH.

For an already bootstrapped node, use `roles: [vpn_node]` with `become: true`,
`become_flags: -n`, `ansible_host_key_checking: true`, non-root `ansible_user`,
`vpn_node_domain`, and the shared Vault variables. Set `vpn_node_name` to a stable
DNS-safe name when the inventory alias is not suitable. Public address defaults
to `ansible_host`; SSH key paths and client output default to Cherry's private
directory. The role verifies sudo and matching probe keys before changing SSH.

## What is installed

- Daily unattended **Debian security** updates, with automatic reboots disabled.
  Required reboots remain an administrator responsibility. Docker/upstream proxy
  releases are not automatically upgraded by this security-only apt policy.
- Restricted `vpnprobe` native SSH forwarding: no shell/subsystem sessions, agent,
  TTY, remote TCP forwarding or Unix-socket forwarding. Root SSH is disabled only
  after verified non-root sudo access. Host-key checking remains enabled.
- Docker Engine/Compose and two unprivileged, read-only, capability-dropped
  containers with memory/PID/log limits. No Docker group access is granted.
- Naïve `v2.11.7-naive2`: checksum-verified upstream amd64 binary packaged into a
  scratch image, without compilation. VLESS: upstream sing-box `1.14.4`, pinned by
  immutable image digest. The latest Xray `26.10.21` failed REALITY verification
  with the installed sing-box `1.14.2` client in an isolated local test; this role
  does **not** work around that by deploying an older Xray release.
- Private server configs under `/srv/deploy/vpn-node`, and persistent certificates
  and ACME account under `/var/lib/vpn-node`. Recreating containers preserves both.
  Back these up securely; they are not stored in the images.

Both configurations are checked in their pinned containers before activation.
Reruns preserve credentials/certificates and recreate containers only when their
image/configuration changes. Syntax checks are not an end-to-end health gate;
post-activation failure currently needs manual investigation/rollback. DNS moves
before ACME/services are ready, so a replacement can briefly interrupt traffic. This must
be improved before unattended replacement. A failed deployment does not destroy
the VM or stop billing. No expiry, automatic allocation or automatic retry is
introduced; the operator supervises running nodes and spend.

## Linux test, then publish

After successful **node-side** HTTPS/certificate verification, the role exports
two mode-0600 files. This self-check proves service readiness only; direct
regional connectivity is tested separately and must gate publication:

- `infra/cherry-vpn/private/cherry-test.json`: isolated mixed listeners, all bound
  to loopback: SSH `12340`, Naïve `12341`, VLESS `12342`. No TUN, system routing,
  Clash API or active-client configuration changes.
- `infra/cherry-vpn/private/cherry-outbounds.json`: three complete client outbounds
  for the profile publisher. Contains the **probe**, never administrator, private
  key. The server host key is read through the authenticated administrator
  connection and pinned in the SSH outbound; TLS verification stays enabled.

Start the isolated test client in another terminal (existing listeners cause a
bind failure, not replacement):

```sh
sing-box run -c infra/cherry-vpn/private/cherry-test.json
```

Test each local proxy; its returned egress IPv4 should match the Cherry node:

```sh
for port in 12340 12341 12342; do
  curl --disable --fail --silent --show-error --noproxy '' \
    --proxy "http://127.0.0.1:$port" --connect-timeout 10 --max-time 20 \
    https://api.ipify.org/
  printf '\n'
done
```

Repeat against independent HTTPS destinations, compare with nt1, and test from
the intended ISP. An active system TUN can still carry the underlying connections;
verify bypass routes before calling a result a direct-network test. Stop this
foreground client after testing. Successful website/certificate checks alone do
not prove authenticated proxy connectivity.

After successful isolated tests, publish alongside nt1, retaining existing URLs
and nt1 defaults:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/sing-box-configs/deploy.yaml \
  -e sing_box_extra_outbounds_file=infra/cherry-vpn/private/cherry-outbounds.json
sudo systemctl start sing-box-profile-update.service
```

Then explicitly select `cherry-ssh`, `cherry-naive` or `cherry-vless` in the
client's selector (the Linux Clash API is at `127.0.0.1:9091`). Updating a remote
profile does not automatically select the new node. Only use already-private
HTTPS enrollment URLs; they now grant the extra tunnel credentials as well.
Credentials are shared across enrolled devices, not individually revocable.

**Keep passing the exported file on later publishes** during this supervised
trial; a normal publish without it removes these extra nodes. Alternatively,
store the exported list in the shared profile Vault's `extra_outbounds` field and
publish without the flag. Do not do both (duplicate tags are rejected).
This explicit publisher input is not yet an automatically reconciled node list;
use a managed node catalogue before enabling unattended rotation. After replacing
a VM, rerun the role to export the new address and authenticated host key, then
republish. Remove the extra entries, republish and return clients to nt1 before
destroying a node.

## Local checks

```sh
python -m unittest discover -s roles/vpn_node/tests -p 'test_*.py'
python -m unittest discover -s infra/cherry-vpn -p 'test_*.py'
python -m unittest discover -s playbooks/vpn-probe -p 'test_*.py'
python -m unittest discover -s playbooks/sing-box-configs -p 'test_*.py'
ansible-lint roles/vpn_node infra/cherry-vpn/deploy.yaml playbooks/vpn-probe/deploy.yaml
```

Live Cherry deployment now verifies the pre-pinned identity, non-root sudo,
security-update policy, restricted SSH forwarding, both containers and Naïve's
real Let's Encrypt certificate. Lithuania failed all direct checks but passed
its SSH-forwarded reference; an approved destroy-first move to Amsterdam passed
**6/6 direct Linux checks** across all protocols and two HTTPS targets. A further
6/6 checks passed using the actual published Linux profile in an isolated core.
All three platform profiles now include Cherry alongside nt1, without URL/token
or default changes. The workstation's active local profile was deliberately not
enrolled/replaced and its update timer remains inactive. Other platform runtimes,
UDP, sustained performance and autonomous failover are not established by these
short TCP tests. See the Cherry guide's current status for the live node.
