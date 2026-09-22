# Workstation ARR stack

Telegram → title matches → confirmation → Radarr/Sonarr → existing Transmission →
existing Jellyfin. Prowlarr manages indexers; Bazarr fetches subtitles.

## Telegram usage

- `/movie Spirited Away`: movie search.
- `/series Cowboy Bebop`: season **1**, not the whole series.
- `/series Example S02` or `Example season 2`: request season 2.
- Plain titles search both movies and series; series default to season 1.
- Choose a title/year match, then confirm. Invalid/missing seasons are rejected.
- Only the selected season is monitored for a newly added series. Future seasons
  are not automatically monitored. For an existing series, previously requested
  seasons are preserved; only the requested season is enabled and searched.
- Sonarr's season numbering is used, including for anime. Check unusual split
  seasons/cours against its metadata. Anime series type is detected from genres.
- No plot-description/LLM matching or download-progress notifications yet.

An empty/unset `TELEGRAM_ALLOWED_USERS` permits **any Telegram user** in private
chats to request downloads. Populate it with comma-separated numeric user IDs to
restrict access. Group chats are always ignored.

## Configured preferences

- **1080p:** HDTV, WEB and Blu-ray qualities from the built-in HD-1080p profile.
  No 720p or 4K. Upgrades within 1080p are enabled.
- **Original audio preferred:** +100 custom-format score when ARR identifies the
  original language. This is a preference, not a hard requirement; ARR's quality
  ordering takes precedence and metadata/release-name parsing is not infallible.
- **English subtitles:** Bazarr default profile, respecting embedded subtitles.
  YIFY Subtitles and SuperSubtitles are enabled without extra accounts. Availability
  and matching are provider-dependent; subtitles are not guaranteed for every file.
- **Russian subtitles:** enabled for manual searches, not required by the default
  profile and not an automatic fallback replacing English.
- **Indexers:** Nyaa.si (English-translated anime category), 1337x, RuTracker.org.
  RuTracker credentials come from `RUTRACKER_USER` / `RUTRACKER_PASS` in external vars.
- **FlareSolverr:** browser helper for Cloudflare checks on 1337x/RuTracker only.
  It has no published port. A passing test does not guarantee permanent access;
  site challenges and proxy exit-IP blocks can change.

## Existing storage and services

All media services use the same bind mount:

```text
Host:          /mnt/storage/jellyfin_media
ARR/Bazarr:    /downloads
Transmission: /downloads
Jellyfin:      /storage
```

Movies import to `/downloads/complete/films`; series to
`/downloads/complete/shows`. These match the workstation's existing Jellyfin
**Films** and **Shows** libraries (real-time monitoring enabled). Anime currently
uses these same roots rather than the separate legacy anime libraries.
No Jellyfin configuration is modified.

Staging directories are `/downloads/incoming/radarr` and
`/downloads/incoming/sonarr`. Transmission's ARR integration disallows setting
both Category and Directory, so each app uses a distinct Directory and no Category.
Completed Download Handling and hardlinks are enabled. Automatic torrent removal
is disabled, preserving seeding. Same-filesystem and UID/GID permissions are needed
for hardlinks. The existing Transmission configuration/routing is not modified.

Transmission is reached at `host.docker.internal:9092`. The inspected instance has
RPC authentication disabled; don't expose its RPC port to untrusted networks.
If you enable RPC authentication later, enter those credentials in both ARR apps.

Outbound ARR, bot, and Bazarr requests use the existing workstation HTTP proxy at
`host.docker.internal:20171`; internal service connections bypass it. ARR's own proxy
settings are also configured via API. Prowlarr passes its proxy to FlareSolverr.
This stack does not install or change the VPN/proxy or route Transmission through it.

## Deploy and configure

Requirements: Docker Engine/Compose v2, `findmnt`, Python 3 with PyYAML on ws,
mounted media disk, and media permissions matching the deployment user's UID/GID
(currently 1000:1000). Preparation refuses storage backed by `/` to avoid filling
the OS disk after a missing mount. No recursive media ownership changes are made.

Set these in the ignored `external_vars.yml` (Ansible Vault values supported):

```yaml
ARR_TELEGRAM_BOT_TOKEN: "..."
RUTRACKER_USER: "..."
RUTRACKER_PASS: "..."
```

Run from the repository root, selecting **one** workstation inventory alias:

```sh
# Start infrastructure; bot remains disabled for first-time setup.
ansible-playbook playbooks/arr/deploy.yaml -i hosts -l remote_workstation \
  --vault-password-file=.ansible_pass -e arr_start=true

# Configure running apps and start the bot.
ansible-playbook playbooks/arr/configure.yaml -i hosts -l remote_workstation \
  --vault-password-file=.ansible_pass
```

Without `-e arr_start=true`, the deployment playbook only prepares files/directories.
For subsequent bot-code updates, add `-e arr_bot_enabled=true` to deployment.
Omitting the bot profile does **not** stop an already running bot.

Deployment directory: `/srv/deploy/arr`.

- `.env` and `bot.env` are seeded once with mode 0600.
- Deployment updates only `TELEGRAM_BOT_TOKEN` from external vars when defined.
- Configuration discovers local ARR keys and writes them and quality-profile IDs
  to `bot.env`; no manual key copying is required. The user allowlist is preserved.
- RuTracker credentials are passed to configuration without Ansible logging and
  stored by Prowlarr. No separate tracker secret file is deployed.
- The configuration playbook manages named `ARR ...` profiles, Transmission clients,
  the three chosen indexers, Prowlarr app links, and Bazarr defaults. Rerunning it
  reapplies these choices; edit the script if you want different managed defaults.
- Indexers are tested before saving; failed additions are reported in the summary.
  Read that summary even if Ansible succeeds. Configuration never requests media.
- Use one Telegram polling process per token and remove any existing webhook first.

## Admin access

UIs bind to localhost; no Internet-facing ports are added. Use an SSH tunnel:

```sh
ssh -p 22123 -N \
  -L 7878:127.0.0.1:7878 -L 8989:127.0.0.1:8989 \
  -L 9696:127.0.0.1:9696 -L 6767:127.0.0.1:6767 \
  akorz@akorz.duckdns.org
```

Open localhost ports 7878 (Radarr), 8989 (Sonarr), 9696 (Prowlarr), 6767 (Bazarr).
Configure UI authentication before broadening access. `ARR_BIND_IP` in `.env` can
bind to a LAN address instead, but requires appropriate firewall restrictions.

## Resource budgets

| Service | Reserved CPU / memory | CPU / memory limit |
| --- | --- | --- |
| Radarr | 0.25 / 256M | 2 / 2G |
| Sonarr | 0.25 / 256M | 2 / 2G |
| Prowlarr | 0.10 / 128M | 1 / 1G |
| Bazarr | 0.10 / 128M | 1 / 1G |
| FlareSolverr | 0.10 / 256M | 2 / 1G |
| Bot | 0.05 / 32M | 0.5 / 256M |

Memory reservations are soft targets, not preallocated RAM. CPU reservations are
Swarm scheduler hints, not guaranteed CPU shares under standalone Compose.
Images follow `latest`; pin tested versions/digests before unattended upgrades.
Bazarr's in-app auto-update is disabled in favor of container image updates.

## Checks and limitations

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s playbooks/arr/bot -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s playbooks/arr -p 'test_configure.py'
```

Validate Compose from a temporary copy containing `bot.env.example` as `bot.env`:
`docker compose --profile bot config --quiet`. Don't print resolved Compose configs
from ws: they contain secrets.

On ws: `cd /srv/deploy/arr && docker compose --profile bot ps`.
Use `docker compose logs --tail=100 bot` for bot diagnostics; bot logs deliberately
omit token-bearing URLs and API response bodies. Third-party app logs can contain
credentials, so inspect/redact them before sharing.

The bot is one synchronous worker for private use, not a public request portal.
Selections expire after 15 minutes, after a new search by the same user, or on
restart. Poll offsets persist under `config/bot`; updates are checkpointed before
handling to prevent replay on restart. A crash can therefore lose a request.
Check ARR before retrying after any timeout. Existing movie requests do not trigger
another search. Series requests search only the selected season; previously enabled
seasons are not silently disabled.

Connection tests and metadata lookups do not test the full download/import path.
Confirm a real title through Telegram, then verify Transmission, ARR import,
Jellyfin visibility, and subtitle availability. No sample movie/series is downloaded
by the configuration playbook.

Back up `config/`, `.env`, and `bot.env` securely. To stop only the bot:
`docker compose --profile bot stop bot`. `docker compose --profile bot down` removes
containers but leaves bind-mounted configuration and media intact.
