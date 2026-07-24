#!/usr/bin/env python3
"""IncusOS kernel flavor: a hypervisor/container host kernel.

This is the *policy* half of the generator -- what to switch on and why. All
the machinery it calls lives in genconfig.py; this file contains no Kconfig
tree-walking logic of its own, only decisions.

STATUS: this is currently a verbatim copy of the generic flavor, taken as a
starting point so that divergence from it is visible commit by commit rather
than arriving as one unreviewable drop. Nothing here has been trimmed yet.

Where it is going: IncusOS runs VMs and containers on x86_64 server hardware.
Everything the generic flavor carries for desktop and laptop use -- sound,
graphics, media capture, wireless, consumer interconnects -- is exactly what
this flavor exists to leave out. The block near the end that the generic
flavor marks VALIDATION-ONLY is the obvious first thing to go.

It is still compared against misc/zabbly-config, because that is the only
reference config in the tree and a diff is more informative than no diff. But
unlike the generic flavor, a *large* diff is the goal here, not a defect:
byte-parity with a general-purpose distro kernel would mean this flavor had
failed at its job. Read its diff as a list of what has been dropped so far.

The data half lives in config_slices/ next to this file, loaded near the end.
Anything that is genuinely per-symbol policy (no family, no gate, no prefix)
belongs there rather than here.

Run with ./genconfig.sh incus-os.
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

from genconfig import (  # noqa: E402  (import follows the path bootstrap above)
    start, load_slices, finish,
    enable_umbrella, enable_exact, enable_menu, enable_by_prefix,
)

kconf = start()

# ============================================================================
# EARLY PREREQUISITES
#
# Everything in this block has to run before the umbrella/prefix sweeps below,
# because those sweeps can only reach a symbol that is already *visible*. Get
# the order wrong and a driver is attempted while its parent is still off; it
# silently caps, and the symptom looks like a "promptless symbol we can't set"
# rather than an ordering bug. That misdiagnosis cost this project many rounds.
#
# The concrete lesson, kept because it is easy to re-introduce: MFD parent
# chips usually depend on "I2C=y" specifically (built-in, not module -- PMICs
# probe early at boot), not merely "I2C != n", and several also need the
# REGULATOR / GPIOLIB framework bools already on (e.g. MFD_SEC_CORE depends on
# I2C=y && REGULATOR, MFD_TPS6586X on I2C=y && GPIOLIB). With those satisfied
# first, the MFD_ sweep below reaches the whole family, and the REGULATOR_*,
# SENSORS_*, RTC_DRV_*, GPIO_* and CHARGER_* companion drivers that hang off
# those parents come along later in their own sweeps.
#
# (These prerequisites used to be data, loaded from a separate
# zabbly_exact_values.config at this point in the file. That file has been
# retired: the values it carried are now either set structurally right here or
# distributed into config_slices/. See this flavor's config_slices/.)
# ============================================================================

# RC_CORE (remote-control core) needs a real subtree walk rather than a bare
# set: DVB_USB and VIDEO_CX88 depend on it, and it has a driver family of its
# own underneath (the IR_* receiver/decoder drivers). Setting only the top
# switch is why 32 IR_* symbols once showed up as "never attempted" while
# RC_CORE itself read as correctly on.
enable_umbrella("RC_CORE", 1, label="RC_CORE")

# Two master gates that used to be bare CONFIG_X=y data lines. They are set
# here, early, because everything downstream depends on them being on -- but
# deliberately NOT walked. enable_umbrella() was tried here first
# and regressed the diff from 9 to 21: walking drivers/staging pulls in
# STAGING_MEDIA_DEPRECATED -> INTEL_ATOMISP -> the VIDEO_ATOMISP_* sensor
# drivers, and walking drivers/accessibility pulls in A11Y_BRAILLE_CONSOLE --
# none of which zabbly ships. These two gates exist to make a subtree
# *reachable*; the families inside that we actually want (COMEDI, GREYBUS,
# MOST_COMPONENTS, SPEAKUP, FB_TFT) each have their own targeted umbrella
# further down. RAPIDIO is handled by its existing umbrella near the bus
# families instead -- it is a tristate, and a second call here would just be
# clobbered by that one anyway.
enable_exact(("STAGING", 2), ("ACCESSIBILITY", 2))

# Two more flat families that were sitting in zabbly_exact_values.config as
# 11 individual lines. Both are pure "=m driver zoo under a plain menu", which
# is exactly what enable_by_prefix is for.
#   MDIO_*  -- MDIO bus drivers (GPIO/HISI_FEMAC/MVUSB/OCTEON/IPQ4019/IPQ8064)
#              and the MDIO_BUS_* multiplexers, which this subsumes.
#   NET_IP* -- the IPv4 tunnel drivers (IPIP/IPGRE(+DEMUX,BROADCAST)/IPVTI).
enable_by_prefix("MDIO_")
enable_by_prefix("NET_IP")

enable_by_prefix("MFD_")

#
# Enable all ethernet device drivers as modules
#
enable_umbrella("ETHERNET", 2, label="ETHERNET")

#
# Enable all hardware monitoring device drivers as modules
#
enable_umbrella("HWMON", 2, label="HWMON")

#
# Enable all Reliability, Availability and Serviceability (RAS) and
# EDAC (Error Detection and Correction) drivers as modules
#
enable_exact(("RAS", 2))                 # plain gate, no subtree of its own
enable_umbrella("EDAC", 2, label="EDAC")

#
# Enable all Watchdog drivers as modules
#
enable_umbrella("WATCHDOG", 2, label="WATCHDOG")

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

#
# Enable all InfiniBand/RDMA HCA drivers and ULPs (IPoIB, SRP/SRPT,
# iSER/iSERT, RTRS) as modules. Unlike ETHERNET/SCSI_LOWLEVEL, INFINIBAND
# is tristate (not bool), and depends on "m || IPV6 != m" -- so we set the
# umbrella itself to m rather than y, sidestepping that constraint entirely
# instead of depending on knowing IPV6's value here.
#
enable_umbrella("INFINIBAND", 1, label="INFINIBAND")

# ============================================================================
# CONFIG_EXPERT: kernel-wide visibility switch, not a driver subsystem.
# A large fraction of options across the ENTIRE tree are gated behind
# "depends on EXPERT" or change their default under "!EXPERT" -- this is
# almost certainly higher-leverage than any single umbrella fix so far,
# since it isn't scoped to one subsystem. Confirmed real (zabbly-config
# has CONFIG_EXPERT=y, ours had it off) via the raw diff, not the
# umbrella-scoped cross-reference tooling -- this lives in init/Kconfig,
# outside every subtree we've walked.
# ============================================================================
if "EXPERT" in kconf.syms:
    kconf.syms["EXPERT"].set_value(2)  # y

# MAXSMP: explains the NR_CPUS_DEFAULT/RANGE differences directly
# (zabbly=8192, ours=64) -- another core kernel/arch option, same
# previously-unaddressed area as EXPERT above.
if "MAXSMP" in kconf.syms:
    kconf.syms["MAXSMP"].set_value(2)  # y

# Kernel compression method: a `choice` block, single-select.
if "KERNEL_ZSTD" in kconf.syms:
    kconf.syms["KERNEL_ZSTD"].set_value(2)  # y

# --- Preemption model: a `choice` block (PREEMPT_NONE/VOLUNTARY/PREEMPT/RT).
#     Confirmed via zabbly-config: CONFIG_PREEMPT=y.
if "PREEMPT" in kconf.syms:
    kconf.syms["PREEMPT"].set_value(2)  # y

# --- GREYBUS: Project Ara / Greybus protocol subsystem, also under
#     staging -- confirmed via zabbly-config (CONFIG_GREYBUS=m).
enable_umbrella("GREYBUS", 1, label="GREYBUS")

# --- Embedded-controller platform drivers: real and confirmed via
# zabbly-config, added per explicit request despite being company/laptop-
# specific (CROS_EC=Chromebook, WILCO_EC=Google's Chrome Enterprise
# laptop line, SURFACE_AGGREGATOR=Microsoft Surface, FSI=IBM POWER
# service interface). None of these matter for a real x86 server
# deployment, but they're legitimate umbrellas we simply hadn't added.
# CHROME_PLATFORMS is the master gate for the whole ChromeOS platform
# driver directory (CROS_EC, CHROMEOS_*, WILCO_EC, CROS_EC_TYPEC, etc.)
# -- confirmed still off despite everything downstream being configured
# for many rounds now. This is almost certainly why the entire family
# showed up as completely ABSENT rather than just capped.
enable_umbrella("CROS_EC", 1, label="CROS_EC")

# CROS_EC has resisted many rounds of investigation -- some legacy
# children (CROS_EC_CHARDEV, etc.) depend on MFD_CROS_EC specifically
# rather than CROS_EC directly. Our MFD_ prefix sweep should already
# reach it, but forcing it explicitly here too as a targeted retry.

# --- CHROMEOS_* platform drivers: simpler than the CROS_EC/MFD_CROS_EC
# family, mostly just depend on ACPI (already on). Never touched.
enable_umbrella("WILCO_EC", 1, label="WILCO_EC")
enable_umbrella("SURFACE_AGGREGATOR", 1, label="SURFACE_AGGREGATOR")
enable_umbrella("FSI", 1, label="FSI")

# --- Raw-NAND flash filesystems. UBIFS_FS depends on MTD_UBI (the UBI
# volume-management layer), a separate umbrella we hadn't touched.
enable_umbrella("MTD_UBI", 1, label="MTD_UBI")
enable_umbrella("UBIFS_FS", 1, label="UBIFS_FS")
enable_umbrella("JFFS2_FS", 1, label="JFFS2_FS")

# --- TIPC (Transparent Inter-Process Communication) -- real cluster/
# cloud networking protocol, never touched.
enable_umbrella("TIPC", 1, label="TIPC")

# --- FUSION (LSI/Broadcom Fusion-MPT SCSI/FC/SAS HBA family) -- a
# separate umbrella from SCSI_LOWLEVEL, genuinely relevant enterprise
# storage/HBA hardware, never touched.
enable_umbrella("FUSION", 2, label="FUSION")

# INET (fundamental TCP/IP support) was never explicitly set anywhere in
# this script -- the real prerequisite for INET_DIAG, confirmed missing
# the same way I2C/RC_CORE were before.
enable_umbrella("INET_DIAG", 1, label="INET_DIAG")

# I2C_DESIGNWARE_CORE is a library-only symbol with no real children of
# its own (same shape as RC_CORE before the fix) -- the actual individual
# controller drivers (I2C_DESIGNWARE_PLATFORM/_PCI/_BAYTRAIL) are
# separate sibling symbols depending on it, never independently touched.
enable_umbrella("I2C_DESIGNWARE_CORE", 2, label="I2C_DESIGNWARE_CORE")

# --- BT_HCIUART: the real prerequisite for BT_HCIUART_BCM/BT_QCA (UART-
# attached Bluetooth controllers), never touched.
# --- BT_HCIUART's real prerequisite: SERIAL_DEV_BUS (the serdev
# framework for attaching devices to serial ports), confirmed real via
# zabbly-config and never touched.
enable_umbrella("BT_HCIUART", 1, label="BT_HCIUART")

# ============================================================================
# Batch from a raw diff -y chunk against zabbly-config (init/Kconfig,
# kernel/Kconfig, arch/x86/Kconfig, block layer, mm). Mostly plain
# explicit sets; a few are `choice`-block conflicts where the wrong
# member was already selected (both the correct member is enabled AND
# the wrong one explicitly disabled, for safety), and three are things
# that need to be DISABLED because they were wrongly on in our output.
# ============================================================================

# ============================================================================
# Second batch from the next diff -y chunk. Same conventions as before.
# ============================================================================
                                              # separate from the DEFAULT_GOV choice

# ============================================================================
# Third batch: VME bus, Mellanox switch platform family, Surface family,
# and one item that needs to be DISABLED.
# ============================================================================

# --- VME (VMEbus) device drivers -- industrial/telecom bus, never touched.
enable_umbrella("VME_BUS", 2, label="VME_BUS")

# --- Three more embedded-ish buses/carriers that gate drivers scattered across
# completely different subsystems. They have to run HERE, before the generic
# SERIAL_/I2C_/GPIO_ prefix sweeps further down, or those sweeps see the gated
# drivers as invisible and skip them:
#   MCB   (MEN Chameleon Bus)  -> MCB_PCI/MCB_LPC + SERIAL_MEN_Z135,
#                                 SERIAL_8250_MEN_MCB, GPIO_MENZ127,
#                                 MEN_A21_WDT, MEN_Z188_ADC
#   LITEX_ (LiteX FPGA SoC)    -> LITEX_SOC_CONTROLLER selects the promptless
#                                 LITEX, which unblocks SERIAL_LITEUART and
#                                 MMC_LITEX
#   KEBA_ (KEBA CP500 FPGA)    -> KEBA_CP500 registers the sub-devices behind
#                                 SERIAL_8250_KEBA, I2C_KEBA, KEBA_LAN9252
enable_umbrella("MCB", 1, label="MCB")
enable_by_prefix("LITEX_")
enable_by_prefix("KEBA_")

# --- Same story for the PCI/USB card-reader bridge chips in
# drivers/misc/cardreader: MISC_RTSX itself is promptless and selected by the
# PCI/USB halves. They gate the SD/MMC and Memory Stick front-ends
# (MMC_REALTEK_PCI/USB, MMC_ALCOR, MEMSTICK_REALTEK_PCI/USB), so they have to
# precede the MMC/MEMSTICK families below. The whole "MISC_" prefix is safe to
# sweep -- it is only these three plus MISC_RP1 (Raspberry Pi southbridge, also
# =m in zabbly) and the MISC_FILESYSTEMS menu gate.
enable_by_prefix("MISC_")

# ============================================================================
# Fourth batch: clock generator chips, mailbox/hwspinlock, IOMMUFD.
# ============================================================================

# --- COMMON_CLK_*: 30+ I2C/SPI-attached programmable clock generator
# chips (drivers/clk/Kconfig). COMMON_CLK itself is confirmed already on;
# the individual chip options are scattered enough that a prefix sweep is
# the right tool, same reasoning as MFD_/PINCTRL_/I2C_ before.
enable_by_prefix("COMMON_CLK_")

# ============================================================================
# Fifth batch: GPIB, staging IIO chips, STAGING_MEDIA family, MOST,
# GREYBUS (prefix sweep this time -- the umbrella alone wasn't reaching
# its children), XIL_AXIS_FIFO.
# ============================================================================

# --- GPIB (IEEE-488 lab instrument bus) -- drivers/staging/gpib, real
# now that STAGING is on. Umbrella walk should reach the whole family.
enable_umbrella("GPIB", 1, label="GPIB")

# --- GREYBUS: the umbrella itself (=m) was already correctly set, but
# none of its 18 children were ever reached -- same "separate menu, not
# nested" shape as several families before. Prefix sweep instead.
enable_by_prefix("GREYBUS_")

# ============================================================================
# Sixth batch: reset controllers, generic PHY framework, NTB, NVMEM.
# ============================================================================

# --- Reset controller framework (drivers/reset/Kconfig).
enable_by_prefix("RESET_")

# --- Generic PHY framework (drivers/phy/Kconfig) -- SerDes/USB/PCIe
# transceiver drivers, wide vendor variety, prefix sweep. Distinct from
# Ethernet MDIO PHY drivers (those use vendor-name-first naming like
# BROADCOM_PHY, not a PHY_ prefix, so no collision here.
enable_by_prefix("PHY_")

# --- NVMEM (non-volatile memory / EEPROM layout parsers) -- includes
# NVMEM_LAYOUT_ONIE_TLV, relevant for bare-metal networking switch
# hardware (Open Network Install Environment).
enable_by_prefix("NVMEM_")

# --- Previously-missing umbrellas for families that had been getting
# individually hardcoded instead: CPU_FREQ (governors/drivers),
# THERMAL (governors/drivers), HW_RANDOM (chip drivers), TCP_CONG_
# (congestion control algorithms).
enable_umbrella("CPU_FREQ", 2, label="CPU_FREQ")
enable_umbrella("THERMAL", 2, label="THERMAL")
enable_by_prefix("HW_RANDOM_")
enable_by_prefix("TCP_CONG_")

# ============================================================================
# Seventh batch: Ethernet driver leaf-bools, PHYLIB (proper umbrella walk
# this time -- unlocks ~50 vendor PHY chip drivers that were never
# individually touched), PSE/PoE, MCTP transports, MDIO, PLIP/PPPOE/
# PPTP/SLIP, WAN/HDLC subsystem, IEEE802154 device drivers.
# ============================================================================

# --- FDDI (Fiber Distributed Data Interface) -- separate umbrella,
# never touched.
enable_umbrella("FDDI", 2, label="FDDI")

# --- PHYLIB: was only ever set as a plain value (=m), never walked as a
# subtree -- this is almost certainly why the ~50-item vendor MDIO PHY
# chip driver list (BROADCOM_PHY, MARVELL_PHY, AT803X_PHY, DP83xxx_PHY,
# etc.) was never individually reached. Proper umbrella walk this time.
enable_umbrella("PHYLIB", 2, label="PHYLIB")

# --- PSE (Power Sourcing Equipment / PoE controller framework) --
# genuinely relevant for PoE-capable network switches, never touched.
enable_umbrella("PSE_CONTROLLER", 2, label="PSE_CONTROLLER")

# ============================================================================
# Batch from a pasted raw diff chunk (left=zabbly, right=ours). Grouped
# by area; almost all are core kernel/x86-platform options with no
# driver zoo, so direct explicit sets are the right tool throughout.
# ============================================================================


# --- Networking diagnostics / TLS offload

enable_umbrella("RIONET", 1, label="RIONET")
enable_umbrella("ARCNET", 1, label="ARCNET")

# --- I2C bus controller drivers: drivers/i2c/busses/Kconfig uses a plain
# `menu "I2C Hardware Bus support"` with NO controlling symbol -- same
# shape as MFD_/PINCTRL_/CRYPTO_DEV_ before. I2C's own subtree walk
# never reached any of these 65 symbols since they live in a separate
# ungated menu block. Name-prefix sweep is the right tool.
enable_by_prefix("I2C_")

# --- PTP hardware clocks (precision time sync) and PPS (pulse-per-second
# GPS/time-sync hardware) -- both real, both never touched.
enable_umbrella("PTP_1588_CLOCK", 2, label="PTP_1588_CLOCK")
# PTP_1588_CLOCK is NOT a menuconfig and has no children -- the individual
# clock drivers (OCP/IDTCM/INES/IDT82P33/FC3W/MOCK/KVM/VMCLOCK/VMW) are prefix
# siblings gated by `depends on PTP_1588_CLOCK`, so sweep them by name. The
# ARM/PPC/legacy-SoC ones (IXP46X/DTE/QORIQ/PCH) cap on x86.
enable_by_prefix("PTP_1588_CLOCK_")
enable_umbrella("PPS", 2, label="PPS")

# --- IP6_NF_NAT: the real prerequisite for IP6_NF_TARGET_MASQUERADE,
# never touched despite IP6_NF_IPTABLES itself being on.
# IP6_NF_IPTABLES (legacy ip6tables) was never enabled at all -- we only
# ever did IP_NF_IPTABLES (IPv4). This is the real prerequisite for
# IP6_NF_NAT / IP6_NF_TARGET_MASQUERADE.
enable_umbrella("IP6_NF_IPTABLES", 1, label="IP6_NF_IPTABLES")
enable_umbrella("IP6_NF_NAT", 1, label="IP6_NF_NAT")

# --- SCSI device handlers (multipath support for enterprise storage
#     arrays -- RDAC, EMC, ALUA, HP) -- genuinely server-relevant, not
#     just zabbly-parity, and a separate umbrella from SCSI_LOWLEVEL.
enable_umbrella("SCSI_DH", 2, label="SCSI_DH")

# --- MCTP (Management Component Transport Protocol) -- BMC/platform
#     management, ties directly into the IPMI work from platform.config.
enable_umbrella("MCTP", 2, label="MCTP")
# MCTP transport drivers (SERIAL/I2C/I3C/USB + MCTP_FLOWS) are prefix siblings
# gated by `depends on MCTP`, not menu children, so sweep them by name.
enable_by_prefix("MCTP_")
# QRTR (Qualcomm IPC router) transports SMD/TUN -- same prefix-sibling shape.
enable_by_prefix("QRTR_")

# --- Firmware loading framework core -- an important baseline that had
#     simply never been touched.
enable_umbrella("FW_LOADER", 2, label="FW_LOADER")

# --- Intel SoC PMIC drivers (Bay Trail/Cherry Trail/Merrifield) --
#     genuinely x86/Intel platform-relevant.
enable_umbrella("INTEL_SOC_PMIC", 2, label="INTEL_SOC_PMIC")

# PMIC_OPREGION: confirmed via real Kconfig source (drivers/acpi/Kconfig)
# to be a genuine menuconfig bool umbrella, with children each depending
# on a specific INTEL_SOC_PMIC_* variant -- must come AFTER
# INTEL_SOC_PMIC's own walk above, which is why setting it via the
# fragment alone kept failing (an ordering issue, not a removed value).
# XPOWER_PMIC_OPREGION's own prerequisites (MFD_AXP20X_I2C, IOSF_MBI) are
# already satisfied by this point -- MFD_AXP20X_I2C via the MFD_ prefix sweep
# near the top, IOSF_MBI via the x86 defconfig.
enable_umbrella("PMIC_OPREGION", 2, label="PMIC_OPREGION")

# --- OCFS2: cluster filesystem, real and never touched.
enable_umbrella("OCFS2_FS", 1, label="OCFS2_FS")

# --- Parallel port core support. This is the actual missing prerequisite
#     for PATA_PARPORT's children (PATA_PARPORT_ATEN, _BPCK, etc.) -- we
#     enabled PATA_PARPORT itself last round, but its individual adapter
#     modules also depend on PARPORT, which we'd never touched.
enable_umbrella("PARPORT", 1, label="PARPORT")

# --- Serial console, LEDs, RTC, PWM: all real menuconfig umbrellas, all
#     never touched -- same blind-spot pattern as GPIO/mm before them.
enable_umbrella("SERIAL_8250", 2, label="SERIAL_8250")
enable_umbrella("NEW_LEDS", 2, label="NEW_LEDS")
enable_umbrella("RTC_CLASS", 2, label="RTC_CLASS")
enable_umbrella("PWM", 2, label="PWM")

# --- USB device/peripheral mode. Separate top-level menuconfig from USB
#     (host-mode only) -- explains 143 of 144 missing USB_* symbols, which
#     were never even ATTEMPTED (not capped) before this, since only a
#     hand-picked few USB_GADGET children were ever set, via a flat
#     fragment, rather than the whole subtree being walked.
enable_umbrella("USB_GADGET", 1, label="USB_GADGET")

# --- CAN: same sibling-umbrella shape as ETHERNET/USB_NET_DRIVERS. CAN
#     (net/can/Kconfig) covers only the protocol layer (CAN_RAW, CAN_BCM,
#     CAN_GW). The actual vendor CAN controller/adapter drivers
#     (CAN_PEAK_USB, CAN_KVASER_USB, CAN_GS_USB, CAN_FLEXCAN, ...) live
#     under CAN_DEV, a SEPARATE menuconfig in drivers/net/Kconfig,
#     confirmed via Kconfig source -- never walked before now.
enable_umbrella("CAN_DEV", 1, label="CAN_DEV")

# --- NET_DSA: net/dsa/Kconfig's own NET_DSA umbrella only covers tagging
#     protocol drivers (NET_DSA_TAG_*), already reached. The vendor
#     switch-chip drivers (NET_DSA_REALTEK, NET_DSA_MICROCHIP_KSZ_COMMON,
#     mv88e6xxx, mt7530, ocelot, b53, ...) live in drivers/net/dsa/Kconfig
#     under a plain `menu` block (not menuconfig) with NO controlling
#     symbol -- same shape as MFD_/CRYPTO_DEV_ from much earlier, so
#     name-prefix filtering is the right tool, not another umbrella walk.
enable_by_prefix("NET_DSA_")

# --- PINCTRL: the base PINCTRL bool itself is promptless (select-only,
#     same as MFD_* -- confirmed via Kconfig source: "depends on: (none)"
#     with no prompt text), and its actual driver zoo sits under a plain
#     `menu "Pin controllers"` with no controlling symbol. Name-prefix
#     sweep is the right tool, same as MFD_/CRYPTO_DEV_/NET_DSA_ above --
#     and this doubles as the real fix for a chunk of the GPIO complaint
#     too, since on real x86 hardware, GPIO support for platforms like
#     Baytrail/Cherryview/Sunrisepoint/etc. is actually delivered through
#     these Intel pinctrl+GPIO combo drivers, not through drivers/gpio/
#     itself. Confirmed real via zabbly-config (PINCTRL_BAYTRAIL=y,
#     PINCTRL_CHERRYVIEW=y, PINCTRL_LYNXPOINT=m, and several more).
enable_by_prefix("PINCTRL_")

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

# BRIDGE_NF_EBTABLES_LEGACY: the old sockopt/eval-loop ebtables path,
# depends on NETFILTER_XTABLES_LEGACY (already established via the
# fragment) + BRIDGE_NF_EBTABLES (just above). Covers BRIDGE_EBT_BROUTE/
# T_FILTER/T_NAT as children.
enable_umbrella("BRIDGE_NF_EBTABLES_LEGACY", 1, label="BRIDGE_NF_EBTABLES_LEGACY")

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

# --- RDS (Reliable Datagram Sockets) -- ties to our INFINIBAND/RDMA work.
enable_umbrella("RDS", 1, label="RDS")
enable_exact(("RDS_DEBUG", 0))  # same DBG/DEBUG naming gap as above

# --- USB: turns out to be unusually fragmented -- Cadence (USB_CDNS_
#     SUPPORT) and ChipIdea are THIRD-PARTY sibling umbrellas (separate
#     from both USB and USB_GADGET), and even some USB_GADGET children
#     (USB_CONFIGFS_*) weren't reliably reached by that walk. Rather than
#     keep chasing individual umbrella names in a tree this fragmented, a
#     full prefix sweep catches everything regardless of which sibling
#     file it lives in -- same technique as MFD_/CRYPTO_DEV_/NET_DSA_/
#     PINCTRL_ above, just broader since USB's fragmentation is worse.
enable_by_prefix("USB_")

# --- CRYPTO: confirmed via diagnostics that the actual crypto/Kconfig
#     core (cipher algorithms, DRBG/RNG, JITTERENTROPY, CRYPTO_LIB_*) was
#     never touched at all -- we'd only ever swept CRYPTO_DEV_ (hardware
#     accelerators) much earlier. Broad "CRYPTO" prefix (no trailing
#     underscore) catches everything in one sweep -- CRYPTO_DEV_* and the
#     CRYPTO_LIB_* symbols over in lib/crypto/Kconfig included -- so the
#     separate CRYPTO_DEV_/CRYPTO_LIB_ sweeps that used to sit here and
#     further up are gone; measured redundant, diff unchanged.
enable_by_prefix("CRYPTO")

# --- PECI (Platform Environment Control Interface): a separate small bus
#     subsystem in drivers/peci/Kconfig, never touched. This is the real
#     blocker for SENSORS_PECI_CPUTEMP/SENSORS_PECI_DIMMTEMP -- the
#     existing HWMON walk already correctly attempts those two (confirmed
#     via diagnostics: they show up as "attempted", not "never attempted"),
#     they just needed this prerequisite satisfied. Also genuinely
#     relevant beyond zabbly-parity -- PECI is how real Xeon/EPYC server
#     platforms expose CPU package and DIMM temperature, worth carrying
#     into production too, not just this validation script.
enable_umbrella("PECI", 1, label="PECI")

# --- GPIO: a handful of drivers (GPIO_I8255 and three PMIC-companion
#     ones) were never reached by the GPIOLIB walk at all -- same
#     reachability-gap shape as USB. The PMIC ones will likely stay
#     capped regardless (same promptless-MFD wall as CHARGER/REGULATOR/
#     IIO/SENSORS), but cheap and consistent to sweep broadly anyway.
enable_by_prefix("GPIO_")

# --- SERIAL: SERIAL_8250 only covers one UART controller family --
#     drivers/tty/serial/Kconfig has a whole set of independently-gated
#     chip-specific UART drivers (SC16IS7XX, SCCNXP, etc.) as sibling
#     entries in the same file, not nested under SERIAL_8250 at all.
#     Confirmed via diagnostics: 13 of 16 missing SERIAL_* symbols were
#     never attempted before this.
enable_by_prefix("SERIAL_")

# --- FB: a real structural gap, not a new one -- FB has been in the
#     umbrella list since very early in this project, but confirmed via
#     diagnostics that 0 of its 76 missing children were ever attempted.
#     zabbly-config has both FB=y AND FB_CORE=y -- FB_CORE is a newer
#     symbol from a fbdev Kconfig restructuring our original FB walk never
#     accounted for, and the actual driver zoo now lives under a separate
#     `menu` block, not nested inside FB's own subtree (same "plain menu,
#     no controlling symbol" shape as MFD_/PINCTRL_ before it).
if "FB_CORE" in kconf.syms:
    kconf.syms["FB_CORE"].set_value(2)  # y
enable_by_prefix("FB_")

# A few FB_* items are genuinely x86-relevant (EFI/VESA firmware
# framebuffers) rather than the staging-adjacent FB_TFT hobbyist-display
# family -- explicit direct sets as a targeted follow-up.

# --- Backlight and LCD panel class devices: two more real, entirely
#     untouched umbrellas (drivers/video/backlight/Kconfig). Most of the
#     BACKLIGHT_* residual (88PM860X, AAT2870, ADP5520, DA903X, LP8788,
#     MAX8925, ...) is PMIC-companion chips -- same promptless-MFD wall
#     as CHARGER/REGULATOR/IIO/SENSORS, so expect those specific ones to
#     stay capped regardless.
enable_umbrella("BACKLIGHT_CLASS_DEVICE", 2, label="BACKLIGHT_CLASS_DEVICE")
enable_by_prefix("BACKLIGHT_")
enable_umbrella("LCD_CLASS_DEVICE", 1, label="LCD_CLASS_DEVICE")
enable_by_prefix("LCD_")

# ============================================================================
# Batch found via a broad "never attempted at all" scan across the WHOLE
# residual (not just a specific prefix someone asked about) -- 1253 of
# 1583 missing symbols turned out to fall in this category this round,
# confirming the FB_CORE lesson: worth periodically re-scanning broadly
# rather than only reacting to whichever prefix gets mentioned next.
# ============================================================================

# --- Modern filesystems, never touched at all (filesystems.config
#     apparently never covered these two).
enable_umbrella("EROFS_FS", 1, label="EROFS_FS")
enable_umbrella("F2FS_FS", 1, label="F2FS_FS")

# --- FPGA manager framework + Intel/Altera DFL (Device Feature List) --
#     genuinely relevant for real enterprise servers with FPGA
#     accelerator cards, not just zabbly-parity.
enable_umbrella("FPGA", 1, label="FPGA")
enable_umbrella("FPGA_DFL", 1, label="FPGA_DFL")

# --- Device DAX: direct-access mode for persistent memory / CXL memory
#     regions -- directly relevant given CXL_BUS is already enabled above.
#     Correction: DEV_DAX itself was still missing after the previous
#     attempt -- the real prerequisite is DAX (a separate core bool, not
#     DEV_DAX's own concern), confirmed via zabbly-config (CONFIG_DAX=y).
enable_umbrella("DEV_DAX", 1, label="DEV_DAX")

# --- Network teaming (alternative to bonding).
enable_umbrella("NET_TEAM", 1, label="NET_TEAM")

# --- UFS (Universal Flash Storage) host controller -- a separate
#     umbrella from SCSI_LOWLEVEL, explaining why it was never reached
#     despite that walk already covering the rest of SCSI.
enable_umbrella("SCSI_UFSHCD", 1, label="SCSI_UFSHCD")

# --- Intel Trace Hub: real x86 platform debug/tracing hardware.
enable_umbrella("INTEL_TH", 1, label="INTEL_TH")

# --- POWER_RESET / PCIE_DW: previously (wrongly) written off as
#     "ARM SoC-specific" and skipped. That was sloppy -- neither has an
#     actual architecture restriction in Kconfig; PCIE_DW_PLAT is the
#     generic platform wrapper around the DesignWare PCIe core, and
#     POWER_RESET_RESTART is a generic restart handler. zabbly-config
#     enabling both on an x86 build is direct proof they're not ARM-only.
#     (POWER_RESET_MT6323/ATC260X genuinely are PMIC-companion chips and
#     will likely stay capped via the usual promptless-MFD wall -- that's
#     fine, no harm in the umbrella walk attempting them anyway.)
enable_umbrella("POWER_RESET", 2, label="POWER_RESET")
enable_umbrella("PCIE_DW", 2, label="PCIE_DW")

# --- EXTCON: external connector detection (USB cable type, dock state,
#     headphone jack) -- never touched. Two of the six residual items
#     (EXTCON_INTEL_CHT_WC, EXTCON_INTEL_MRFLD) are genuinely x86/Intel
#     platform-relevant; the rest are PMIC-companion chips likely to hit
#     the usual promptless-MFD wall.
enable_umbrella("EXTCON", 2, label="EXTCON")

# CHARGER_* is NOT included here on purpose: confirmed via diagnostics
# that all of it is already correctly attempted via the POWER_SUPPLY
# walk, and every remaining item is the same promptless-MFD-parent wall
# as REGULATOR/IIO/SENSORS (TPS65090, 88PM860X, TWL4030/6030, ...) --
# no umbrella or prefix sweep can fix that; it's a structural limit of
# what direct set_value() can force, not a reachability gap.

# --- CRYPTO: the core software crypto API (crypto/Kconfig) -- a proper
#     menuconfig umbrella. The same sweep also covers drivers/crypto/'s
#     CRYPTO_DEV_* hardware accelerators and lib/crypto's CRYPTO_LIB_*,
#     since both start with "CRYPTO". Explains
#     CRYPTO_BLOWFISH_COMMON, CRYPTO_CAST_COMMON, CRYPTO_DRBG_MENU (and
#     its nested children CTR/HASH/HMAC), CRYPTO_FCRYPT, CRYPTO_PCBC, etc.
enable_umbrella("CRYPTO", 1, label="CRYPTO")

# --- USB residual: drivers/usb/Kconfig sources the dual-role/OTG
#     controller Kconfigs (cdns3, dwc3, dwc2, chipidea, musb, mtu3,
#     fotg210, isp1760) UNCONDITIONALLY at the top level -- siblings to
#     both the "if USB...endif" block AND drivers/usb/gadget/Kconfig, not
#     nested inside either. Their own entry-point symbols were never
#     reached by either the USB or USB_GADGET walk, even though each has
#     a proper nested subtree once reached directly.
enable_umbrella("USB_CDNS3", 1, label="USB_CDNS3")
enable_umbrella("USB_DWC3", 1, label="USB_DWC3")
enable_umbrella("USB_DWC2", 2, label="USB_DWC2")  # confirmed =y in zabbly
enable_umbrella("USB_CHIPIDEA", 1, label="USB_CHIPIDEA")

# ============================================================================
# Driver-family umbrellas/prefix sweeps -- each of these is a self-contained
# driver zoo (a menuconfig gate with a uniform =m/=y child family, or a flat
# sibling family under a plain menu) that the structural walker can cover in
# full, replacing what used to be a per-symbol block of data. Ordering: all of their dependencies (PCI, WAN,
# NET_DSA, NETDEVICES, TTY, ...) are already satisfied by this point.
# ============================================================================
enable_umbrella("NTB", 1, label="NTB")            # Non-Transparent Bridge + NTB_* clients
enable_umbrella("BCMA", 1, label="BCMA")          # Broadcom SoC bus
enable_umbrella("SSB", 1, label="SSB")            # Sonics Silicon Backplane bus
enable_umbrella("RAPIDIO", 2, label="RAPIDIO")    # RapidIO interconnect + switches (=y: zabbly builds the bus in)
enable_umbrella("XILLYBUS", 1, label="XILLYBUS")  # generic FPGA interface bus
enable_umbrella("HDLC", 1, label="HDLC")          # generic HDLC + per-protocol drivers
enable_umbrella("B53", 1, label="B53")            # Broadcom BCM53xx DSA switch family
enable_umbrella("TARGET_CORE", 1, label="TARGET_CORE")  # LIO SCSI/iSCSI/FC target + TCM_* backstores
enable_umbrella("CHROME_PLATFORMS", 2, label="CHROME_PLATFORMS")  # ChromeOS platform: CROS_*/CHROMEOS_*
enable_umbrella("SLIP", 1, label="SLIP")          # SLIP net driver (parent for the SLIP_* options below)
enable_by_prefix("SERIO_")                        # input serio port drivers (siblings, no gate)
enable_by_prefix("SLIP_")                         # SLIP line-discipline compression options
enable_by_prefix("MLXREG_")                       # Mellanox register-access platform drivers
enable_by_prefix("ADT7316")                       # ADT7316/7516 sensor (core + I2C/SPI variants)
enable_by_prefix("ZL3073X")                       # Microchip ZL3073x clock/timing (core + I2C/SPI)
enable_by_prefix("RAVE_SP_")                      # RAVE supervisory-processor MFD drivers
enable_by_prefix("MOXA_")                         # Moxa Intellio/Smartio multiport serial
enable_by_prefix("MIPI_I3C")                      # MIPI I3C host-controller interface
enable_by_prefix("SURFACE_")                      # MS Surface platform drivers (SURFACE_PLATFORMS gate is default-y)

# Virtualization guest/host driver menus -- all three are menuconfig gates
# (VIRTIO_MENU/VHOST_MENU default y, VDPA is tristate) whose child driver
# families zabbly enables essentially wholesale. VDPA's vendor drivers
# (MLX5_VDPA_NET, IFCVF, ...) need their parent NIC cores, already on via the
# ETHERNET walk far above. VIRTIO_MENU has two children zabbly leaves off
# (VIRTIO_HARDEN_NOTIFICATION hardening toggle, VIRTIO_RTC_ARM arch-specific);
# they can't be pattern-denied, so they are suppressed as data in
# config_slices/virtualization.config instead.
enable_umbrella("VHOST_MENU", 2, label="VHOST_MENU")   # vhost host-side accel: VHOST_NET/SCSI/VSOCK/VDPA
enable_umbrella("VDPA", 1, label="VDPA")               # vDPA bus + sim/vendor drivers
enable_umbrella("VIRTIO_MENU", 2, label="VIRTIO_MENU") # virtio guest drivers: PCI/MMIO/BALLOON/MEM/INPUT/RTC/...
enable_umbrella("INTEL_MEI", 1, label="INTEL_MEI")     # Intel Management Engine Interface + ME/TXE/GSC/CSC/VSC/HDCP/PXP

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

enable_umbrella("UIO", 1, label="UIO")                 # userspace I/O drivers (FSL/PPC children cap on x86)
enable_umbrella("COUNTER", 1, label="COUNTER")         # counter subsystem: 104_QUAD_8/INTEL_QEP/INTERRUPT_CNT (SoC drivers cap on x86)
enable_umbrella("MEDIA_CEC_SUPPORT", 2, label="MEDIA_CEC_SUPPORT")  # HDMI-CEC adapters: GPIO/CH7322/CROS_EC/NXP/SECO (SoC drivers cap on x86)
enable_umbrella("PCI_ENDPOINT", 2, label="PCI_ENDPOINT")  # PCI endpoint framework: PCI_EPF_MHI/NTB/VNTB + gates PCIE_DW_PLAT_EP / NVME_TARGET_PCI_EPF
enable_umbrella("KGDB", 2, label="KGDB")               # KGDB/KDB debugger: serial-console/kdb/keyboard/blocklist (KGDB_TESTS denied)
enable_umbrella("VIRT_DRIVERS", 2, label="VIRT_DRIVERS")  # virt guest drivers: VMGENID/VBOXGUEST/NITRO/SEV_GUEST/TDX_GUEST_DRIVER (ARM/FSL cap); also cascades the TSM_* selects
enable_umbrella("USB4", 1, label="USB4")               # USB4/Thunderbolt bus (DMA_TEST denied, DEBUGFS_WRITE/MARGINING denied as "(DANGEROUS)" distro opt-outs)
enable_by_prefix("USB4_")                              # USB4_NET lives under drivers/net, not inside the `if USB4` block, so the walk can't reach it

# --- More single-gate families. Each of these was showing up in the diff as
# one "wrong value" line plus 3-7 "missing from ours" lines: the missing ones
# aren't really missing, they are simply INVISIBLE while the gate is off, so
# they never make it into the generated file at all. Turn the gate on and the
# whole family appears, with the deny-list keeping the *_DEBUG sub-options off
# exactly as zabbly has them.
#
# Where the sub-options are prefix siblings (`depends on X`) rather than nested
# menu children, the umbrella walk can't reach them and a prefix sweep follows.
enable_umbrella("MOST", 1, label="MOST")               # MOST automotive bus core (drivers/most)
enable_umbrella("MOST_COMPONENTS", 1, label="MOST_COMPONENTS")  # ...and its component drivers, which live in a separate menuconfig under drivers/staging/most: CDEV/NET/SND/VIDEO/DIM2/USB_HDM
enable_umbrella("EVM", 2, label="EVM")                 # Extended Verification Module (integrity xattr protection)
enable_by_prefix("EVM_")                               # ATTR_FSUUID/ADD_XATTRS/EXTRA_SMACK_XATTRS are `depends on EVM` siblings
enable_exact(("HARDLOCKUP_DETECTOR", 2))               # NMI hard-lockup detector; the _PERF/_COUNTS_HRTIMER/_ARCH/_BUDDY sub-symbols are promptless and resolve themselves
enable_umbrella("MEMSTICK", 1, label="MEMSTICK")       # Sony Memory Stick: TIFM_MS/JMICRON_38X/R592/REALTEK_USB
enable_umbrella("JFS_FS", 1, label="JFS_FS")
enable_by_prefix("JFS_")                               # POSIX_ACL/SECURITY/STATISTICS are `depends on JFS_FS` siblings
enable_umbrella("AFS_FS", 1, label="AFS_FS")
enable_by_prefix("AFS_")                               # AFS_FSCACHE
enable_umbrella("PANEL", 1, label="PANEL")             # parallel-port LCD panel; selects CHARLCD
enable_by_prefix("PANEL_")
enable_by_prefix("CHARLCD")
enable_umbrella("FW_CFG_SYSFS", 1, label="FW_CFG_SYSFS")  # QEMU fw_cfg sysfs interface

# --- Menuconfig gates that were already at the right value but had never been
# WALKED, so their entire driver zoo sat at default-off. enable_umbrella on an
# already-correct gate is not a no-op: the walk is the point.
enable_umbrella("MISC_FILESYSTEMS", 2, label="MISC_FILESYSTEMS")  # ADFS/AFFS/BEFS/BFS/CODA/EFS/GFS2/HFS(+PLUS)/HPFS/MINIX/NILFS2/OMFS/ORANGEFS/QNX4/QNX6/UFS/VBOXSF/VXFS/ECRYPT
enable_umbrella("DMADEVICES", 2, label="DMADEVICES")   # dmaengine drivers: IOAT/IDMA64/PTDMA/QDMA/DW(+AXI)/PLX/SWITCHTEC/ALTERA/XILINX (SoC ones cap on x86)
enable_umbrella("AUXDISPLAY", 2, label="AUXDISPLAY")   # character LCD / LED display drivers: HD44780/HT16K33/KS0108/LCD2S/MAX6959/IMG_ASCII_LCD/SEG_LED_GPIO
enable_umbrella("MULTIPLEXER", 2, label="MULTIPLEXER") # MUX_ADG792A/ADGS1408/GPIO/MMIO
enable_umbrella("PM_DEVFREQ", 2, label="PM_DEVFREQ")   # devfreq governors: SIMPLE_ONDEMAND/PERFORMANCE/POWERSAVE/USERSPACE/PASSIVE
enable_umbrella("RPMSG", 1, label="RPMSG")             # remote-processor messaging: CHAR/CTRL/TTY/QCOM_GLINK
enable_umbrella("REMOTEPROC", 2, label="REMOTEPROC")
enable_umbrella("INTERCONNECT", 2, label="INTERCONNECT")
enable_umbrella("MEMORY", 2, label="MEMORY")           # memory-controller drivers
enable_umbrella("HTE", 2, label="HTE")                 # hardware timestamping engine
enable_umbrella("TEE", 1, label="TEE")                 # Trusted Execution Environment (AMDTEE on x86)
enable_umbrella("FWCTL", 1, label="FWCTL")             # firmware control: FWCTL_BNXT/MLX5/PDS
enable_umbrella("MHI_BUS", 1, label="MHI_BUS")         # Qualcomm MHI bus; also the missing prerequisite for PCI_EPF_MHI
enable_by_prefix("EEPROM_")                            # I2C/SPI EEPROM drivers sit under a plain `menu`, no gate to walk from
enable_umbrella("DRM_ACCEL", 2, label="DRM_ACCEL")     # compute-accelerator drivers: AMDXDNA/HABANALABS/IVPU/QAIC
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
enable_exact(("MHI_BUS_EP", 1), ("NTB_NETDEV", 1))     # single tristates with no menu or prefix to hang off
enable_by_prefix("MUX_")                               # drivers/mux: MULTIPLEXER is a plain config, so its chip drivers aren't nested under it
enable_by_prefix("RPMSG_")                             # same shape for RPMSG: CHAR/CTRL/TTY/QCOM_GLINK_RPM are `depends on RPMSG` siblings

# ============================================================================
# Batch added after a systematic sweep prompted by real gaps found by eye
# in the diff -- everything below is verified directly against
# zabbly-config's actual values (grep misc/zabbly-config), not
# guessed. tri_value key: 0=n, 1=m, 2=y.
# ============================================================================

# --- net/smc/Kconfig: SMC (Shared Memory Communications) -- RDMA-accelerated
#     sockets, notably relevant given INFINIBAND is already enabled above.
enable_umbrella("SMC", 1, label="SMC")

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

# --- net/dsa/Kconfig: embedded switch-chip drivers. No production case
#     (essentially never present on x86 servers) -- validation-only.
enable_umbrella("NET_DSA", 1, label="NET_DSA")

# --- net/sched/Kconfig: NET_SCHED is the real umbrella covering BOTH
#     NET_CLS_* (classifiers) and NET_ACT_* (actions) -- NET_SCH_* queueing
#     disciplines were already hand-picked in networking.config, but
#     classifiers/actions live in the same file and were never walked.
#     NET_CLS_ACT specifically gates action visibility and needs setting
#     explicitly (it's a bool with no children of its own).
enable_umbrella("NET_SCHED", 2, label="NET_SCHED")

# --- net/batman-adv/Kconfig: mesh networking protocol
enable_umbrella("BATMAN_ADV", 1, label="BATMAN_ADV")

# --- drivers/net/can/Kconfig + net/can/Kconfig
enable_umbrella("CAN", 1, label="CAN")

# --- drivers/gnss/Kconfig
enable_umbrella("GNSS", 1, label="GNSS")

# --- drivers/ata/pata_parport/Kconfig, nested under ATA -- should already
#     be reachable via the ATA walk added last round, but PATA_PARPORT
#     itself still showed up missing, so setting it explicitly as a
#     belt-and-suspenders in case ordering/visibility timing matters.
enable_umbrella("PATA_PARPORT", 1, label="PATA_PARPORT")

# --- drivers/md/Kconfig: device-mapper (dm-crypt, dm-thin, dm-raid,
#     dm-cache, dm-verity, dm-integrity, dm-multipath, ...). Confirmed via
#     zabbly-config this is its own thing worth walking explicitly, not
#     fully covered by the MD walk from several rounds back.
enable_umbrella("BLK_DEV_DM", 2, label="BLK_DEV_DM")

# --- net/9p/Kconfig (transport) + fs/9p/Kconfig (filesystem) -- two
#     separate small umbrellas, both needed for Plan 9 protocol support.
enable_umbrella("NET_9P", 1, label="NET_9P")
enable_umbrella("9P_FS", 1, label="9P_FS")

# --- drivers/net/ppp/Kconfig
enable_umbrella("PPP", 2, label="PPP")

# --- drivers/gpio/Kconfig: deferred three times earlier in this project
#     for lack of a clean umbrella -- resolved now. GPIOLIB is real,
#     confirmed via zabbly-config (CONFIG_GPIOLIB=y).
enable_umbrella("GPIOLIB", 2, label="GPIOLIB")

#
# Enable IPv6 (protocol suite: tunnels, extension headers, routing, etc.)
#
enable_umbrella("IPV6", 2, label="IPV6")

#
# Enable IPVS (IP Virtual Server / Linux load balancer) as modules
#
enable_umbrella("IP_VS", 1, label="IP_VS")

# IP_VS_PROTO_AH_ESP needs IP_VS itself already on -- moved here from
# much earlier in the file, where it was being attempted 444 lines
# before IP_VS was actually turned on.

#
# Enable L2TP as modules
#
enable_umbrella("L2TP", 1, label="L2TP")

#
# Enable all SATA/PATA controller drivers as modules. Also genuinely
# useful for production, not just zabbly-parity -- most non-NVMe server
# storage still goes through libata.
#
enable_umbrella("ATA", 2, label="ATA")

#
# Enable CXL (Compute Express Link) support. Also genuinely useful for
# production -- CXL.mem/CXL.cache memory expansion and tiering are real
# enterprise server concerns, not just a zabbly-parity item.
#
enable_umbrella("CXL_BUS", 1, label="CXL_BUS")

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

#
# AF_XDP sockets -- same reasoning as zswap: flat, direct assignment, and
# genuinely useful outside this validation exercise (high-performance
# packet processing on a hypervisor host).
#
if "XDP_SOCKETS" in kconf.syms:
    kconf.syms["XDP_SOCKETS"].set_value(2)  # y
if "XDP_SOCKETS_DIAG" in kconf.syms:
    kconf.syms["XDP_SOCKETS_DIAG"].set_value(1)  # m

# ============================================================================
# EVERYTHING BELOW THIS LINE IS VALIDATION-ONLY.
#
# These subsystems (sound, graphics, media, wireless desktop/laptop hardware
# support, etc.) are exactly what the rest of this project exists to leave
# OUT of the production IncusOS kernel. They're enabled here purely to
# reproduce zabbly-config as a way of proving the genconfig.py machinery
# itself (env setup, Kconfiglib fidelity, the subtree-walk technique) is
# trustworthy. Do not copy this block into a production config.
# ============================================================================

# Umbrellas verified directly against Kconfig source (menuconfig, correct
# bool/tristate type):
_VALIDATION_ONLY_TRISTATE_UMBRELLAS = [
    "MEDIA_SUPPORT",
    "USB",
    "FB",
    "MTD",
    "IIO",
    # "I2C" removed from this generic list -- it needs to stay =y
    # specifically (not =m) because several MFD parent chips depend on
    # I2C=y strictly, and this generic loop's "set to m if tristate"
    # logic was silently overriding the explicit I2C=y fix set earlier
    # (right before the MFD sweep), retroactively breaking MFD_MAX8925
    # and friends. Confirmed via checkpoint tracing: I2C was correct
    # right after the MFD sweep, then wrong by the time this loop had run.
    "SPI",
    "NFC",
    "MMC",
    "HID",
    "W1",
    "INPUT",
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

# MEDIA_SUPPORT alone isn't enough -- VIDEO_DEV and DVB_CORE (the actual
# cores everything else cascades from) only default on if one of several
# bool category switches is set, and those default OFF whenever
# MEDIA_SUPPORT_FILTER is on (which is itself the default unless EXPERT).
# Our subtree walker deliberately skips bool, so it never touches this --
# disabling the filter directly bypasses the whole mechanism.
if "MEDIA_SUPPORT_FILTER" in kconf.syms:
    kconf.syms["MEDIA_SUPPORT_FILTER"].set_value(2)  # y -- CORRECTED: zabbly
    # keeps the filter ON and enables each category individually, rather than
    # disabling the filter entirely. Both approaches unlock the same media
    # drivers practically, but only this one is byte-identical to zabbly.
    kconf.syms["MEDIA_CAMERA_SUPPORT"].set_value(2)
    kconf.syms["MEDIA_ANALOG_TV_SUPPORT"].set_value(2)
    kconf.syms["MEDIA_DIGITAL_TV_SUPPORT"].set_value(2)
    kconf.syms["MEDIA_RADIO_SUPPORT"].set_value(2)
    kconf.syms["MEDIA_SDR_SUPPORT"].set_value(2)

# Confirmed via cross-referencing capped_symbols.txt against the real
# missing-vs-zabbly diff: zabbly-config has CONFIG_OF=y, which is why a
# large tranche of DRM panel/bridge-chip drivers ("depends on OF") are
# visible there but not for us. OF is architecture-independent
# infrastructure, not something that requires devicetree hardware to be
# meaningfully present -- safe to enable for parity purposes.
if "OF" in kconf.syms:
    kconf.syms["OF"].set_value(2)  # y

# ASoC (SND_SOC) machine drivers for Intel platforms (Haswell/Broadwell/
# Bay Trail/Cherry Trail/etc.) sit behind a two-level bool gate chain --
# same MEDIA_SUPPORT_FILTER-shaped problem, confirmed via Kconfig source.
# The general "bool with children" rule in enable_subtree should now catch
# these automatically once SOUND's walk reaches them, but setting the
# known chain explicitly here too as a belt-and-suspenders in case
# ordering within the walk matters.
for name in ("SND_SOC_INTEL_SST_TOPLEVEL", "SND_SOC_SOF_INTEL_TOPLEVEL", "SND_SOC_INTEL_MACH"):
    if name in kconf.syms:
        kconf.syms[name].set_value(2)  # y

# SoundWire: a separate audio-codec interconnect bus subsystem, not nested
# under SOUND at all -- explains the SND_SOC_*_SDW cluster in the residual.
# Confirmed real (not noise) via zabbly-config having SOUNDWIRE=m.
enable_umbrella("SOUNDWIRE", 1, label="SOUNDWIRE")

# Several remaining SND_SOC_INTEL_*_MACH drivers (Bay Trail/Cherry Trail
# era) additionally depend on this Intel platform I2C/SPI/UART controller
# support. Confirmed real via zabbly-config having X86_INTEL_LPSS=y.
if "X86_INTEL_LPSS" in kconf.syms:
    kconf.syms["X86_INTEL_LPSS"].set_value(2)  # y

# Same shape again: USB-attached media devices (webcams, USB DVB dongles)
# sit behind MEDIA_USB_SUPPORT, a bool gate under MEDIA_SUPPORT's subtree.
if "MEDIA_USB_SUPPORT" in kconf.syms:
    kconf.syms["MEDIA_USB_SUPPORT"].set_value(2)  # y

# Older pre-v2 USB DVB tuner framework core -- nested under
# MEDIA_USB_SUPPORT (per its Kconfig structure), so this MUST come after
# the line above. It was previously positioned much earlier in this file,
# before MEDIA_USB_SUPPORT existed, which silently capped the entire
# DVB_USB subtree for a whole round -- an ordering bug, not a real
# Kconfig-dependency mystery.
enable_umbrella("DVB_USB", 1, label="DVB_USB")

# VIDEO_CX88 needed an explicit re-attempt here (after MEDIA_USB_SUPPORT
# and RC_CORE are both established) since MEDIA_SUPPORT's own earlier
# walk ran before RC_CORE was set.
if "VIDEO_CX88" in kconf.syms:
    kconf.syms["VIDEO_CX88"].set_value(1)  # m

# USB network adapters (USB_NET_CDCETHER, USB_NET_SMSC95XX, ...) live in
# drivers/net/usb/Kconfig, sourced from drivers/net/Kconfig -- a sibling
# menu, not nested inside USB's own subtree, so walking USB alone never
# reaches them despite USB_NET_DRIVERS's own default correctly tracking
# USB's value.
enable_umbrella("USB_NET_DRIVERS", 1, label="USB_NET_DRIVERS")

# REGULATOR and X86_PLATFORM_DEVICES are bool, not tristate -- same pattern,
# separated out so the type isn't hidden in the list above.
for name in ("REGULATOR", "X86_PLATFORM_DEVICES"):
    enable_umbrella(name, 2)   # y -- these are bool umbrellas

# XEN: makes no sense on a KVM-only host. Included ONLY for byte-parity
# against zabbly-config, which is a general-purpose desktop/server kernel
# that supports running as a Xen guest/host too.
enable_umbrella("XEN", 2, label="XEN")

# COMEDI: lives in drivers/staging. Reverses the staging-exclusion stance
# from earlier in this project -- included ONLY for byte-parity, never in
# production.
enable_umbrella("COMEDI", 1, label="COMEDI")

# ============================================================================
# END VALIDATION-ONLY BLOCK
# ============================================================================


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
    "drivers",
)


# VIRTIO_VFIO_PCI (variant VFIO PCI driver for virtio devices) + its
# VIRTIO_VFIO_PCI_ADMIN_LEGACY child. Placed here, AFTER the config_slices
# load, because it depends on VFIO -- which virtualization.config only turns
# on a few lines above; running it up in the driver-family block would find
# VFIO still off and get silently capped.
enable_umbrella("VIRTIO_VFIO_PCI", 1, label="VIRTIO_VFIO_PCI")

# STM (System Trace Module) trace subsystem + its protocol/source drivers.
# Also placed after the config_slices load: STM_SOURCE_FTRACE depends on
# TRACING, which only comes on once tracing.config's FUNCTION_TRACER selects
# it a few lines above.
enable_umbrella("STM", 1, label="STM")

#kconf.load_config("kernel/configs/kvm_guest.config", replace=False)

# VALIDATION-ONLY override: netfilter.config deliberately disables
# NETFILTER_XTABLES_LEGACY (dropping legacy iptables/ip6tables tooling
# while keeping NETFILTER_XTABLES + NFT_COMPAT for translated-rule
# compatibility) -- that's the real production policy decision from
# earlier in this project, and it's correct for production. But since this
# script's job is byte-parity with zabbly-config specifically, re-enable
# it here, AFTER the fragment load, so it isn't immediately overridden
# back to n. IP_NF_IPTABLES_LEGACY / IP6_NF_IPTABLES_LEGACY default to m
# conditionally on this, so flipping the one switch should take both
# with it -- no need to set them individually.
if "NETFILTER_XTABLES_LEGACY" in kconf.syms:
    kconf.syms["NETFILTER_XTABLES_LEGACY"].set_value(2)  # y

# Legacy/foreign partition table format support (block/partitions/Kconfig).
# Structurally different from everything else in this file: PARTITION_ADVANCED
# doesn't wrap its children in an "if PARTITION_ADVANCED ... endif" block --
# each format instead uses `bool "..." if PARTITION_ADVANCED` (a conditional
# PROMPT on the individual symbol), so PARTITION_ADVANCED has no node.list
# children at all. Neither the subtree walker nor the general bool-gate rule
# could ever reach these regardless of the deny-list -- needs direct
# handling. Also a small, fixed, well-bounded list (not a vendor zoo), so an
# explicit list is the right tool here, not more walker machinery.
# Mirrors zabbly-config's specific choices exactly -- it does NOT enable
# everything either (ACORN_PARTITION and OF_PARTITION are off there too).
if "PARTITION_ADVANCED" in kconf.syms:
    kconf.syms["PARTITION_ADVANCED"].set_value(2)  # y
    for name in (
        "AIX_PARTITION", "AMIGA_PARTITION", "ATARI_PARTITION", "BSD_DISKLABEL",
        "KARMA_PARTITION", "LDM_PARTITION", "MAC_PARTITION", "MINIX_SUBPARTITION",
        "OSF_PARTITION", "SGI_PARTITION", "SOLARIS_X86_PARTITION", "SUN_PARTITION",
        "SYSV68_PARTITION", "ULTRIX_PARTITION", "UNIXWARE_DISKLABEL",
    ):
        if name in kconf.syms:
            kconf.syms[name].set_value(2)  # y

finish()
