# Local QEMU/KVM restore

This playbook installs/configures QEMU and libvirt and can restore the archived
Arch Linux VM.

## Portable storage paths

Paths are derived from one variable instead of a machine-specific mount:

```yaml
vm_storage_root: "{{ regular_home }}"
vm_backup_dir: "{{ vm_storage_root }}/vm.bak"
vm_restore_dir: "{{ vm_storage_root }}/vm"
```

The defaults on this machine resolve to:

```text
Backup: ~/vm.bak
VM:     ~/vm
Disk:   ~/vm/archlinux.qcow2
```

To use another disk, override only the root:

```sh
ansible-playbook -i localhost, local/qemu-arch.playbook.yaml \
  -e vm_storage_root=/path/on/large-disk
```

## Receive a QEMU backup over HTTP

Starts a temporary copyparty upload server on port `8000` in
`~/vm.bak/YYYY-MM-DD` and prints the exact source-machine backup/upload commands.
If port `8000` is already occupied, the playbook exits with an error:

```sh
ansible-playbook -i localhost, local/qemu-backup-upload.playbook.yaml
```

Override storage/VM when needed:

```sh
ansible-playbook -i localhost, local/qemu-backup-upload.playbook.yaml \
  -e vm_storage_root=/path/on/large-disk \
  -e source_vm_name=archlinux
```

No SSH is needed from the source machine; upload with a browser or `curl` to the
printed HTTP URL. Full automation is only possible if the source machine exposes
the backup through HTTP too; then this host can fetch it with `get_url`/`curl`.

## Restore today's uploaded backup

Restores from `~/vm.bak/YYYY-MM-DD` into `~/vm` and defines
`archlinux-restored` without starting it:

```sh
ansible-playbook -i localhost, local/qemu-backup-restore.playbook.yaml
```

The playbook refuses to overwrite a non-empty `~/vm`. To deliberately replace
an existing restore:

```sh
ansible-playbook -i localhost, local/qemu-backup-restore.playbook.yaml \
  -e restore_overwrite=true \
  -e restore_clear_target=true
```

## Configure QEMU/libvirt and define an existing restore

```sh
ansible-playbook -i localhost, local/qemu-arch.playbook.yaml
```

When `vm/vmconfig.xml` exists, the playbook sanitizes it, points it at the
portable disk path, and defines `archlinux-restored` in `qemu:///system`.
It does not start the VM by default.

## Restore the backup

Restore is deliberately opt-in. The backup and restored image each occupy
about 79 GiB, so check available space first. The target is not overwritten or
cleared unless both options are explicitly enabled.

```sh
ansible-playbook -i localhost, local/qemu-arch.playbook.yaml \
  -e restore_backup=true \
  -e restore_overwrite=true \
  -e restore_clear_target=true \
  -e verify_restored_image=true
```

The expected backup files are `vmconfig*.xml`, `*.data`, and the associated
virtnbdbackup metadata in `vm_backup_dir`.

## Start the VM

```sh
ansible-playbook -i localhost, local/qemu-arch.playbook.yaml \
  -e start_restored_vm=true
```

Or:

```sh
virsh -c qemu:///system start archlinux-restored
```

## Spice 3D acceleration

This host uses the AMD/Mesa render node because the default desktop GPU is
NVIDIA:

```text
/dev/dri/by-path/pci-0000:10:00.0-render
```

Disable GL for a portable software-rendered configuration with:

```sh
ansible-playbook -i localhost, local/qemu-arch.playbook.yaml \
  -e spice_gl_enabled=false
```

With GL enabled, launch the viewer through Mesa to avoid a black window:

```sh
env \
  __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json \
  MESA_VK_DEVICE_SELECT=1002:164e \
  DRI_PRIME=1 \
  virt-viewer -c qemu:///system archlinux-restored --attach
```

The guest login is on tty1; use `Ctrl+Alt+F1` if the viewer opens another TTY.
