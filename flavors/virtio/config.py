#!/usr/bin/env python3

import os
import sys

FLAVOR = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from genconfig import (
    enable_by_prefix,
    enable_exact,
    enable_umbrella,
    finish,
    load_slices,
    start,
)

kconf = start()

enable_exact(("STAGING", 2))

#
# Enable all RAID and LVM device drivers as modules
#
enable_umbrella("MD", 2, label="MD")

#
# Enable all SCSI/RAID/SAS/FC HBA drivers as modules
#
scsi = kconf.syms["SCSI"]
if scsi.tri_value == 0:          # SCSI_LOWLEVEL requires "SCSI!=n"
    scsi.set_value(2)            # y

enable_umbrella("SCSI_LOWLEVEL", 2, label="SCSI_LOWLEVEL")  # a gate, not a driver itself

if "EXPERT" in kconf.syms:
    kconf.syms["EXPERT"].set_value(2)  # y

if "MAXSMP" in kconf.syms:
    kconf.syms["MAXSMP"].set_value(2)  # y

# Kernel compression method: a `choice` block, single-select.
if "KERNEL_ZSTD" in kconf.syms:
    kconf.syms["KERNEL_ZSTD"].set_value(2)  # y

if "PREEMPT" in kconf.syms:
    kconf.syms["PREEMPT"].set_value(2)  # y

enable_umbrella("INET_DIAG", 1, label="INET_DIAG")

# --- IP6_NF_NAT: the real prerequisite for IP6_NF_TARGET_MASQUERADE,
# never touched despite IP6_NF_IPTABLES itself being on.
# IP6_NF_IPTABLES (legacy ip6tables) was never enabled at all -- we only
# ever did IP_NF_IPTABLES (IPv4). This is the real prerequisite for
# IP6_NF_NAT / IP6_NF_TARGET_MASQUERADE.
enable_umbrella("IP6_NF_IPTABLES", 1, label="IP6_NF_IPTABLES")
enable_umbrella("IP6_NF_NAT", 1, label="IP6_NF_NAT")

# --- IP_SET (netfilter ipset): its own separate menuconfig umbrella in
#     net/netfilter/ipset/Kconfig -- distinct from NETFILTER_XTABLES/
#     NF_TABLES/NF_CONNTRACK, never touched this whole session.
enable_umbrella("IP_SET", 1, label="IP_SET")

# --- BRIDGE_NF_EBTABLES (ebtables, the bridge-layer sibling to iptables/
#     ip6tables/arptables): its prerequisites (BRIDGE, NETFILTER,
#     NETFILTER_XTABLES) are all already on, but the umbrella itself was
#     never explicitly enabled or walked. Note: this is the modern
#     ebtables path, distinct from BRIDGE_NF_EBTABLES_LEGACY (the old
#     sockopt interface gated by NETFILTER_XTABLES_LEGACY, which we
#     already turned on separately for the same byte-parity reasons).
enable_umbrella("BRIDGE_NF_EBTABLES", 1, label="BRIDGE_NF_EBTABLES")

# IP_NF_ARPTABLES: legacy arptables, a third family alongside
# IP_NF_IPTABLES/IP6_NF_IPTABLES that was never explicitly touched.
# Covers IP_NF_ARPFILTER/ARP_MANGLE as children.
enable_umbrella("IP_NF_ARPTABLES", 1, label="IP_NF_ARPTABLES")

enable_exact(("BRIDGE_NETFILTER", 1), ("NF_CT_NETLINK_HELPER", 1),
             ("NETFILTER_NETLINK_GLUE_CT", 2), ("NETFILTER_XT_MATCH_PHYSDEV", 1),
             ("NF_LOG_ARP", 1), ("NF_LOG_IPV4", 1), ("NF_CONNTRACK_BRIDGE", 1))

# --- MPTCP (Multipath TCP) -- never touched.
enable_umbrella("MPTCP", 2, label="MPTCP")
enable_exact(("INET_MPTCP_DIAG", 1), ("MPTCP_IPV6", 2))

# --- IP_SCTP -- whole protocol never enabled before.
enable_umbrella("IP_SCTP", 1, label="IP_SCTP")
enable_exact(("INET_SCTP_DIAG", 1), ("SCTP_DBG_OBJCNT", 0))  # DBG doesn't
# match the "DEBUG" deny-list pattern, so explicit insurance is needed.

# --- CRYPTO: confirmed via diagnostics that the actual crypto/Kconfig
#     core (cipher algorithms, DRBG/RNG, JITTERENTROPY, CRYPTO_LIB_*) was
#     never touched at all -- we'd only ever swept CRYPTO_DEV_ (hardware
#     accelerators) much earlier. Broad "CRYPTO" prefix (no trailing
#     underscore) catches everything in one sweep -- CRYPTO_DEV_* and the
#     CRYPTO_LIB_* symbols over in lib/crypto/Kconfig included -- so the
#     separate CRYPTO_DEV_/CRYPTO_LIB_ sweeps that used to sit here and
#     further up are gone; measured redundant, diff unchanged.
enable_by_prefix("CRYPTO")

# --- CRYPTO: the core software crypto API (crypto/Kconfig) -- a proper
#     menuconfig umbrella. The same sweep also covers drivers/crypto/'s
#     CRYPTO_DEV_* hardware accelerators and lib/crypto's CRYPTO_LIB_*,
#     since both start with "CRYPTO". Explains
#     CRYPTO_BLOWFISH_COMMON, CRYPTO_CAST_COMMON, CRYPTO_DRBG_MENU (and
#     its nested children CTR/HASH/HMAC), CRYPTO_FCRYPT, CRYPTO_PCBC, etc.
enable_umbrella("CRYPTO", 1, label="CRYPTO")

# Virtualization guest/host driver menus -- all three are menuconfig gates
# (VIRTIO_MENU/VHOST_MENU default y, VDPA is tristate) whose child driver
# families zabbly enables essentially wholesale. VDPA's vendor drivers
# (MLX5_VDPA_NET, IFCVF, ...) need their parent NIC cores, already on via the
# ETHERNET walk far above. VIRTIO_MENU has two children zabbly leaves off
# (VIRTIO_HARDEN_NOTIFICATION hardening toggle, VIRTIO_RTC_ARM arch-specific);
# they can't be pattern-denied, so they are suppressed as data in
# config_slices/virtualization.config instead.
enable_umbrella("VHOST_MENU", 2, label="VHOST_MENU")   # vhost host-side accel: VHOST_NET/SCSI/VSOCK/VDPA
enable_umbrella("VIRTIO_MENU", 2, label="VIRTIO_MENU") # virtio guest drivers: PCI/MMIO/BALLOON/MEM/INPUT/RTC/...

# Hyper-V guest support (validation-only parity; pointless on a KVM host, same
# stance as XEN). HYPERV is a plain bool gate whose driver zoo is scattered by
# `depends on HYPERV_VMBUS` across drivers/hv, net/hyperv, scsi, hid, pci, drm,
# uio -- NOT a menu subtree, so a subtree walk can't reach them. Enable the gate
# + sweep the HYPERV_* core family here, EARLY, so HYPERV_VMBUS is already on
# when the UIO/HID/DRM/PCI walks below run and pick up the cross-subsystem
# drivers (UIO_HV_GENERIC/HID_HYPERV_MOUSE/DRM_HYPERV/PCI_HYPERV). VTL_MODE and
# the stray PCI_HYPERV/MSHV bits are handled as data in virtualization.config.
enable_exact(("HYPERV", 2))                            # bool gate (set without walking -> avoids VTL_MODE)
enable_by_prefix("HYPERV_")                            # VMBUS + net/storage/utils/balloon/vsock/kbd/iommu/timer

enable_umbrella("KGDB", 2, label="KGDB")               # KGDB/KDB debugger: serial-console/kdb/keyboard/blocklist (KGDB_TESTS denied)
enable_umbrella("VIRT_DRIVERS", 2, label="VIRT_DRIVERS")  # virt guest drivers: VMGENID/VBOXGUEST/NITRO/SEV_GUEST/TDX_GUEST_DRIVER (ARM/FSL cap); also cascades the TSM_* selects

enable_umbrella("EVM", 2, label="EVM")                 # Extended Verification Module (integrity xattr protection)
enable_by_prefix("EVM_")                               # ATTR_FSUUID/ADD_XATTRS/EXTRA_SMACK_XATTRS are `depends on EVM` siblings
enable_exact(("HARDLOCKUP_DETECTOR", 2))               # NMI hard-lockup detector; the _PERF/_COUNTS_HRTIMER/_ARCH/_BUDDY sub-symbols are promptless and resolve themselves
enable_umbrella("FW_CFG_SYSFS", 1, label="FW_CFG_SYSFS")  # QEMU fw_cfg sysfs interface

# --- net/netfilter/Kconfig: the x_tables match/target module zoo itself.
#     We flipped NETFILTER_XTABLES_LEGACY on for byte-parity earlier, but
#     never actually walked NETFILTER_XTABLES's own subtree -- that's a
#     separate thing (the module list, not the legacy-tools switch).
enable_umbrella("NETFILTER_XTABLES", 1, label="NETFILTER_XTABLES")

# --- net/ipv4/netfilter/Kconfig: legacy iptables match modules
#     (IP_NF_MATCH_*) -- same story, the LEGACY switch alone doesn't walk
#     this subtree.
enable_umbrella("IP_NF_IPTABLES", 1, label="IP_NF_IPTABLES")

# --- net/netfilter/Kconfig: NF_CONNTRACK proper. The netfilter.config
#     fragment (loaded later) hand-picks a subset of NF_CONNTRACK_* --
#     walking the real subtree here covers what that hand-picked list
#     missed; the fragment's own explicit values still apply on top and
#     win where they differ, since it loads after this.
enable_umbrella("NF_CONNTRACK", 1, label="NF_CONNTRACK")

# --- net/bridge/Kconfig
enable_umbrella("BRIDGE", 1, label="BRIDGE")

# --- net/sched/Kconfig: NET_SCHED is the real umbrella covering BOTH
#     NET_CLS_* (classifiers) and NET_ACT_* (actions) -- NET_SCH_* queueing
#     disciplines were already hand-picked in networking.config, but
#     classifiers/actions live in the same file and were never walked.
#     NET_CLS_ACT specifically gates action visibility and needs setting
#     explicitly (it's a bool with no children of its own).
enable_umbrella("NET_SCHED", 2, label="NET_SCHED")

# --- drivers/md/Kconfig: device-mapper (dm-crypt, dm-thin, dm-raid,
#     dm-cache, dm-verity, dm-integrity, dm-multipath, ...). Confirmed via
#     zabbly-config this is its own thing worth walking explicitly, not
#     fully covered by the MD walk from several rounds back.
enable_umbrella("BLK_DEV_DM", 2, label="BLK_DEV_DM")

# --- net/9p/Kconfig (transport) + fs/9p/Kconfig (filesystem) -- two
#     separate small umbrellas, both needed for Plan 9 protocol support.
enable_umbrella("NET_9P", 1, label="NET_9P")
enable_umbrella("9P_FS", 1, label="9P_FS")

#
# Enable IPv6 (protocol suite: tunnels, extension headers, routing, etc.)
#
enable_umbrella("IPV6", 2, label="IPV6")

#
# zswap (compressed swap cache) -- flat, no meaningful driver zoo, so a
# direct assignment is the right tool here, not a subtree walk. Also
# genuinely useful for production memory pressure handling, not just
# zabbly-parity. Compressor choice mirrors zabbly-config exactly (lzo).
#
if "ZSWAP" in kconf.syms:
    kconf.syms["ZSWAP"].set_value(2)  # y
if "ZSWAP_COMPRESSOR_DEFAULT_LZO" in kconf.syms:
    kconf.syms["ZSWAP_COMPRESSOR_DEFAULT_LZO"].set_value(2)  # y

# ============================================================================
# The data half: per-symbol policy that no structural sweep can express.
#
# Load order is load-bearing -- these deliberately overwrite each other and
# the structural work above, last writer wins. Alphabetical order would be a
# different (wrong) config, which is why the sequence is written out here
# rather than globbed. Check it stays overlap-free with ./check_slices.py.
# ============================================================================
load_slices(
    FLAVOR,
    "nf_tables",
    "platform",
    "filesystems",
    "block_devices",
    "virtualization",
    "containers",
    "tracing",
    "networking",
    "secure_boot",
    "crypto",
    "misc",
)

# VIRTIO_VFIO_PCI (variant VFIO PCI driver for virtio devices) + its
# VIRTIO_VFIO_PCI_ADMIN_LEGACY child. Placed here, AFTER the config_slices
# load, because it depends on VFIO -- which virtualization.config only turns
# on a few lines above; running it up in the driver-family block would find
# VFIO still off and get silently capped.
enable_umbrella("VIRTIO_VFIO_PCI", 1, label="VIRTIO_VFIO_PCI")

kconf.load_config("kernel/configs/kvm_guest.config", replace=False)

finish()
