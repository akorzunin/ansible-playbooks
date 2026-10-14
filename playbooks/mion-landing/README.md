# Mion landing demo

Static frontend at <https://demo.akorz.duckdns.org>, served by Nginx in Docker
on `remote_workstation`. No backend, identity provider, or admin is deployed.
The existing workstation Caddy route to `192.168.1.132:8001` is unchanged.
The landing's **Начать** link redirects back to `/` because chat is not available.

## Deploy / update

Keep `mion.front` beside this repository and install its dependencies first
(`pnpm install --frozen-lockfile` in `mion.front`). From this repository:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass playbooks/mion-landing/deploy.yaml
```

The playbook builds the frontend locally, uploads only `dist`, builds the static
Docker image, and starts it in `/srv/deploy/mion-landing`. It removes the retired
`saulux-demo` container if present, without deleting its files or volumes.
All other workstation services and Caddy certificate state are untouched.

Check status on the workstation:

```sh
cd /srv/deploy/mion-landing
docker compose ps
docker compose logs --tail=50
```
