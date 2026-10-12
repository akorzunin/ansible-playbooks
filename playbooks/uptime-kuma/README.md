# Uptime Kuma

Pinned to stable `2.5.6` by tag and SHA-256 digest, exposed on port `3033`. Data remains in
`~/deploy/uptime-kuma/data` on the deployment host.

## Declarative configuration

The workstation's configuration was exported read-only on 2026-10-12:

- `config.yml`: HTTP monitors, named notification assignments, Telegram options,
  and general settings (including timezone and 180-day retention).
- Credentials reuse `AUTH_PASS`, `MONITORING_TELEGRAM_BOT_TOKEN`, and
  `MONITORING_TELEGRAM_CHAT_ID` from the ignored `external_vars.yml`.
  No separate secret file is committed.
- `configure.yaml` / `configure.cjs`: reconcile through the pinned version's
  internal Socket.IO API using its bundled client, with no extra dependencies.

The existing `admin` account uses `AUTH_PASS`. On a fresh installation this
password creates the account automatically; SQLite is selected by Compose, so
neither database setup nor monitor/notification setup requires the web UI.
Account passwords are not reset on existing installations.

After upgrading Kuma to `2.5.6` and allowing migrations to finish, preview and
apply (select **one** inventory alias for the workstation):

```sh
ansible-playbook playbooks/uptime-kuma/configure.yaml -i hosts \
  -l remote_workstation --vault-password-file .ansible_pass --check
ansible-playbook playbooks/uptime-kuma/configure.yaml -i hosts \
  -l remote_workstation --vault-password-file .ansible_pass
```

Configuration is deliberately separate from deployment: `deploy.yaml` alone
keeps existing data/configuration, and does not call the configuration API.

Reconciliation matches exact names, resolves notification IDs dynamically, and
updates in place to retain monitor history. Repeating it with no changes does
not save/restart monitors. It preserves settings/fields not listed in the
manifest and does **not** delete unlisted objects. Renaming creates another
object; deletion/renaming cleanup remains explicit. Duplicate names are refused.
Avoid simultaneous configuration runs or UI edits during reconciliation; there
is no cross-run lock.

Only ungrouped HTTP monitors without monitor proxies and Telegram notifications
are currently supported, matching the exported state. Tags, status pages and
maintenance are not managed (none existed on the workstation). Runtime history,
password hashes and JWT signing keys are not exported. The internal API is pinned
to `2.5.6`; review/test it when changing image versions. The captured account has
2FA disabled; enabling 2FA would require extending automated login.

`--check` logs in and reads state but makes no configuration writes, sends no test
notification and does not initialize a fresh account. Normal application does
not send a test notification either, though new/restarted monitors may generate
normal alerts. Verify Telegram delivery using its UI **Test** after the upgrade.

Tests:

```sh
node --test playbooks/uptime-kuma/test_configure.cjs
```

## Telegram proxy

`NOTIFICATION_PROXY=http://host.docker.internal:20171` routes Telegram and other
notification providers that support this variable through the existing host HTTP
proxy. It does not change monitor proxy settings. No global `HTTP_PROXY` or
`HTTPS_PROXY` is set.

The proxy must be running on the **Kuma host**, reachable from Docker containers
on port `20171`, and able to reach `api.telegram.org`. A listener bound only to
`127.0.0.1` is not reachable through `host.docker.internal`; allow the Docker
bridge, but do not expose an unauthenticated proxy to the Internet.

Keep the Telegram notification's API server URL as `https://api.telegram.org`.
That field is an API endpoint, not a forward-proxy setting. Reconciliation uses
`MONITORING_TELEGRAM_BOT_TOKEN` and `MONITORING_TELEGRAM_CHAT_ID` and retains the
exported monitor notification assignments.

## Upgrade

Before upgrading from `2.0.0-beta.1`, take a cold backup on the deployment host:

```sh
cd ~/deploy/uptime-kuma
docker compose stop uptime-kuma
tar -czf "uptime-kuma-data-$(date +%Y%m%d-%H%M%S).tar.gz" data
```

Only proceed if the backup succeeds. From this repository, deploy to the selected
inventory host:

```sh
ansible-playbook playbooks/uptime-kuma/deploy.yaml -i hosts -l <host> \
  --vault-password-file .ansible_pass
```

On the deployment host, watch startup/migration logs:

```sh
cd ~/deploy/uptime-kuma
docker compose logs -f uptime-kuma
```

Do not interrupt database migrations. In Kuma, edit the existing Telegram
notification and click **Test**; confirm the message arrives. Also check that
existing monitors still work. Browser-side Telegram chat-ID auto-detection is
not routed through the container's notification proxy; retain the existing ID.

If rollback is necessary, stop Kuma, restore the cold backup, and revert the
image tag together. Do not run the old beta against an upgraded database.
