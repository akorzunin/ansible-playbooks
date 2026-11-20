# Workstation NVIDIA cgroup access

Jellyfin and ARR preparation use the GTX 1070 through the legacy NVIDIA runtime.
A runtime hook injects devices without recording them in Docker's configuration.
A systemd reload or resource-limit update can then remove GPU cgroup permissions:
`CUDA_ERROR_NO_DEVICE`, despite a healthy host GPU and visible `/dev/nvidia*` nodes.

## Preventive fix

1. Both Compose services explicitly map the GPU and control/UVM device nodes, so
   Docker retains their permissions when updating cgroups.
2. `deploy.yaml` creates `/dev/char/<major>:<minor>` links for the older `runc` on
   this host. A boot service loads the NVIDIA/UVM modules and scans existing nodes
   after udev settles, before Docker starts. A udev rule also handles driver adds.
   Major numbers are discovered, never hardcoded (the UVM major can change).

The installed toolkit 1.13.5's `--create-all` expects the old `nvidia-frontend`
name in `/proc/devices`; driver 560 reports `nvidia`, so that option fails. The
existing-node scan works. This workaround is deliberately for the single-GPU
workstation: use a current toolkit and CDI when migrating to multi-GPU/MIG or
replacing this legacy stack. This does not fix driver resets or hardware faults.

No privileged containers, disabled cgroups, restart timers, Docker daemon restart,
or driver/package upgrades are needed. Existing containers must be recreated once
so Docker records the explicit device permissions. Other GPU services are not
migrated by this change.

Sources: [NVIDIA troubleshooting](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html#mitigations-and-workarounds),
[NVIDIA device-link workaround](https://github.com/NVIDIA/nvidia-container-toolkit/issues/48).

## Apply

Run the host playbook first (sudo required; no Docker restart):

```sh
ansible-playbook -i hosts -l remote_workstation \
  --vault-password-file=.ansible_pass playbooks/nvidia-runtime/deploy.yaml
```

Copy the updated `playbooks/jellyfin/compose.yaml` and `playbooks/arr/compose.yaml`
to their existing `/srv/deploy/{jellyfin,arr}/compose.yaml` paths. Back up the old
files and check for local overrides first. Validate without printing resolved
secrets, then recreate only the affected services during a playback maintenance
window. Do not pull newer images as part of this repair:

```sh
cd /srv/deploy/jellyfin
docker compose config --quiet
docker compose up -d --no-deps --pull never --force-recreate jellyfin
cd /srv/deploy/arr
docker compose --profile prepare config --quiet
docker compose --profile prepare up -d --no-deps --pull never --force-recreate prepare
```

Normal future Jellyfin/ARR deployments retain the device mappings; provision the
host playbook on replacement workstations too. Keep the host service/rule installed
alongside these Compose files. `/dev/char` is temporary and must be rebuilt at boot.

## Validate

Local static checks:

```sh
python -m unittest discover -s playbooks/nvidia-runtime -p 'test_*.py'
uvx prek run --all-files
```

Run `bash test-gpu-access.sh` on the workstation after copying the script there.
**This deliberately performs a host-wide `systemctl daemon-reload`.** Schedule it
around any other, unprotected GPU services. It creates disposable containers from
the exact running Jellyfin/worker image IDs, with explicit device mappings, a
non-root user, read-only rootfs, no capabilities and no network or media mounts.
NVENC must pass initially, after a resource-limit update, and after daemon-reload.
It also checks NVENC in both live services after the reload and cleans up its
containers on exit. No live container resource limits are changed.

Then check a short encode of the actual source and Chrome playback. Send `/retry
13` to the bot to requeue failed preparation; container recreation does not erase
or automatically retry failed jobs. Verify boot persistence after the next planned
reboot with `systemctl status nvidia-dev-char.service` and the regression script;
this repair does not reboot the workstation.

## Rollback

Restore the backed-up Compose files and recreate only the same two services.
That restores the previous configuration **and its permission-loss risk**. The
host device links are safe to leave installed. To remove them from management,
disable `nvidia-dev-char.service`, remove its unit and
`/etc/udev/rules.d/71-nvidia-dev-char.rules`, then reload systemd/udev rules. No
need to delete live `/dev/char` links or restart Docker.
