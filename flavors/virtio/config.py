#!/usr/bin/env python3

import os
import sys

FLAVOR = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from genconfig import (
    enable_exact,
    enable_umbrella,
    finish,
    load_slices,
    start,
)

kconf = start(defconfig="kernel/configs/kvm_guest.config")

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
    "misc",
)

finish()
