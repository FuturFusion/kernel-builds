#!/usr/bin/env python3
"""Server kernel flavor: a hypervisor/container host kernel.

This is the *policy* half of the generator -- what to switch on and why. All
the machinery it calls lives in genconfig.py; this file contains no Kconfig
tree-walking logic of its own, only decisions.

STATUS: this is currently a verbatim copy of the generic flavor, taken as a
starting point so that divergence from it is visible commit by commit rather
than arriving as one unreviewable drop. Nothing here has been trimmed yet.

Where it is going: this flavor runs VMs and containers on x86_64 server hardware.
Everything the generic flavor carries for desktop and laptop use -- sound,
graphics, media capture, wireless, consumer interconnects -- is exactly what
this flavor exists to leave out. The block near the end that the generic
flavor marks VALIDATION-ONLY is the obvious first thing to go.

It is still compared against misc/<series>/reference-<arch>-config, because
that is the only reference config in the tree and a diff is more informative
than no diff. But unlike the generic flavor, a *large* diff is the goal here,
not a defect: byte-parity with a general-purpose distro kernel would mean this
flavor had failed at its job. Read its diff as a list of what has been dropped
so far.

The data half lives in config_slices/ next to this file, loaded near the end.
Anything that is genuinely per-symbol policy (no family, no gate, no prefix)
belongs there rather than here.

Run with ./genconfig.sh <arch> server.
"""
import os
import sys

import kconfiglib

# This flavor's name is its directory name, so a flavor copied to a new
# directory loads its OWN config_slices/ without anyone having to remember to
# edit the load_slices() call below.
FLAVOR = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

# genconfig.py lives at the repository root, two levels up from
# flavors/<name>/config.py. Bootstrapping sys.path here rather than relying on
# PYTHONPATH keeps a flavor runnable however it is launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from genconfig import (
    enable_by_prefix,
    enable_exact,
    enable_menu,
    enable_umbrella,
    finish,
    load_slices,
    start,
)

kconf = start()

# EARLY PREREQUISITES: must run before the umbrella/prefix sweeps below --
# a sweep can only reach a symbol that's already visible. Lesson worth
# keeping: MFD parent chips need "I2C=y" specifically (not just != n) plus
# REGULATOR/GPIOLIB already on, or the MFD_ sweep below silently caps.

# STAGING: deliberately NOT walked -- enable_umbrella() here regressed the
# diff (pulls in INTEL_ATOMISP, A11Y_BRAILLE_CONSOLE). Its wanted families
# (COMEDI, GREYBUS, MOST_COMPONENTS, SPEAKUP, FB_TFT) have their own
# umbrellas further down; RAPIDIO has its own near the bus families.
enable_exact(("STAGING", 2))

# MDIO_* (MDIO bus drivers) and NET_IP* (IPv4 tunnel drivers): flat =m
# driver zoos, exactly what enable_by_prefix is for.
enable_by_prefix("MDIO_")
enable_by_prefix("NET_IP")

enable_by_prefix("MFD_")

# Enable all ethernet device drivers as modules
enable_umbrella("ETHERNET", 2, label="ETHERNET")

# Enable all hardware monitoring device drivers as modules
enable_umbrella("HWMON", 2, label="HWMON")

# Enable all RAS (Reliability, Availability, Serviceability) and EDAC drivers
enable_exact(("RAS", 2))                 # plain gate, no subtree of its own
enable_umbrella("EDAC", 2, label="EDAC")

# Enable all Watchdog drivers as modules
enable_umbrella("WATCHDOG", 2, label="WATCHDOG")

# Enable all RAID and LVM device drivers as modules
enable_umbrella("MD", 2, label="MD")

# Enable all SCSI/RAID/SAS/FC HBA drivers as modules
scsi = kconf.syms["SCSI"]
if scsi.tri_value == 0:          # SCSI_LOWLEVEL requires "SCSI!=n"
    scsi.set_value(2)            # y

enable_umbrella("SCSI_LOWLEVEL", 2, label="SCSI_LOWLEVEL")  # a gate, not a driver itself

# InfiniBand/RDMA HCAs + ULPs (IPoIB, SRP/SRPT, iSER/iSERT, RTRS). Tristate,
# and depends on "m || IPV6 != m" -- set to m directly rather than depending
# on IPV6's value here.
enable_umbrella("INFINIBAND", 1, label="INFINIBAND")

# CONFIG_EXPERT: kernel-wide visibility switch gating a huge fraction of the
# tree behind "depends on EXPERT" -- confirmed on in zabbly-config.
if "EXPERT" in kconf.syms:
    kconf.syms["EXPERT"].set_value(2)  # y

# MAXSMP: explains the NR_CPUS_DEFAULT/RANGE diff (zabbly=8192, ours=64).
if "MAXSMP" in kconf.syms:
    kconf.syms["MAXSMP"].set_value(2)  # y

# Kernel compression method: a `choice` block, single-select.
if "KERNEL_ZSTD" in kconf.syms:
    kconf.syms["KERNEL_ZSTD"].set_value(2)  # y

# Preemption model: a `choice` block. Confirmed via zabbly-config: PREEMPT=y.
if "PREEMPT" in kconf.syms:
    kconf.syms["PREEMPT"].set_value(2)  # y

# FUSION: LSI/Broadcom Fusion-MPT SCSI/FC/SAS HBA family, separate from
# SCSI_LOWLEVEL.
enable_umbrella("FUSION", 2, label="FUSION")

# INET_DIAG's real prerequisite -- never explicitly set before.
enable_umbrella("INET_DIAG", 1, label="INET_DIAG")

# I2C_DESIGNWARE_CORE is library-only; the real controller drivers
# (_PLATFORM/_PCI/_BAYTRAIL) are siblings depending on it.
enable_umbrella("I2C_DESIGNWARE_CORE", 2, label="I2C_DESIGNWARE_CORE")

# --- VME (VMEbus) device drivers -- industrial/telecom bus.
enable_umbrella("VME_BUS", 2, label="VME_BUS")

# Three embedded-ish buses that gate drivers scattered across other
# subsystems -- must run before the generic SERIAL_/I2C_/GPIO_ sweeps below,
# or those sweeps see the gated drivers as invisible and skip them:
# MCB (MEN Chameleon Bus), LITEX_ (LiteX FPGA SoC), KEBA_ (KEBA CP500 FPGA).
enable_umbrella("MCB", 1, label="MCB")
enable_by_prefix("LITEX_")
enable_by_prefix("KEBA_")

# COMMON_CLK_*: 30+ I2C/SPI-attached programmable clock generator chips.
enable_by_prefix("COMMON_CLK_")

# GPIB (IEEE-488 lab instrument bus), real now that STAGING is on.
enable_umbrella("GPIB", 1, label="GPIB")

# Reset controller framework.
enable_by_prefix("RESET_")

# Generic PHY framework (SerDes/USB/PCIe transceivers) -- distinct from
# Ethernet MDIO PHY drivers (vendor-name-first, no PHY_ prefix).
enable_by_prefix("PHY_")

# NVMEM (EEPROM layout parsers), incl. NVMEM_LAYOUT_ONIE_TLV for bare-metal
# networking switch hardware.
enable_by_prefix("NVMEM_")

enable_umbrella("CPU_FREQ", 2, label="CPU_FREQ")
enable_umbrella("THERMAL", 2, label="THERMAL")
enable_by_prefix("HW_RANDOM_")
enable_by_prefix("TCP_CONG_")

# FDDI (Fiber Distributed Data Interface).
enable_umbrella("FDDI", 2, label="FDDI")

# PHYLIB: unlocks ~50 vendor Ethernet PHY chip drivers.
enable_umbrella("PHYLIB", 2, label="PHYLIB")

# PSE (Power Sourcing Equipment / PoE controller framework).
enable_umbrella("PSE_CONTROLLER", 2, label="PSE_CONTROLLER")

enable_umbrella("RIONET", 1, label="RIONET")

# I2C bus controller drivers: plain menu, no controlling symbol, so a
# prefix sweep is the right tool (same shape as MFD_/PINCTRL_ before it).
enable_by_prefix("I2C_")

# PTP hardware clocks + PPS (pulse-per-second GPS/time-sync).
enable_umbrella("PTP_1588_CLOCK", 2, label="PTP_1588_CLOCK")
enable_by_prefix("PTP_1588_CLOCK_")  # individual clock drivers, prefix siblings
enable_umbrella("PPS", 2, label="PPS")

# IP6_NF_IPTABLES (legacy ip6tables) + IP6_NF_NAT, the real prerequisite for
# IP6_NF_TARGET_MASQUERADE.
enable_umbrella("IP6_NF_IPTABLES", 1, label="IP6_NF_IPTABLES")
enable_umbrella("IP6_NF_NAT", 1, label="IP6_NF_NAT")

# SCSI device handlers: multipath for enterprise storage arrays (RDAC/EMC/
# ALUA/HP), separate umbrella from SCSI_LOWLEVEL.
enable_umbrella("SCSI_DH", 2, label="SCSI_DH")

# MCTP (Management Component Transport Protocol) -- BMC/platform
# management, ties into the IPMI work from platform.config.
enable_umbrella("MCTP", 2, label="MCTP")
enable_by_prefix("MCTP_")  # transport drivers, `depends on MCTP` siblings
enable_by_prefix("QRTR_")  # Qualcomm IPC router transports, same shape

# Firmware loading framework core.
enable_umbrella("FW_LOADER", 2, label="FW_LOADER")

# Intel SoC PMIC drivers (Bay Trail/Cherry Trail/Merrifield).
enable_umbrella("INTEL_SOC_PMIC", 2, label="INTEL_SOC_PMIC")

# PMIC_OPREGION: must come after INTEL_SOC_PMIC's own walk above (its
# children depend on specific INTEL_SOC_PMIC_* variants).
enable_umbrella("PMIC_OPREGION", 2, label="PMIC_OPREGION")

# OCFS2: cluster filesystem.
enable_umbrella("OCFS2_FS", 1, label="OCFS2_FS")

# Parallel port core -- the real prerequisite for PATA_PARPORT's adapter
# modules (PATA_PARPORT_ATEN, _BPCK, etc.).
enable_umbrella("PARPORT", 1, label="PARPORT")

# Serial console, LEDs, RTC, PWM: real menuconfig umbrellas, never touched.
enable_umbrella("SERIAL_8250", 2, label="SERIAL_8250")
enable_umbrella("NEW_LEDS", 2, label="NEW_LEDS")
enable_umbrella("RTC_CLASS", 2, label="RTC_CLASS")
enable_umbrella("PWM", 2, label="PWM")

# USB device/peripheral mode -- separate top-level menuconfig from USB
# (host-mode only).
enable_umbrella("USB_GADGET", 1, label="USB_GADGET")

# NET_DSA vendor switch-chip drivers: plain `menu`, no controlling symbol,
# so a prefix sweep is needed (NET_DSA's own umbrella only covers tagging).
enable_by_prefix("NET_DSA_")

# PINCTRL: promptless base bool, driver zoo under a plain menu -- prefix
# sweep needed. On real x86 hardware, GPIO for platforms like Baytrail/
# Cherryview is actually delivered through these pinctrl+GPIO combos.
enable_by_prefix("PINCTRL_")

# IP_SET (netfilter ipset): its own menuconfig umbrella, distinct from
# NETFILTER_XTABLES/NF_TABLES/NF_CONNTRACK.
enable_umbrella("IP_SET", 1, label="IP_SET")

# BRIDGE_NF_EBTABLES: modern ebtables path, distinct from the LEGACY one.
enable_umbrella("BRIDGE_NF_EBTABLES", 1, label="BRIDGE_NF_EBTABLES")

# IP_NF_ARPTABLES: legacy arptables, covers ARPFILTER/ARP_MANGLE children.
enable_umbrella("IP_NF_ARPTABLES", 1, label="IP_NF_ARPTABLES")

enable_exact(("BRIDGE_NETFILTER", 1), ("NF_CT_NETLINK_HELPER", 1),
             ("NETFILTER_NETLINK_GLUE_CT", 2), ("NETFILTER_XT_MATCH_PHYSDEV", 1),
             ("NF_LOG_ARP", 1), ("NF_LOG_IPV4", 1), ("NF_CONNTRACK_BRIDGE", 1))

# MPTCP (Multipath TCP).
enable_umbrella("MPTCP", 2, label="MPTCP")
enable_exact(("INET_MPTCP_DIAG", 1), ("MPTCP_IPV6", 2))

# USB is unusually fragmented (Cadence/ChipIdea are third-party sibling
# umbrellas, some USB_GADGET children weren't reliably reached) -- a full
# prefix sweep catches everything regardless of which sibling file it's in.
enable_by_prefix("USB_")

# CRYPTO: broad prefix (no trailing underscore) catches crypto/Kconfig's
# core plus drivers/crypto's CRYPTO_DEV_* and lib/crypto's CRYPTO_LIB_* in
# one sweep.
enable_by_prefix("CRYPTO")

# PECI (Platform Environment Control Interface) -- real prerequisite for
# SENSORS_PECI_CPUTEMP/_DIMMTEMP; how Xeon/EPYC expose CPU/DIMM temp.
enable_umbrella("PECI", 1, label="PECI")

# GPIO: a handful of drivers (GPIO_I8255 + PMIC-companions) weren't reached
# by the GPIOLIB walk alone.
enable_by_prefix("GPIO_")

# SERIAL: SERIAL_8250 only covers one UART family -- chip-specific drivers
# (SC16IS7XX, SCCNXP, etc.) are independent siblings in the same file.
enable_by_prefix("SERIAL_")

# FB_CORE is a newer symbol (fbdev Kconfig restructuring) the original FB
# walk never accounted for; its driver zoo lives under a separate menu.
if "FB_CORE" in kconf.syms:
    kconf.syms["FB_CORE"].set_value(2)  # y
enable_by_prefix("FB_")

# Modern filesystems, never touched at all.
enable_umbrella("EROFS_FS", 1, label="EROFS_FS")
enable_umbrella("F2FS_FS", 1, label="F2FS_FS")

# FPGA manager framework + Intel/Altera DFL -- real enterprise FPGA
# accelerator cards.
enable_umbrella("FPGA", 1, label="FPGA")
enable_umbrella("FPGA_DFL", 1, label="FPGA_DFL")

# Device DAX: direct-access mode for persistent/CXL memory. Real prereq is
# DAX (a separate core bool), not DEV_DAX's own concern.
enable_umbrella("DEV_DAX", 1, label="DEV_DAX")

# Network teaming (alternative to bonding).
enable_umbrella("NET_TEAM", 1, label="NET_TEAM")

# UFS (Universal Flash Storage) host controller -- separate umbrella from
# SCSI_LOWLEVEL.
enable_umbrella("SCSI_UFSHCD", 1, label="SCSI_UFSHCD")

# Intel Trace Hub: real x86 platform debug/tracing hardware.
enable_umbrella("INTEL_TH", 1, label="INTEL_TH")

# POWER_RESET / PCIE_DW: neither is actually ARM-restricted in Kconfig;
# zabbly-config enables both on x86.
enable_umbrella("POWER_RESET", 2, label="POWER_RESET")
enable_umbrella("PCIE_DW", 2, label="PCIE_DW")

# EXTCON: external connector detection (USB cable type, dock, headphone
# jack). Two residual items are x86/Intel platform-relevant.
enable_umbrella("EXTCON", 2, label="EXTCON")

# CRYPTO (menuconfig umbrella walk) -- same sweep as the prefix walk above,
# explains the nested CRYPTO_DRBG_MENU children (CTR/HASH/HMAC).
enable_umbrella("CRYPTO", 1, label="CRYPTO")

# USB residual: drivers/usb/Kconfig sources dual-role/OTG controllers
# (cdns3, dwc3, dwc2, chipidea, ...) unconditionally at the top level --
# siblings to both USB and USB_GADGET, never reached by either walk.
enable_umbrella("USB_CDNS3", 1, label="USB_CDNS3")
enable_umbrella("USB_DWC3", 1, label="USB_DWC3")
enable_umbrella("USB_DWC2", 2, label="USB_DWC2")  # confirmed =y in zabbly
enable_umbrella("USB_CHIPIDEA", 1, label="USB_CHIPIDEA")

# Driver-family umbrellas/prefix sweeps: self-contained driver zoos the
# structural walker covers in full. Dependencies (PCI, WAN, NET_DSA,
# NETDEVICES, TTY, ...) are already satisfied by this point.
enable_umbrella("NTB", 1, label="NTB")            # Non-Transparent Bridge + NTB_* clients
enable_umbrella("BCMA", 1, label="BCMA")          # Broadcom SoC bus
enable_umbrella("SSB", 1, label="SSB")            # Sonics Silicon Backplane bus
enable_umbrella("RAPIDIO", 2, label="RAPIDIO")    # RapidIO interconnect + switches (=y: zabbly builds the bus in)
enable_umbrella("XILLYBUS", 1, label="XILLYBUS")  # generic FPGA interface bus
enable_umbrella("HDLC", 1, label="HDLC")          # generic HDLC + per-protocol drivers
enable_umbrella("B53", 1, label="B53")            # Broadcom BCM53xx DSA switch family
enable_umbrella("TARGET_CORE", 1, label="TARGET_CORE")  # LIO SCSI/iSCSI/FC target + TCM_* backstores
enable_umbrella("SLIP", 1, label="SLIP")          # SLIP net driver (parent for the SLIP_* options below)
enable_by_prefix("SERIO_")                        # input serio port drivers (siblings, no gate)
enable_by_prefix("SLIP_")                         # SLIP line-discipline compression options
enable_by_prefix("MLXREG_")                       # Mellanox register-access platform drivers
enable_by_prefix("ADT7316")                       # ADT7316/7516 sensor (core + I2C/SPI variants)
enable_by_prefix("ZL3073X")                       # Microchip ZL3073x clock/timing (core + I2C/SPI)
enable_by_prefix("RAVE_SP_")                      # RAVE supervisory-processor MFD drivers
enable_by_prefix("MIPI_I3C")                      # MIPI I3C host-controller interface

# Virtualization guest/host driver menus: VHOST_MENU/VDPA are host-side
# accel; VIRTIO_MENU's guest drivers zabbly enables essentially wholesale
# (its two leave-off children are suppressed as data in
# config_slices/virtualization.config instead).
enable_umbrella("VHOST_MENU", 2, label="VHOST_MENU")   # vhost host-side accel: VHOST_NET/SCSI/VSOCK/VDPA
enable_umbrella("VDPA", 1, label="VDPA")               # vDPA bus + sim/vendor drivers
enable_umbrella("VIRTIO_MENU", 2, label="VIRTIO_MENU") # virtio guest drivers: PCI/MMIO/BALLOON/MEM/INPUT/RTC/...
enable_umbrella("INTEL_MEI", 1, label="INTEL_MEI")     # Intel Management Engine Interface + ME/TXE/GSC/CSC/VSC/HDCP/PXP

# Hyper-V guest support (validation-only parity; pointless on a KVM host,
# same stance as XEN). HYPERV_VMBUS enabled early so the UIO/HID/DRM/PCI
# walks below pick up its cross-subsystem drivers. VTL_MODE and stray
# PCI_HYPERV/MSHV bits are handled as data in virtualization.config.
enable_exact(("HYPERV", 2))                            # bool gate (set without walking -> avoids VTL_MODE)
enable_by_prefix("HYPERV_")                            # VMBUS + net/storage/utils/balloon/vsock/kbd/iommu/timer

enable_umbrella("UIO", 1, label="UIO")                 # userspace I/O drivers (FSL/PPC children cap on x86)
enable_umbrella("COUNTER", 1, label="COUNTER")         # counter subsystem: 104_QUAD_8/INTEL_QEP/INTERRUPT_CNT (SoC drivers cap on x86)
enable_umbrella("MEDIA_CEC_SUPPORT", 2, label="MEDIA_CEC_SUPPORT")  # HDMI-CEC adapters: GPIO/CH7322/CROS_EC/NXP/SECO (SoC drivers cap on x86)
enable_umbrella("PCI_ENDPOINT", 2, label="PCI_ENDPOINT")  # PCI endpoint framework: PCI_EPF_MHI/NTB/VNTB + gates PCIE_DW_PLAT_EP / NVME_TARGET_PCI_EPF
enable_umbrella("KGDB", 2, label="KGDB")               # KGDB/KDB debugger: serial-console/kdb/keyboard/blocklist (KGDB_TESTS denied)
enable_umbrella("VIRT_DRIVERS", 2, label="VIRT_DRIVERS")  # virt guest drivers: VMGENID/VBOXGUEST/NITRO/SEV_GUEST/TDX_GUEST_DRIVER (ARM/FSL cap); also cascades the TSM_* selects
enable_umbrella("USB4", 1, label="USB4")               # USB4/Thunderbolt bus (DMA_TEST denied, DEBUGFS_WRITE/MARGINING denied as "(DANGEROUS)" distro opt-outs)
enable_by_prefix("USB4_")                              # USB4_NET lives under drivers/net, not inside the `if USB4` block, so the walk can't reach it

# More single-gate families: each showed up in the diff as one wrong value
# plus several "missing" lines that are really just invisible while the
# gate is off. Where sub-options are prefix siblings rather than nested
# menu children, a prefix sweep follows the umbrella.
enable_umbrella("EVM", 2, label="EVM")                 # Extended Verification Module (integrity xattr protection)
enable_by_prefix("EVM_")                               # ATTR_FSUUID/ADD_XATTRS/EXTRA_SMACK_XATTRS are `depends on EVM` siblings
enable_exact(("HARDLOCKUP_DETECTOR", 2))               # NMI hard-lockup detector; the _PERF/_COUNTS_HRTIMER/_ARCH/_BUDDY sub-symbols are promptless and resolve themselves
enable_umbrella("JFS_FS", 1, label="JFS_FS")
enable_by_prefix("JFS_")                               # POSIX_ACL/SECURITY/STATISTICS are `depends on JFS_FS` siblings
enable_umbrella("AFS_FS", 1, label="AFS_FS")
enable_by_prefix("AFS_")                               # AFS_FSCACHE
enable_umbrella("FW_CFG_SYSFS", 1, label="FW_CFG_SYSFS")  # QEMU fw_cfg sysfs interface

enable_umbrella("DMADEVICES", 2, label="DMADEVICES")   # dmaengine drivers: IOAT/IDMA64/PTDMA/QDMA/DW(+AXI)/PLX/SWITCHTEC/ALTERA/XILINX (SoC ones cap on x86)
enable_umbrella("MULTIPLEXER", 2, label="MULTIPLEXER") # MUX_ADG792A/ADGS1408/GPIO/MMIO
enable_umbrella("PM_DEVFREQ", 2, label="PM_DEVFREQ")   # devfreq governors: SIMPLE_ONDEMAND/PERFORMANCE/POWERSAVE/USERSPACE/PASSIVE
enable_umbrella("RPMSG", 1, label="RPMSG")             # remote-processor messaging: CHAR/CTRL/TTY/QCOM_GLINK
enable_umbrella("REMOTEPROC", 2, label="REMOTEPROC")
enable_umbrella("INTERCONNECT", 2, label="INTERCONNECT")
enable_umbrella("MEMORY", 2, label="MEMORY")           # memory-controller drivers
enable_umbrella("HTE", 2, label="HTE")                 # hardware timestamping engine
enable_umbrella("TEE", 1, label="TEE")                 # Trusted Execution Environment (AMDTEE on x86)
enable_umbrella("FWCTL", 1, label="FWCTL")             # firmware control: FWCTL_BNXT/MLX5/PDS
enable_by_prefix("EEPROM_")                            # I2C/SPI EEPROM drivers sit under a plain `menu`, no gate to walk from
enable_umbrella("DMABUF_HEAPS", 2, label="DMABUF_HEAPS")  # dma-buf exporter heaps (SYSTEM, and TEE_DMABUF_HEAPS via TEE above)
enable_umbrella("SIOX", 1, label="SIOX")               # Eckelmann SIOX bus (+ SIOX_BUS_GPIO, GPIO_SIOX)
enable_umbrella("DLM", 1, label="DLM")                 # distributed lock manager -- the prerequisite for GFS2_FS_LOCKING_DLM
enable_by_prefix("PVPANIC")                            # paravirtualized panic notifier: MMIO + PCI transports
enable_by_prefix("AD525X_DPOT")                        # digital potentiometers: I2C + SPI halves
enable_by_prefix("QCOM_PMIC_GLINK")                    # Qualcomm PMIC GLINK (+ BATTERY_QCOM_BATTMGR, UCSI_PMIC_GLINK)
enable_by_prefix("PCI_PWRCTRL")                        # PCI power-control slot drivers
enable_exact(("SOC_BUS", 2), ("FW_LOADER_COMPRESS", 2))   # promptless-adjacent singletons; FW_LOADER_COMPRESS gates its XZ/ZSTD backends
enable_menu("Misc devices")                            # drivers/misc: ~25 unrelated drivers sharing only a plain `menu`
enable_menu("EFI (Extensible Firmware Interface) Support")  # EFI_BOOTLOADER_CONTROL/CAPSULE_LOADER/RCI2_TABLE
enable_menu("VFIO support for PCI devices")            # the per-vendor VFIO variant drivers (MLX5/PDS/QAT/XE) + NOIOMMU/PCI_VGA
enable_menu("Kernel hardening options")                # FORTIFY_SOURCE, HARDENED_USERCOPY, INIT_ON_ALLOC_DEFAULT_ON, PAGE_POISONING, ZERO_CALL_USED_REGS
enable_umbrella("POWERCAP", 2, label="POWERCAP")       # INTEL_RAPL(+TPMI), DTPM
enable_exact(("NTB_NETDEV", 1))     # single tristates with no menu or prefix to hang off
enable_by_prefix("MUX_")                               # drivers/mux: MULTIPLEXER is a plain config, so its chip drivers aren't nested under it
enable_by_prefix("RPMSG_")                             # same shape for RPMSG: CHAR/CTRL/TTY/QCOM_GLINK_RPM are `depends on RPMSG` siblings

# Batch verified directly against zabbly-config's actual values.
# tri_value key: 0=n, 1=m, 2=y.

enable_umbrella("SMC", 1, label="SMC")  # Shared Memory Communications, RDMA-accelerated sockets (pairs with INFINIBAND)
enable_umbrella("NETFILTER_XTABLES", 1, label="NETFILTER_XTABLES")  # the x_tables match/target module zoo
enable_umbrella("IP_NF_IPTABLES", 1, label="IP_NF_IPTABLES")  # legacy iptables match modules
enable_umbrella("NF_CONNTRACK", 1, label="NF_CONNTRACK")  # the netfilter.config fragment's hand-picked subset still applies on top

enable_umbrella("BRIDGE", 1, label="BRIDGE")

# NET_DSA: embedded switch-chip drivers. No production case on x86
# servers -- validation-only.
enable_umbrella("NET_DSA", 1, label="NET_DSA")

# NET_SCHED covers NET_CLS_*/NET_ACT_* (classifiers/actions); NET_SCH_*
# queueing disciplines are already hand-picked in networking.config.
enable_umbrella("NET_SCHED", 2, label="NET_SCHED")

enable_umbrella("PATA_PARPORT", 1, label="PATA_PARPORT")  # nested under ATA, belt-and-suspenders explicit set
enable_umbrella("BLK_DEV_DM", 2, label="BLK_DEV_DM")  # device-mapper: dm-crypt/thin/raid/cache/verity/multipath
enable_umbrella("NET_9P", 1, label="NET_9P")  # Plan 9 transport
enable_umbrella("9P_FS", 1, label="9P_FS")    # Plan 9 filesystem
enable_umbrella("PPP", 2, label="PPP")
enable_umbrella("GPIOLIB", 2, label="GPIOLIB")

# Enable IPv6 (protocol suite: tunnels, extension headers, routing, etc.)
enable_umbrella("IPV6", 2, label="IPV6")

# Enable IPVS (IP Virtual Server / Linux load balancer) as modules
enable_umbrella("IP_VS", 1, label="IP_VS")

# Enable L2TP as modules
enable_umbrella("L2TP", 1, label="L2TP")

# Enable all SATA/PATA controller drivers as modules -- most non-NVMe
# server storage still goes through libata.
enable_umbrella("ATA", 2, label="ATA")

# Enable CXL (Compute Express Link) support -- real enterprise server
# memory expansion/tiering concern.
enable_umbrella("CXL_BUS", 1, label="CXL_BUS")

# zswap (compressed swap cache) -- flat, direct assignment. Compressor
# choice mirrors zabbly-config (lzo).
if "ZSWAP" in kconf.syms:
    kconf.syms["ZSWAP"].set_value(2)  # y
if "ZSWAP_COMPRESSOR_DEFAULT_LZO" in kconf.syms:
    kconf.syms["ZSWAP_COMPRESSOR_DEFAULT_LZO"].set_value(2)  # y

# AF_XDP sockets -- high-performance packet processing on a hypervisor host.
if "XDP_SOCKETS" in kconf.syms:
    kconf.syms["XDP_SOCKETS"].set_value(2)  # y
if "XDP_SOCKETS_DIAG" in kconf.syms:
    kconf.syms["XDP_SOCKETS_DIAG"].set_value(1)  # m

# Umbrellas verified directly against Kconfig source (menuconfig, correct
# bool/tristate type):
_VALIDATION_ONLY_TRISTATE_UMBRELLAS = [
    "MEDIA_SUPPORT",
    "USB",
    "FB",
    "MTD",
    # "I2C" removed from this generic list -- it needs to stay =y
    # specifically (not =m) because several MFD parent chips depend on
    # I2C=y strictly, and this generic loop's "set to m if tristate"
    # logic was silently overriding the explicit I2C=y fix set earlier
    # (right before the MFD sweep), retroactively breaking MFD_MAX8925
    # and friends. Confirmed via checkpoint tracing: I2C was correct
    # right after the MFD sweep, then wrong by the time this loop had run.
    "SPI",
    "MMC",
    "HID",
    "POWER_SUPPLY",
    "TYPEC",
]
for name in _VALIDATION_ONLY_TRISTATE_UMBRELLAS:
    if name in kconf.syms:
        # tristate -> m, bool -> y, matching enable_by_prefix's convention
        sym = kconf.syms[name]
        enable_umbrella(name, 1 if sym.orig_type == kconfiglib.TRISTATE else 2)
    else:
        print(f"note: symbol {name} not found in this kernel tree -- skipped")

# MEDIA_SUPPORT alone isn't enough -- VIDEO_DEV/DVB_CORE only default on if a
# bool category switch is set, and those default off while
# MEDIA_SUPPORT_FILTER is on (the default unless EXPERT). The subtree walker
# skips bool, so this has to be set directly.
if "MEDIA_SUPPORT_FILTER" in kconf.syms:
    kconf.syms["MEDIA_SUPPORT_FILTER"].set_value(2)  # y -- CORRECTED: zabbly
    # keeps the filter ON and enables each category individually, rather than
    # disabling the filter entirely. Both approaches unlock the same media
    # drivers practically, but only this one is byte-identical to zabbly.
    kconf.syms["MEDIA_SDR_SUPPORT"].set_value(2)
    kconf.syms["MEDIA_DIGITAL_TV_SUPPORT"].set_value(0)
    kconf.syms["MEDIA_ANALOG_TV_SUPPORT"].set_value(0)
    kconf.syms["MEDIA_CAMERA_SUPPORT"].set_value(0)
    kconf.syms["MEDIA_RADIO_SUPPORT"].set_value(0)
    kconf.syms["MEDIA_TEST_SUPPORT"].set_value(0)
#    kconf.syms["MEDIA_SUBDRV_AUTOSELECT"].set_value(0)

# zabbly-config has CONFIG_OF=y, which is why a tranche of DRM panel/
# bridge-chip drivers ("depends on OF") are visible there but not for us.
# OF is architecture-independent infrastructure, safe to enable for parity.
if "OF" in kconf.syms:
    kconf.syms["OF"].set_value(2)  # y

# ASoC (SND_SOC) machine drivers for Intel platforms sit behind a two-level
# bool gate chain -- set explicitly as belt-and-suspenders alongside the
# general "bool with children" rule in enable_subtree.
for name in ("SND_SOC_INTEL_SST_TOPLEVEL", "SND_SOC_SOF_INTEL_TOPLEVEL", "SND_SOC_INTEL_MACH"):
    if name in kconf.syms:
        kconf.syms[name].set_value(2)  # y

# Several SND_SOC_INTEL_*_MACH drivers also depend on this Intel platform
# I2C/SPI/UART controller support.
if "X86_INTEL_LPSS" in kconf.syms:
    kconf.syms["X86_INTEL_LPSS"].set_value(2)  # y

# USB-attached media devices (webcams, USB DVB dongles) sit behind
# MEDIA_USB_SUPPORT, a bool gate under MEDIA_SUPPORT's subtree.
if "MEDIA_USB_SUPPORT" in kconf.syms:
    kconf.syms["MEDIA_USB_SUPPORT"].set_value(2)  # y

# USB network adapters live in a sibling menu, not inside USB's own subtree.
enable_umbrella("USB_NET_DRIVERS", 1, label="USB_NET_DRIVERS")

# REGULATOR and X86_PLATFORM_DEVICES are bool, not tristate.
for name in ("REGULATOR", "X86_PLATFORM_DEVICES"):
    enable_umbrella(name, 2)   # y -- these are bool umbrellas

# ============================================================================
# END VALIDATION-ONLY BLOCK
# ============================================================================

# The data half: per-symbol policy that no structural sweep can express.
# Load order is load-bearing (last writer wins) -- check it stays
# overlap-free with ./check_slices.py.
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
    "drivers",
    "drm",
)

# Both placed after the config_slices load because they depend on symbols
# only turned on there (VFIO via virtualization.config, TRACING via
# tracing.config) -- running them earlier would find the dependency still
# off and get silently capped.
enable_umbrella("VIRTIO_VFIO_PCI", 1, label="VIRTIO_VFIO_PCI")
enable_umbrella("STM", 1, label="STM")

finish()
