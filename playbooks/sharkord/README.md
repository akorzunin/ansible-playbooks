# Sharkord on workstation

A single Sharkord v0.0.29 container (alpha), pinned by image digest, with SQLite,
voice, video and screen sharing. No MongoDB or separate media service.

## Deploy

From the repository root:

```sh
ansible-playbook -i hosts --vault-password-file .ansible_pass playbooks/sharkord/deploy.yaml
```

Targets **only `remote_workstation`**. Check mode is deliberately refused because
startup and health verification need a running service. The playbook validates
Compose, waits for container health, and checks the public HTTPS endpoint with
certificate verification. Docker and Compose must already be installed.

- Deployment and data: `/srv/deploy/sharkord/`, with persistent state in `data/`.
- URL: <https://chat.akorz.duckdns.org>.
- Existing Caddy route: `192.168.1.132:3333`, mapped to container HTTP port 4991.
  No DNS or Caddy changes are needed. Do not forward port 3333 from the router.
- WebRTC: TCP **and** UDP 40000 on the workstation, forwarded to the same
  container port. No host firewall changes are made.

### Router forwarding required for remote voice/video

On the Keenetic router, add these rules without changing existing HTTPS/SSH rules:

| Protocol | WAN port | LAN destination | LAN port |
| --- | --- | --- | --- |
| UDP | 40000 | 192.168.1.132 | 40000 |
| TCP | 40000 | 192.168.1.132 | 40000 |

See [the Caddy README](../pi-caddy/README.md) for the private router-management
SSH tunnel. This playbook does **not** alter the router. A working web page does
not prove WebRTC works; test a call between two clients on different networks.
LAN clients may need router NAT loopback to reach the advertised WAN address.

The advertised media IPv4 is resolved from `chat.akorz.duckdns.org` at deployment
and saved in `.env`. **Rerun the playbook after a WAN IPv4/DuckDNS change** to
recreate the container with the new ICE address. This is deployment-time resolution,
not continuous dynamic-DNS tracking. IPv6-only clients/TURN relaying are not set up.

## Claim ownership

Sharkord prints its first-start owner token once. The playbook preserves those
logs in `/srv/deploy/sharkord/bootstrap.log`, mode 0600, inside a mode-0700 directory.
Never commit or share this file: the token can grant ownership of the server.

Read it privately on your own terminal:

```sh
ssh -p 22123 akorz@akorz.duckdns.org 'less -R /srv/deploy/sharkord/bootstrap.log'
```

Open the HTTPS site and create your account. Open the browser developer console
(`Ctrl+Shift+I`, Console) and run `useToken("your_token_here")` with the token from
the private log, as described in [Sharkord's owner guide](https://sharkord.com/docs/introduction/owner-permissions).
The token is reusable and cannot be revoked or rotated in this release.
Set a server password or disable open registration and use invites before sharing
the URL. Upstream defaults permit new registrations; deployment does not create an
account or change that setting. Store the token in a password manager; Docker logs
also contain it until they rotate.

For audio, compare browser suppression, RNNoise and DTLN in the client settings.
The latter two are experimental and run on each participant's device.

## Deployment verification

Deployed on 2026-11-05. Container health, HTTPS certificate, web UI, `/info`, and
the RNNoise worklet asset passed checks. A second deployment made no changes.
Idle memory was about 111 MiB (not a loaded-call benchmark). After the owner added
router rules, public TCP 40000 connected and a uniquely marked UDP probe to the
public hostname reached workstation port 40000 (confirmed by packet capture).
A real two-client voice/video call remains to be verified. No other containers or
Caddy configuration were changed.

## Operations

On the workstation:

```sh
cd /srv/deploy/sharkord
docker compose ps
docker stats --no-stream sharkord
```

Back up the **whole `data/` directory while the container is stopped** for a
consistent SQLite snapshot, then start it again. Keep the archive private. Back up
before upgrades: alpha releases can change the database and may require restoring
the snapshot to roll back. Updates are manual; change the pinned tag/digest here
and redeploy. Bootstrap logs and `.env` should also be kept privately.

To stop the trial without deleting data: `docker compose stop`. The existing Caddy
route will return 502 while stopped. No other services or old chat data are removed.

## Offline checks

```sh
python -m unittest discover -s playbooks/sharkord -p 'test_*.py'
uvx prek run --all-files
```
