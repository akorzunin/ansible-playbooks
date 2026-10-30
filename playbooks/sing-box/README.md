# Workstation sing-box proxy

Replaces V2RayA and its obsolete NT1 SSH tunnel with the pinned sing-box 1.14.4
container, following the migration in `../aurora-devops/playbooks/sing-box/`.
All proxy traffic uses **`aurora-vless`**, with no NT1 or direct fallback.
No TUN, host routing changes, panel, host networking or NET_ADMIN are needed.

## Credentials

The playbook selects exactly one direct VLESS outbound tagged `aurora-vless` from
`sing_box_secrets.extra_outbounds` in
`playbooks/sing-box-configs/secrets.vault.yaml`. UUID, server, TLS/Reality and flow
settings are reused unchanged. No credentials need copying into `external_vars.yml`.
To rotate them, edit that Vault and redeploy; republish the remote profiles separately
if those clients should receive the new credentials too.

## Deploy

From the repository root:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/sing-box/deploy.yaml
```

Only `remote_workstation` is targeted. `--check` is deliberately refused because
cutover requires live verification. The playbook:

1. Pulls the pinned image, stages a private config, runs `sing-box check` with
   that image and validates Compose **before** stopping anything.
2. Records the states of `v2raya`, `v2raya-ssh-socks` and `sing-box`, backs up
   changed active files, then stops any running legacy proxy/tunnel containers.
3. Starts sing-box, force-recreating it when configuration changes to remount
   atomically replaced bind-mounted files.
4. Requires a certificate-validated HTTPS request through `127.0.0.1:20171`
   to succeed. Override `sing_box_health_url` with a trusted 200/204 endpoint if
   necessary. On activation failure, removes the replacement, restores backed-up
   files and restarts only previously running containers (legacy tunnel first).

Deployment files and secret-bearing rollback copies live in the owner-only
`/srv/deploy/sing-box/` directory. The container runs without capabilities as
the deploying user's numeric UID/GID with a read-only filesystem.

## Existing clients

- HTTP/SOCKS mixed proxy: `127.0.0.1:20171` from the workstation.
- Existing app containers: **`http://host.docker.internal:20171`**, unchanged.
- Containers on `v2raya-proxy`: `http://sing-box:20171` or the compatibility alias
  `http://v2raya:20171`.
- Dedicated SOCKS listener: port `20170`, preserving the live workstation listener.

Unlike Aurora's loopback-only publish, both ports remain published on host
interfaces for existing Docker host-gateway, VM and LAN clients. These are
**unauthenticated proxies**: keep them restricted to trusted clients by the
host/router firewall; do not forward them from the Internet. Docker-published
ports may bypass ordinary host firewall rules. The old management port `2017`
is not exposed.

This deployment does not modify the controller's native sing-box service, TUN,
remote-profile subscription or the profile publisher. Published platform defaults
remain independent of this workstation's fixed `aurora-vless` outbound.

## Verify / rollback

On the workstation:

```sh
cd /srv/deploy/sing-box
docker compose -p workstation-sing-box ps
curl --noproxy '' -x http://127.0.0.1:20171 -I https://www.gstatic.com/generate_204
curl --noproxy '' --socks5-hostname 127.0.0.1:20170 -I https://www.gstatic.com/generate_204
```

The stopped legacy containers, `/srv/deploy/v2raya/` files and `/etc/v2raya/` data
are retained for rollback; the legacy NT1 route is still blocked. To restore the
old deployment, stop sing-box **first**, then start only the legacy containers
that were previously running:

```sh
cd /srv/deploy/sing-box
docker compose -p workstation-sing-box down
docker start v2raya-ssh-socks v2raya  # omit the tunnel if it was not present
```

Do not rerun the legacy playbook or start V2RayA alongside sing-box: their ports
conflict. For a later sing-box config rollback, restore the desired private
`config.json` backup and run `docker compose -p workstation-sing-box up -d --force-recreate`.

## Checks

```sh
python -m unittest discover -s playbooks/sing-box -p 'test_*.py' -v
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  playbooks/sing-box/deploy.yaml --syntax-check
SING_BOX_UID=$(id -u) SING_BOX_GID=$(id -g) \
  docker compose -f playbooks/sing-box/compose.yaml config -q
uvx prek run --all-files
```

Pinned-image config tests run when that image is cached locally, otherwise skip.
