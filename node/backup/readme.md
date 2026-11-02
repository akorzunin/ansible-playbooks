# Service backups

Run from the repository root. `rclone`, GNU tar, Python 3 and Docker must already
be installed on the source host. An existing authenticated rclone remote is
required; the role **never creates, deletes or prints its configuration**.
Default: `backup-remote`, config `/home/<ansible_user>/.config/rclone/rclone.conf`.
Override `backup_remote_name` / `backup_rclone_config_path` if necessary.

## Create

Always select an explicit host with `--limit`:

```bash
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  node/backup/create.playbook.yaml --limit nt1 -e bs=dwman-test
```

For both nt1 dwman deployments and older on-host copies:

```bash
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  node/backup/create.playbook.yaml --limit nt1 \
  -e @node/backup/nt1-dwman.vars.yaml
```

For the remaining nt1 services, substitute `-e @node/backup/nt1-services.vars.yaml`.
This briefly interrupts nt1 proxies and monitoring as well. The dwman selection
is separate so it need not be stopped twice. See the [2026-10-30 receipt](nt1-2026-10-30.md)
for verified object paths and the pre-existing empty main database finding.

### Blocked nt1: use dyn1 as an SSH hop

**Historical only:** dyn1 was destroyed on 2026-11-01; this route no longer works.
Use a separately verified replacement hop before attempting another nt1 backup.
The existing cloud backups are unaffected.

Pass `--ssh-common-args` to the above commands. Both hosts must have pinned keys;
never disable checking or accept a replacement key to work around a failure.
The create playbook enables host-key checking despite the repository-wide default.
`DYN1_HOST` is dyn1's current address from the private inventory:

```bash
DYN1_HOST=<current-dyn1-address>
HOP_ARGS="-o StrictHostKeyChecking=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ProxyCommand=\"ssh -i $PWD/infra/cherry-vpn/private/ssh/admin -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$PWD/infra/cherry-vpn/private/known_hosts -o ConnectTimeout=10 -W %h:%p vpnadmin@$DYN1_HOST\""
ansible-playbook -i hosts --vault-password-file .ansible_pass \
  node/backup/create.playbook.yaml --limit nt1 \
  -e @node/backup/nt1-dwman.vars.yaml --ssh-common-args="$HOP_ARGS"
```

Cloud transfers originate on nt1, not the controller or hop. Cloud-only means no
archive is saved on the workstation; temporary root-only staging on nt1 is
necessary. Ensure enough free space in `/var/tmp` for an uncompressed-sized copy.
Run only one backup at a time; concurrent runs can interfere with container state.

### Coverage and guarantees

- `bs=all` selects **only `/srv/deploy`**, not the whole host. Override
  `backup_paths` with an explicit JSON/YAML list for other trees.
- Relevant containers are discovered from Compose working directories and mounts,
  including containers sharing selected storage. Omitted writable external
  bind/named volumes fail preflight instead of silently being lost.
- Read-only external config mounts, symlink targets, container writable layers,
  Docker images and non-Docker writers are **not** automatically backed up.
  Add config paths explicitly; quiesce non-Docker writers separately.
- Cloud access and source coverage are checked before downtime. Only previously
  running relevant containers are stopped. `always` restarts those same IDs after
  archiving, before upload; previously stopped containers stay stopped.
- A controller crash/disconnection can bypass Ansible recovery. If interrupted,
  inspect `/var/tmp/service-backup-*/metadata/containers.json` for `running_ids`
  and restart those IDs manually. Never start every stopped container blindly.
- Archives preserve numeric ownership, modes, ACLs, xattrs, deployment files and
  private container inspection metadata. Treat the entire archive as a secret.
  The existing remote's encryption/access controls apply; tar is not encrypted.
- gzip and all tar members are read locally; SHA256 accompanies the archive.
  `rclone check --download --one-way` reads cloud bytes back for comparison.
  This verifies archive transport, **not application-level recoverability**.
- `dwman` database sizes/JSON table counts are reported without exposing records.
  Empty or invalid databases are preserved with a warning, never silently repaired.
- No retention deletion or `sync` is used. Staging is removed only after verified
  upload; failures retain recovery files. Existing cloud backups remain untouched.

## Restore safely

**The old automatic in-place restore is disabled.** It copied live databases and
could leave services stopped on failure. New archives are `.tar.gz` with paths
relative to `/`; legacy ZIP archives have a different layout. Do not feed new
archives to the old rclone extraction procedure.

On a trusted recovery machine with the remote already configured:

```bash
umask 077
mkdir -p /private/recovery
cd /private/recovery
# Set REMOTE to the exact verified .tar.gz path printed by the backup playbook.
rclone copyto "$REMOTE" backup.tar.gz
rclone copyto "$REMOTE.sha256" backup.sha256
# Compare the digest; the sidecar's filename is the original archive basename.
expected=$(awk '{print $1}' backup.sha256)
printf '%s  backup.tar.gz\n' "$expected" | sha256sum --check -
gzip --test backup.tar.gz
tar --list --gzip --file backup.tar.gz
mkdir extracted
tar --extract --gzip --file backup.tar.gz --directory extracted --no-same-owner
```

Inspect `extracted/metadata/containers.json`, deployment config, and database
contents in isolation. Validate dwman JSON and test a separate application instance
before production cutover. Stop only the target application, preserve its current
tree, then restore the appropriate staged tree with original ownership/permissions
(as root with `--numeric-owner --acls --xattrs` when extracting for production).
Start only services intended to run. Never extract directly over `/`.

Legacy cloud ZIPs can be downloaded into a private recovery directory and inspected
with Python `zipfile` / `unzip`. Check their actual member names before extraction.
Missing data in today's database requires recovery from an older valid copy, not
repeatedly backing up or starting the broken application.

## Tests

```bash
python -m unittest discover -s roles/backup/tests -v
uvx prek run --all-files
```
