# Local QEMU/KVM restore

## Restore performed on 2026-07-16

Backup source:

```text
/mnt/gay_store/vm.res/2026-07-16/
```

Restore target:

```text
/mnt/gay_store/vm/gpn/
```

Important space note: do **not** restore this VM under `$HOME`. The home filesystem had ~98 GiB free, while the restored VM image uses ~95.5 GiB and needs working/output space. The playbook defaults restore output to `/mnt/gay_store/vm/gpn/`, where there was enough free space.

## Full restore command used

The backup was updated to include the libvirt config:

```text
/mnt/gay_store/vm.res/2026-07-16/vmconfig.copy.xml
/mnt/gay_store/vm.res/2026-07-16/vda.copy.data
/mnt/gay_store/vm.res/2026-07-16/vda.copy.qcow.json
/mnt/gay_store/vm.res/2026-07-16/vda.copy.data.chksum
```

The full VM restore was run only through the Ansible playbook:

```sh
ansible-playbook -i localhost, local/qemu-arch.playbook.yaml \
  -e restore_backup=true \
  -e restore_overwrite=true \
  -e restore_clear_target=true \
  -e verify_restored_image=true
```

What the playbook did:

1. Installed/verified QEMU/libvirt/virtnbdbackup tooling.
2. Refused restore into `$HOME`.
3. Cleared `/mnt/gay_store/vm/gpn/` because `restore_clear_target=true` was explicitly set.
4. Ran `virtnbdrestore` with adjusted config and libvirt define enabled.
5. Fixed qcow path to `/mnt/gay_store/vm/gpn/archlinux.qcow2`.
6. Removed the unsupported Astra/Parsec security label from the restored XML for Arch/libvirt compatibility.
7. Defined the sanitized VM config.
8. Verified the restored image with `qemu-img check`.

## Starting the VM

The restored backup contained this security label:

```xml
<seclabel type="dynamic" model="parsec" relabel="yes">
```

Arch libvirt does not provide the `parsec` security driver, so starting failed with:

```text
unsupported configuration: Security driver model 'parsec' is not available
```

The playbook now removes only the `parsec` seclabel from `/mnt/gay_store/vm/gpn/vmconfig.xml`, redefines the VM from the sanitized XML, and can start it with:

```sh
ansible-playbook -i localhost, local/qemu-arch.playbook.yaml -e start_restored_vm=true
```

## Spice display acceleration

Hardware acceleration is disabled by default in the playbook (`spice_gl_enabled: false`). The active VM uses plain Spice with `virtio-vga`:

```xml
<graphics type="spice">
  <listen type="none"/>
</graphics>
<video>
  <model type="virtio" heads="1" primary="yes" device="virtio-vga"/>
</video>
```

If GL is re-enabled, the explicit render node is important. This host has:

```text
Intel UHD 770:     /dev/dri/renderD128 (PCI 00:02.0)
NVIDIA RTX 4070:   /dev/dri/renderD129 (PCI 01:00.0)
```

To enable the tested VirGL configuration, use the Intel render node:

```sh
ansible-playbook -i localhost, local/qemu-arch.playbook.yaml \
  -e spice_gl_enabled=true \
  -e restart_restored_vm=true
```

This starts QEMU with `virtio-vga-gl` and `rendernode=/dev/dri/by-path/pci-0000:00:02.0-render`.

On this hybrid Intel/NVIDIA host, launch the local SPICE client on the same Intel/Mesa GPU. The unqualified `virt-viewer` command uses NVIDIA and imports the Intel dma-buf as a black screen:

```sh
env \
  __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json \
  __GLX_VENDOR_LIBRARY_NAME=mesa \
  DRI_PRIME=pci-0000_00_02_0 \
  virt-viewer -c qemu:///system gpn --attach
```

The guest Ly login is on tty1. If the viewer opens a text login instead, switch back with `Ctrl+Alt+F1`.

## Result

Restored files:

```text
/mnt/gay_store/vm/gpn/archlinux.qcow2
/mnt/gay_store/vm/gpn/vmconfig.xml
```

Defined libvirt VM:

```text
Name:  gpn
State: running
URI:   qemu:///system
```

Defined VM disk path:

```text
/mnt/gay_store/vm/gpn/archlinux.qcow2
```

Image verification:

```text
qemu-img check: No errors were found on the image.
```

Image info after full restore:

```text
file format: qcow2
virtual size: 120 GiB
actual file size: ~95.5 GiB
```

You can start it from `virt-manager` or with:

```sh
virsh -c qemu:///system start gpn
```

```sh
env __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json __GLX_VENDOR_LIBRARY_NAME=mesa DRI_PRIME=pci-0000_00_02_0 virt-viewer -c qemu:///system gpn --attach
```
