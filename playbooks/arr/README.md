# Workstation ARR stack

Telegram → title matches → confirmation → Radarr/Sonarr → existing Transmission →
existing Jellyfin. Prowlarr manages indexers; Bazarr fetches subtitles.

## Telegram usage

- `/active` (or `/downloads`): list this chat's bot requests with ARR queue status
  and download progress. Requests without an active torrent are shown if files
  are still missing. Downloads added outside the bot are not listed.
- `/cancel NUMBER`: use the number from `/active`, then confirm cancellation.
  Unmonitors the movie or requested season and removes its Transmission torrents
  **without deleting files**. Other seasons' monitoring remains unchanged. A
  torrent shared across seasons in ARR's queue is refused; untracked torrent
  contents are not inspected. Manage mixed-season packs in ARR/Transmission.
  Already-running explicit searches may still finish; check ARR's queue afterwards.
  Cancellation affects the shared ARR item, including requests from other users
  for the same movie/season. Cancelled requests stop receiving import notifications.
  These commands require the updated standalone bot image; pulling an old image
  does not add them. To restart a cancelled movie with no file, search/select/confirm
  it again in the bot, or re-enable monitoring/search in Radarr. Existing movies
  with files or an active/pending ARR queue entry are left unchanged.
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
- No plot-description/LLM matching. The standalone Go bot notifies the requester
  after Radarr/Sonarr reports a completed import (not merely a torrent completion).

An empty/unset `TELEGRAM_ALLOWED_USERS` permits **any Telegram user** in private
chats to request downloads. Populate it with comma-separated numeric user IDs to
restrict access. Group chats are always ignored.

## Configured preferences

- **1080p:** HDTV, WEB and Blu-ray qualities from the built-in HD-1080p profile.
  No 720p or 4K. Upgrades within 1080p are enabled.
- **Original audio preferred:** +100 custom-format score when ARR identifies the
  original language. This is a preference, not a hard requirement; ARR's quality
  ordering takes precedence and metadata/release-name parsing is not infallible.
- **English subtitles:** Bazarr default profile, respecting embedded text subtitles
  but ignoring embedded PGS (image-based) tracks when checking for missing subtitles.
  This lets Bazarr fetch external text alternatives for Jellyfin clients that cannot
  display PGS directly; original video/subtitle tracks are not modified or OCR-converted.
  YIFY Subtitles and SuperSubtitles are enabled without extra accounts. Availability
  and matching are provider-dependent; subtitles are not guaranteed for every file.
- **Russian subtitles:** enabled for manual searches, not required by the default
  profile and not an automatic fallback replacing English.
- **Indexers:** Nyaa.si (English-translated anime category), 1337x, RuTracker.org,
  The Pirate Bay. Magnet URLs are preferred when available. Pirate Bay's Prowlarr
  definition uses its JSON API (normally `apibay.org`) to obtain infohashes/magnets;
  it does not need FlareSolverr. API availability can differ from the website.
  RuTracker credentials come from `RUTRACKER_USER` / `RUTRACKER_PASS` in external vars.
- **Minimum seeders: 5** on each managed Prowlarr indexer, propagated to
  Radarr/Sonarr by full application sync. This filters weak releases; it does not
  rank seeds above quality/custom-format preferences or fix torrents already
  grabbed. Advertised seed counts may be stale and are not connectivity guarantees.
  For a stuck download, use ARR's interactive search to compare seed counts and
  rejection reasons; remove/blocklist and retry there if a replacement is wanted.
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
**Films** and **Shows** libraries (real-time monitoring enabled). Legacy cartoon
shows and anime series have been consolidated into `complete/shows`; anime films
into `complete/films`. Transmission locations were updated to preserve seeding.
Jellyfin mounts `/storage` read-only; the empty legacy `/media` and `/media2`
mounts are no longer used. ARR and Bazarr retain write access through `/downloads`.
ARR configuration does not modify Jellyfin libraries. Optional streaming preparation
adds a separate optimized-media mount through the Jellyfin deployment; see below.

Staging directories are `/downloads/incoming/radarr` and
`/downloads/incoming/sonarr`. Transmission's ARR integration disallows setting
both Category and Directory, so each app uses a distinct Directory and no Category.
Completed Download Handling and hardlinks are enabled. Automatic torrent removal
is disabled, preserving seeding. Same-filesystem and UID/GID permissions are needed
for hardlinks. The existing Transmission configuration/routing is not modified.

Transmission is reached at `host.docker.internal:9092`. The inspected instance has
RPC authentication disabled; don't expose its RPC port to untrusted networks.
If you enable RPC authentication later, enter those credentials in both ARR apps.

Outbound ARR and Bazarr requests use the existing workstation HTTP proxy at
`host.docker.internal:20171`; internal service connections bypass it. ARR's own proxy
settings are also configured via API. Prowlarr passes its proxy to FlareSolverr.
The standalone bot has its own Compose proxy configuration. Cancellation uses
Transmission RPC at `http://host.docker.internal:9092/transmission/rpc` directly,
with session-ID negotiation. Its RPC URL is set via `TRANSMISSION_URL` in Compose.
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
# Start infrastructure; the bot stays off until configuration writes its API keys.
ansible-playbook playbooks/arr/deploy.yaml -i hosts -l remote_workstation \
  --vault-password-file=.ansible_pass -e arr_start=true

# Configure running apps, write bot.env, and start the Go bot.
ansible-playbook playbooks/arr/configure.yaml -i hosts -l remote_workstation \
  --vault-password-file=.ansible_pass
```

Without `-e arr_start=true`, the deployment playbook only prepares files/directories.
The bot is built and published to GHCR by its separate source repository, but runs
as a service in this ARR Compose stack. `configure.yaml` starts the bot after
writing its API keys and profile IDs to `bot.env`. Bot and worker images in
`compose.yaml` are pinned to the same CI-published commit (`:SHA` and `:worker-SHA`),
not moving tags. To update, wait for the bot repository's image workflow to succeed,
then replace both SHA tags in `compose.yaml`. Run `deploy.yaml` with
`-e arr_start=true -e arr_bot_enabled=true` (and `-e arr_prepare_enabled=true` when
using preparation) to copy the pins and start them. Rerunning `configure.yaml`
alone uses the already-deployed Compose file. The existing `config/bot/offset` is
retained; no second Telegram poller should run with the same token. Keep `bot.env` and `config/bot` across
upgrades. GHCR images from private repositories may require a target-host
`docker login ghcr.io` with read:packages access before deployment.

Deployment directory: `/srv/deploy/arr`.

- `.env` and `bot.env` are seeded once with mode 0600.
- Deployment updates `TELEGRAM_BOT_TOKEN` from external vars when defined. When
  preparation is enabled it also writes `ARR_JELLYFIN_API_KEY` into private
  `worker.env`, and manages `ARR_PREPARATION_DIR` in `.env`.
- Configuration discovers local ARR keys and writes them and quality-profile IDs
  to `bot.env`; no manual key copying is required. The user allowlist is preserved.
- RuTracker credentials are passed to configuration without Ansible logging and
  stored by Prowlarr. No separate tracker secret file is deployed.
- `TELEGRAM_ALLOWED_USERS` in `bot.env` controls general access; leave it empty to
  allow anyone to request downloads in a private chat. `TELEGRAM_CLEANUP_USERS`
  separately restricts permanent disk cleanup to specified numeric user IDs.
  It falls back to the general allowlist when unset; both empty disables deletion.
  `/list` shows ARR movies/seasons oldest import first and is read-only.
  `/cleanup TITLE` (optionally `S02` or `all`) deletes imported files, associated
  Transmission data and optimized copies after admin-bound confirmation.
  Both updated bot and worker images are required for optimized-copy cleanup.
  Mixed/unproven packs are refused. Entries remain unmonitored for safe retries.
- The configuration playbook manages named `ARR ...` profiles, Transmission clients,
  the four chosen indexers, their 5-seeder minimum, Prowlarr app links, and Bazarr defaults. Rerunning it
  reapplies these choices; edit the script if you want different managed defaults.
- Indexers are tested before saving; failed additions are reported in the summary.
  Read that summary even if Ansible succeeds, especially for Pirate Bay's API.
  Configuration never requests media. Existing torrents are not replaced.
- Use one Telegram polling process per token and remove any existing webhook first.

## Optional automatic streaming preparation

This is **implemented but not enabled by default**. Publish both updated images
from `../arr-telegram-bot/` first, matching the pinned `:SHA` bot and `:worker-SHA`
GPU worker tags in `compose.yaml`. Do not start a second Telegram poller. The worker has GPU access, not the Telegram polling process.

1. Confirm **the target workstation's Docker daemon** has the `nvidia` runtime:
   `docker info --format '{{json .Runtimes}}'`. The deployment refuses to enable
   preparation otherwise. NVIDIA Container Toolkit being installed is not enough;
   Docker must be configured to use it. If needed, an administrator can use
   `sudo nvidia-ctk runtime configure --runtime=docker`, followed by a **planned**
   Docker restart. Do not restart a daemon serving active streams blindly.
2. Create a Jellyfin administrator API key and set `ARR_JELLYFIN_API_KEY` in the
   ignored `external_vars.yml` (Vault is supported). Never commit that key.
3. Prepare ARR files/directories without starting services:

   ```sh
   ansible-playbook playbooks/arr/deploy.yaml -i hosts -l remote_workstation \
     --vault-password-file=.ansible_pass -e arr_prepare_enabled=true
   ```

4. Apply the new optimized-media mount to Jellyfin (recreates its container; plan
   around playback):

   ```sh
   ansible-playbook playbooks/jellyfin/deploy.yaml -i hosts -l remote_workstation \
     --vault-password-file=.ansible_pass
   ```

5. In Jellyfin, create **Streaming Films** (Movies, `/optimized/films`) and
   **Streaming Shows** (Shows, `/optimized/shows`). Enable real-time monitoring
   and grant the intended users access. Staging is under `/optimized/.staging`,
   outside these libraries. Original libraries and torrent data stay untouched.
6. Start/recreate the bot and worker after ARR credentials have already been
   configured:

   ```sh
   ansible-playbook playbooks/arr/deploy.yaml -i hosts -l remote_workstation \
     --vault-password-file=.ansible_pass -e arr_start=true \
     -e arr_bot_enabled=true -e arr_prepare_enabled=true
   ```

   For an initial ARR setup, use `configure.yaml -e arr_prepare_enabled=true`
   instead, after deploying infrastructure with the bot off and configuring the
   Jellyfin libraries. Use `arr_prepare_enabled=true` consistently on later
   deployment runs; omitting it disables discovery on the next bot recreation.

The bot inspects only its saved requests (including existing downloaded requested
files and later upgrades), not the entire library. Compatible SDR H.264 ≤1080p
with acceptable average/rolling bitrate is stream-copied; audio/container changes
avoid video encoding. Other SDR video uses NVENC at ~12 Mbps (14 Mbps maxrate, 14 Mbit VBV buffer).
Final outputs undergo full decode and bitrate validation before publication.
HDR is blocked pending a tested tone-mapping implementation. Optimized files keep
one default/first audio track, AAC mono/stereo; originals retain all tracks.
External SRT and embedded plain text are supported, not PGS burn-in or ASS styling.
Later Bazarr SRT additions/updates are mirrored. See the bot README for exact rules.

`/active` now includes compatibility checking, queued/preparing percentage,
validation, indexing, and failures. Fully ready requests are hidden. Ready messages
are sent only after Jellyfin indexes the optimized file; season-pack updates are
batched. Use `/retry NUMBER` or its button after fixing an error; indexing retries
reuse an already prepared video. Requesting an already-downloaded movie queues its
preparation without another search. Cancellation keeps both original data and
published streaming copies. Queue/results persist in `config/preparation`; back
this up together with `config/bot`. Back up `worker.env` securely too.

The worker exposes no ports and receives only the Jellyfin key. Input media is
read-only in both bot and worker. One worker/encode at a time is enforced by a local
filesystem lock; this design is for one workstation, not distributed workers.
Optimized copies use extra disk space, even for stream-copied compatible sources.
Metadata and requested titles are retained indefinitely; index/retention work is
needed before thousands of jobs, because supersession scans are quadratic.

Validate locally on the target without printing credentials:

```sh
cd /srv/deploy/arr
docker compose --profile bot --profile prepare config --quiet
docker compose --profile bot --profile prepare ps
```

Confirm a requested SDR title shows **Direct Play**, then test two real SyncPlay
clients. Synthetic/unit tests do not establish real internet throughput or client
subtitle compatibility. To disable preparation, deploy with `arr_start=true`,
`arr_bot_enabled=true`, and `arr_prepare_enabled=false`; the worker stops and the
bot returns to import notifications. Files and persistent jobs are retained.

### Apply the PGS subtitle fix

Rerun `playbooks/arr/configure.yaml` with the command above to apply the setting
on the running stack (this also reapplies the other managed ARR preferences).
For existing media, use Bazarr's **System → Tasks** to search for wanted subtitles
once missing-subtitle recalculation finishes. If an existing title still looks
complete, rescan its subtitles and verify it has the `ARR English` language profile;
default profiles do not retroactively assign a profile to existing titles.
In Jellyfin, refresh the title's metadata if necessary and select the external
text subtitle track rather than PGS. No media redownload is needed.

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
| Preparation (optional) | 1 NVIDIA GPU | 4 / 2G |

Memory reservations are soft targets, not preallocated RAM. CPU reservations are
Swarm scheduler hints, not guaranteed CPU shares under standalone Compose.
Bot and worker images are pinned to a CI-published commit. Third-party images
still follow `latest`; pin tested versions/digests before unattended upgrades.
Bazarr's in-app auto-update is disabled in favor of container image updates.

## Checks and limitations

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s playbooks/arr -p 'test_*.py'
```

Validate with `docker compose --profile bot config --quiet` without printing
resolved Compose configs from ws: they may contain secrets. Check
`docker compose --profile bot ps` on ws.
Third-party app logs can contain credentials, so inspect/redact them before sharing.
Check ARR before retrying after any timeout. Confirmed existing movie requests
re-enable monitoring and search only if the movie has no file and no active/pending
queue entry; its current profile and path are preserved. Series requests search only the selected season; previously enabled
seasons are not silently disabled. See the standalone bot source repository for
its checks and notification semantics.

Connection tests and metadata lookups do not test the full download/import path.
Confirm a real title through Telegram, then verify Transmission, ARR import,
Jellyfin visibility, and subtitle availability. No sample movie/series is downloaded
by the configuration playbook.

Back up `config/`, `.env`, `bot.env`, and `worker.env` securely. Stop only the bot with
`docker compose --profile bot stop bot`. `docker compose --profile bot down`
removes containers but leaves bind-mounted configuration and media intact.
