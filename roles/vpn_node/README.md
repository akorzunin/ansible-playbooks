# VPN node

Reusable Docker VPN services for an existing, bootstrapped Debian x86_64 node.
Static servers such as ge2 and disposable servers such as dyn1 use the same role;
cloud provisioning and administrator bootstrap remain separate. The role does
not change administrator SSH, host routing, active clients or monitoring.

| Service | Dedicated node | ge2 / shared HTTPS |
| --- | --- | --- |
| Forwarding-only OpenSSH | TCP 2222 | TCP 2222 |
| Naïve HTTP/2 CONNECT | TCP 443, HTTP/ACME 80 | TCP 443 through Caddy SNI passthrough |
| VLESS/REALITY + Vision | TCP 8443 | TCP 8443 |
| Hysteria 2 / Brutal | UDP 443 | UDP 8443 (Caddy retains HTTP/3 on UDP 443) |

All four services run in separate unprivileged, capability-dropped containers
with read-only roots and memory/PID/log limits. SSH is TCP-only and cannot open
shells, commands, PTYs, remote forwards or agent/Unix-socket forwards. Its host key
is separate from administrator SSH and is pinned through the authenticated admin
connection, never by trusting a network scan. Private keys persist on the node.

Naïve is TCP-only. VLESS relays UDP with XUDP, including through its Naïve carrier.
Hysteria uses native outer QUIC/UDP. Protocol availability varies by network; a
short successful check does not establish sustained reliability or DPI resistance.

## Deploy and publish

Create persistent **per-node** credentials once. Existing files are refused:

```sh
python playbooks/vpn-node/prepare-secrets.py --node ge2
```

This creates `node/ge2/vpn.vault.yaml`, containing proxy credentials and a dedicated
unprivileged SSH tunnel key. Keep the encrypted file with shared deployment inputs
and transfer the Vault password separately. Do not regenerate credentials on rerun
or reuse administrator keys for clients. The SSH container's host identity and
Naïve's certificate/ACME state also need secure node backups.

Add the node to private `hosts` with independently verified SSH host-key checking,
a non-root administrator, sudo access and Python. Configure
`node/<inventory-alias>/vpn.yaml`; ge2's tracked file is the example. Then run:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/vpn-node/deploy.yaml -e vpn_target=ge2
```

Select one explicit target; do not use `--limit`. The playbook:

1. Loads node settings and encrypted credentials, restoring controller tunnel keys
   under ignored `playbooks/vpn-node/private/<node>/`.
2. Runs `vpn_node`, validates server configurations before activation, and exports
   private `<node>-outbounds.json` / `<node>-test.json` files.
3. Checks SSH, Naïve, VLESS, Hysteria and VLESS-over-Naïve using isolated loopback
   clients, two HTTPS destinations and the expected node egress IP. Any failure
   stops registration/publication; already-published profiles remain intact.
4. Idempotently replaces only this node's entries in the encrypted profile Vault,
   preserving other nodes and existing enrollment tokens. The configured
   `vpn_node_default_outbound` must name a selectable node choice.
5. Publishes through the existing `sing-box-configs` workflow. Generation derives
   `<node>-vless-via-naive` and `<node>-ssh-via-workstation`; the restricted
   workstation SSH allowlist is updated before publication.
6. Checks every generated node choice, including the workstation SSH hop.

A failure in the final checks is reported after publication; it does not
transactionally roll back already-refreshed remote clients. Enrolled clients must
refresh/reconnect to receive changes. No local client is enrolled or switched.
There is no automatic failover or allocation.

## Node settings

- `vpn_node_domain`: an owned hostname for Naïve/Hysteria certificate verification.
  REALITY SNI defaults to this same owned hostname, not a third-party website; its
  handshake target defaults to the node's public IPv4 on TCP 443.
- `vpn_node_manage_dns`: defaults to true for a dedicated, single-label DuckDNS
  node; load `DUCKDNS_TOKEN` from `external_vars.yml`. This mode retains the original
  IPv4-only DNS guard. Set false for existing externally managed DNS, as on ge2;
  ge2's application A/AAAA records remain unchanged.
- `vpn_node_shared_https`: defaults to false. With true, set
  `vpn_node_caddyfile` to the existing **site-only** Caddy configuration. The role
  validates a combined SNI router, preserving those sites, existing Caddy volumes
  and application containers. Naïve binds only loopback TCP 8089/8444.
- `vpn_node_ssh_port`: defaults to 2222; must differ from administrator SSH.
- `vpn_node_hysteria2_port`: defaults to 443; ge2 uses 8443 to preserve HTTP/3.
- `vpn_node_hysteria2_download_mbps` / `vpn_node_hysteria2_upload_mbps`: initial
  Brutal targets 20/5 Mbps, not measured capacity.

Shared HTTPS uses the repository's version-pinned Caddy/layer4 build. It builds
on the controller (Docker required there), not on a 1 GiB application node, then
transfers the image. A Compose override keeps that image selected on normal
reruns. ge2's application-preparation playbook leaves VPN-managed routing intact;
rerun this VPN deployment to incorporate changes to its site-only source.

For a dynamic node, first provision and verify its administrator identity, then
use the same playbook with its inventory alias and settings. Override
`vpn_node_config_file` and `vpn_node_secrets_file` for infrastructure-specific
locations. No cloud API/token/state is required by this role or playbook. The
legacy Cherry entry point remains for its separate provisioning/bootstrap flow.

## Isolated checks and maintenance

```sh
python roles/vpn_node/files/check.py \
  --input playbooks/sing-box-configs/private/linux.json \
  --node ge2 --expected-ip 94.249.187.177 --udp
```

`--udp` additionally checks VLESS/Hysteria relay against two STUN servers. SSH and
Naïve are deliberately not tested as UDP-capable. Cores use temporary private
configuration and OS-assigned loopback ports; no TUN, system proxy or routing
changes are made. An existing host TUN can still carry the underlying connection;
verify the physical route before describing results as direct-ISP tests.

Pinned Naïve/sing-box versions are unchanged from the Cherry trial. The SSH image
uses Debian 13's OpenSSH packages; rebuilding it is needed for package updates.
Reruns preserve credentials, SSH host keys and certificate state. Activation has
syntax checks, not transactional rollback; supervise changes and retain backups.
Remove a node's Vault outbounds, change the default and republish **before**
destroying it. Infrastructure deletion does not automatically reconcile profiles.
