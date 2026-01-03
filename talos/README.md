# Talos Linux – Extra Kernel Arguments

This document describes the kernel arguments used for this Talos cluster and their purpose. It is intended to live alongside the Talos configuration files (for example in `talos/config/README.md`) so the rationale for these settings is preserved.

---

## Configuration Snippet

Include the following under the appropriate Talos config section (for example `machine.install.extraKernelArgs` or `machine.kernel.extraArgs`, depending on your Talos version):

```yaml
extraKernelArgs:
  - -selinux
  - net.ifnames=0
  - amd_iommu=on
  - iommu=pt
  - amd_pstate=active
  - amd_pstate.shared_mem=1
  - lsm=landlock,lockdown,yama,apparmor,bpf
  - lsm.debug
  - spec_rstack_overflow=microcode
  - zfs.zfs_arc_shrinker_limit=0
  - zfs.zfs_arc_max=34359738368
```

---

## Argument Explanations

### `-selinux`

Disables SELinux at the kernel level.

### `net.ifnames=0`

Disables predictable network interface names and reverts to classic names like `eth0`. This can simplify networking configuration and troubleshooting.

### `amd_iommu=on`

Explicitly enables the AMD IOMMU. Required for PCI passthrough, VFIO, and certain virtualization or container workloads.

### `iommu=pt`

Sets IOMMU to passthrough mode for devices that do not require translation, improving performance while keeping IOMMU enabled.

### `amd_pstate=active`

Enables the AMD P-State CPU frequency scaling driver in active mode for improved power management and performance.

### `amd_pstate.shared_mem=1`

Forces the AMD P-State driver to use **shared memory (SMU mailbox) communication** instead of the default MSR-based interface. **Ryzen 9 5900X (Zen 3) CPUs do not expose the required CPPC MSR interface expected by `amd_pstate=active`**, so without this option the driver cannot attach and silently fails, leaving the system on legacy ACPI frequency scaling.

With `amd_pstate.shared_mem=1`, the driver uses the SMU-provided shared memory path, which *is* supported on Zen 3, allowing `amd_pstate` to initialize correctly and expose modern CPU frequency control. This is therefore a **functional requirement**, not a tuning option, for this hardware.

### `lsm=landlock,lockdown,yama,apparmor,bpf`

Explicitly defines the Linux Security Modules (LSMs) stack and ordering. This ensures AppArmor and other security modules are enabled and predictable.

### `lsm.debug`

Enables debugging output for LSM initialization, useful for verifying that the expected security modules are active.

### `spec_rstack_overflow=microcode`

Mitigates speculative return stack overflow vulnerabilities using CPU microcode support where available.

### `zfs.zfs_arc_shrinker_limit=0`

Removes the ZFS ARC shrinker limit, allowing the kernel more flexibility when reclaiming memory from ARC under pressure.

### `zfs.zfs_arc_max=34359738368`

Caps the ZFS ARC size to **32 GiB** (34,359,738,368 bytes) to prevent ZFS from consuming excessive system memory.

---

## Notes

* **Secure Boot**: This cluster uses Secure Boot with *pre-signed kernel components*. Kernel arguments are applied as part of the Talos boot assets and do **not** rely on modifying unsigned kernel command lines at runtime.
* These settings are tuned for AMD-based systems running ZFS and may not be appropriate for all hardware.
* Review and adjust values (especially ZFS ARC limits) based on available system RAM and workload requirements.
