#!/usr/bin/env python3

import os
import sys

FLAVOR = os.path.basename(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from genconfig import (
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
