# dwman-test on ge2

GitHub Actions in `akorzunin/dwman` owns application deployment. This repository
only prepares `/srv/deploy/dwman-test` and Caddy with persistent certificate storage.
The application remains bound to loopback port **8088**, behind
**https://test-dwman.akorz-ge2.duckdns.org**. Permit inbound TCP 80/443 (and optionally UDP
443 for HTTP/3) in the provider firewall. SSH and Docker come from node bootstrap.
DNS is already configured; this playbook does not update DuckDNS.

```sh
ansible-playbook -i ./hosts --vault-password-file=.ansible_pass \
  node/ge2/prepare-dwman-test.yaml
```

## GitHub Actions handoff

Only the `test` environment is changed; `main` and repository-level secrets are
untouched:

| Test environment setting | Value |
| --- | --- |
| `SERVER_GROUP` | `ge2` |
| `DEPLOY_URL` | `https://test-dwman.akorz-ge2.duckdns.org` |
| `PORT` | `8088` (unchanged) |
| `ANSIBLE_HOSTS` secret | YAML inventory containing **only ge2**, with its Vault-backed key and Python 3 interpreter |
| `ANSIBLE_PASS` secret | Vault password for that inventory |
| `SSH_KNOWN_HOSTS` secret | Pinned ge2 Ed25519 host key |

Existing application secrets are reused. The `test` branch workflow now installs
Ansible 12 / Core 2.19 using Python 3.12, enables its managed SSH agent, and passes the optional
`SSH_KNOWN_HOSTS` secret to the deployment action. Keep these workflow changes
when merging branches. Never upload this repository's full multi-host inventory.
The scoped inventory still grants ge2 administrator/Docker access; it is not a
restricted application-only account.

Allow **`https://test-dwman.akorz-ge2.duckdns.org/get_token`** in the Spotify application's
redirect URI settings. Setting `DEPLOY_URL` updates the application's callback,
but does not change Spotify's allowlist. Existing `IGNORE_CORS=1` is unchanged.

## Data migration (2026-11-01)

Stopped only `dwman-test` on nt1, archived its complete `data/` directory, and
restored it to ge2 before deploying through Actions. The valid 553-byte `db.json`
matched this SHA256 on both sides before application startup:

```text
7217ef13bcef2709dc486f401ad2c8a53d970b876c76cfad1e55261b8e3e8658
```

The old nt1 test container remains stopped; its original data is retained.
Do not run both test instances: they share the Telegram bot credentials.
No main deployment or database was migrated. The migration snapshot is retained
locally as the ignored, Vault-encrypted
`.ansible/dwman-test-migration/data.tar.vault`; the temporary source archive was removed.

[Actions run 41299872023](https://github.com/akorzunin/dwman/actions/runs/41299872023)
succeeded for the initial root-hostname deployment. The new container is healthy, HTTPS `/health` returns 200, and the
post-startup database checksum still matches. Public Google DNS resolves the
hostname correctly; this controller's local resolver failed, so the external TLS
check used `curl --resolve akorz-ge2.duckdns.org:443:94.249.187.177` (without `-k`).

## Test subdomain (2026-11-01)

Switched Caddy and the test environment's `DEPLOY_URL` to
`https://test-dwman.akorz-ge2.duckdns.org`.
[Actions run 41300958244](https://github.com/akorzunin/dwman/actions/runs/41300958244)
succeeded. Verified the container is healthy, HTTPS `/health` returns 200, and
its `SPOTIPY_REDIRECT_URL` exactly matches the registered
`https://test-dwman.akorz-ge2.duckdns.org/get_token` callback. No main hostname
or deployment was configured by this change.

Verify after an Actions deployment:

```sh
curl --fail https://test-dwman.akorz-ge2.duckdns.org/health
ansible ge2 -i ./hosts --vault-password-file=.ansible_pass \
  -m ansible.builtin.command -a 'docker inspect --format "{% raw %}{{.State.Health.Status}}{% endraw %}" dwman-test'
```

## Notification settings after a fresh Spotify login

The migration preserved `send_mail`, `send_time`, and `tg_chat_id`; the source,
encrypted snapshot, and destination databases matched exactly. A fresh Spotify
login issued a new refresh token, but the application still authenticated against
the old stored hash. `/api/user` returned 401, followed by a failed duplicate
`/api/new_user` request, leaving the settings form empty.

The test-branch fix in
[`db8c4a8`](https://github.com/akorzunin/dwman/commit/db8c4a8)
updates the existing user's token and authentication hash after the validated
Spotify OAuth callback, without changing notification settings or other profile
fields. Regression tests cover both callback modes and reject the old token.
[Actions run 41301949745](https://github.com/akorzunin/dwman/actions/runs/41301949745)
succeeded; image `sha-db8c4a8` is healthy and HTTPS `/health` returns 200.
Log out and sign in with Spotify again; no database restore or manual re-entry
of notification settings is needed.

## Rollback

Stop `dwman-test` on ge2 first. Restore test variables to `SERVER_GROUP=nt1` and
`DEPLOY_URL=https://test-dwman.akorz-nt1.duckdns.org`; delete the environment-level
`ANSIBLE_HOSTS`, `ANSIBLE_PASS`, and `SSH_KNOWN_HOSTS` overrides to reuse the
previous repository-level credentials. Then start the existing nt1 test container
through the documented [SSH hop](../backup/readme.md#blocked-nt1-use-dyn1-as-an-ssh-hop).
This returns to nt1's pre-migration database; reconcile any writes made on ge2
before doing so. Caddy on ge2 can remain running, but will return 502 while the
backend is stopped.
