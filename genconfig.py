"""Kconfig tree-walking library shared by every kernel flavor.

This module holds the generic machinery only -- the Kconfiglib compatibility
shim, the deny-list, the four structural enable_* helpers, and the
start()/load_slices()/finish() lifecycle. It sets no symbols of its own and is
not runnable: importing it produces no config.

A *flavor* is a self-contained directory holding a driver script that imports
these helpers and states the policy for one kernel, plus its data fragments:

    flavors/generic/config.py  +  flavors/generic/config_slices/*.config

Adding a flavor means adding another such directory; nothing here needs to
change. Run one with ./genconfig.sh [flavor].

The three structural shapes a flavor has to deal with, and the tool for each:

    menuconfig X + nested children   -> enable_umbrella(name, value)
    flat driver zoo, shared prefix   -> enable_by_prefix(prefix)
    plain `menu "..."`, no gate      -> enable_menu(title)
    a lone symbol with no family     -> enable_exact((name, value), ...)

enable_umbrella both SETS and WALKS; enable_exact only sets. That distinction
is load-bearing -- see the STAGING/ACCESSIBILITY note in flavors/generic/config.py.
"""
import os
import kconfiglib

__all__ = [
    "here",
    "start", "load_slices", "finish",
    "enable_subtree", "enable_umbrella", "enable_exact", "enable_menu",
    "enable_by_prefix",
]


# Anchor to the script's own directory, NOT the process's cwd -- kconf-run.sh
# cd's into the kernel tree before invoking us, so any bare relative path
# here would resolve against the kernel source, not this script's location.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def here(*parts):
    """Resolve a path relative to this script's directory."""
    return os.path.join(SCRIPT_DIR, *parts)


# ============================================================================
# Kconfiglib compatibility shim: int/hex symbols with no value.
#
# The C implementation seeds every symbol's value before evaluating it
# (scripts/kconfig/symbol.c, sym_calc_value):
#
#       case S_INT:    newval.val = "0";    break;
#       case S_HEX:    newval.val = "0x0";  break;
#       case S_STRING: newval.val = "";     break;
#
# Kconfiglib instead starts int/hex at "" (see Symbol.str_value, `val = ""`),
# so an int symbol that is declared but never given a value reads back as ""
# rather than "0". That only matters inside comparisons -- _sym_to_num("")
# raises ValueError, Kconfiglib falls back to a *lexicographic* compare, and
# `SYM = 0` comes out false where the real kconfig says true.
#
# It bites exactly here, on x86:
#
#   mm/Kconfig:
#       config ARCH_FORCE_MAX_ORDER
#               int                      <- bare declaration: no prompt,
#                                           no default; only the non-x86
#                                           arches ever give it a value
#       config PAGE_BLOCK_MAX_ORDER
#               int "Page Block Order Upper Limit"
#               range   1 10 if ARCH_FORCE_MAX_ORDER  = 0
#               default 10   if ARCH_FORCE_MAX_ORDER  = 0
#               range   1 ARCH_FORCE_MAX_ORDER if ARCH_FORCE_MAX_ORDER != 0
#               default   ARCH_FORCE_MAX_ORDER if ARCH_FORCE_MAX_ORDER != 0
#
# and the Kconfig comment directly above it states the intent outright:
# "When ARCH_FORCE_MAX_ORDER is not defined, the default page block order is
# MAX_PAGE_ORDER (10)". With the real kconfig, `= 0` matches and you get 10 --
# which is what zabbly-config has. With Kconfiglib, `!= 0` matches instead,
# giving `range 1 ""`, and PAGE_BLOCK_MAX_ORDER clamps to 1.
#
# Restoring the C seed value fixes it at the root. Nothing else in the output
# moves: all 110 int/hex symbols that read back as "" here are invisible
# (their dependencies are off), so none of them is written to the config --
# the shim only changes how comparisons evaluate.
# ============================================================================
_ORIG_STR_VALUE = kconfiglib.Symbol.str_value


def _str_value_c_compat(self):
    val = _ORIG_STR_VALUE.fget(self)
    if val == "":
        if self.orig_type is kconfiglib.INT:
            return "0"
        if self.orig_type is kconfiglib.HEX:
            return "0x0"
    return val


kconfiglib.Symbol.str_value = property(_str_value_c_compat)




_diagnostics = {"attempted": 0, "stuck": 0, "silently_capped": []}

# Bool symbols matching any of these (case-insensitive) are never
# auto-enabled by the "bool gate with children" rule below, even if
# structurally they look like a category switch -- e.g. DRM_LEGACY ("Enable
# legacy drivers (DANGEROUS)") has nested children just like a normal
# category gate, but is explicitly opt-in for a reason.
# "ERROR_INJECTION" (and "FAULT_INJECT") are deliberate fault-injection
# test scaffolding -- same class as DEBUG/TEST. Denying them lets driver-family
# sweeps (e.g. the SURFACE_ sweep below) skip a stray *_ERROR_INJECTION child
# without listing it by hand. The genuinely-wanted *_ERROR_INJECTION symbols
# in zabbly-config are all enabled from data (flavors/*/config_slices/), which
# loads via load_config() and bypasses this deny-list, so they are unaffected.
# NB the pattern is "FAULT_INJECT", not "FAULT_INJECTION": these are exact
# substring matches, so the longer spelling silently missed the *_INJECTOR
# variant (I2C_GPIO_FAULT_INJECTOR). All four FAULT_INJECT* symbols are off in
# zabbly-config, so the wider match costs nothing.
#
# "WERROR" is a compile-time build-strictness flag (-Werror) that subsystems
# expose for their own developers (DRM_WERROR, DRM_I915_WERROR, DRM_XE_WERROR,
# DRM_AMDGPU_WERROR, OBJTOOL_WERROR). A distro never wants a warning to fail
# the build, so denying the whole family generically replaces four data lines.
#
# "LEGACY" was tried here and REMOVED after measuring it against zabbly-config:
# a distro kernel actually ships the legacy-hardware drivers (PATA_LEGACY,
# MEGARAID_LEGACY, IIO_CROS_EC_ACCEL_LEGACY, USB_F_UAC1_LEGACY, IWLEGACY_DEBUGFS)
# as modules -- they cost nothing until modprobed. Blocking them produced 8
# "missing from ours" diffs and prevented zero unwanted ones.
#
# "TEST" was measured the same way and KEPT: allowing it wins 13 wanted symbols
# but drags in 36 unwanted ones (the SELFTEST/FIPS/*_TESTS suites -- BT_SELFTEST,
# CRYPTO_SELFTESTS, DRM_I915_SELFTEST, KGDB_TESTS, MTD_TESTS, NL80211_TESTMODE).
# The handful of test modules zabbly does ship are set from data instead.
# "DEBUG" likewise stays: those are compile-time verbose/assertion builds.
#
# "DISABLE" is a polarity guard rather than a danger flag. Every enable_*
# helper means "switch this feature on", so setting a symbol whose NAME means
# "turn something off" (EFI_DISABLE_PCI_DMA, EFI_DISABLE_RUNTIME,
# EFI_VARS_PSTORE_DEFAULT_DISABLE, USB_OTG_DISABLE_EXTERNAL_HUB) does the exact
# opposite of what the sweep intends -- the EFI menu walk was switching off
# EFI runtime services. Denying the family is safe in both directions because
# the deny-list means "don't set", NOT "force off": the `default y` members
# (NFS_DISABLE_UDP_SUPPORT, MTD_SPI_NOR_SWP_DISABLE_ON_VOLATILE) keep their y,
# and the promptless X86_DISABLED_FEATURE_* are auto-computed and were never
# reachable by a sweep to begin with.
#
_DANGEROUS_BOOL_PATTERNS = ("DANGEROUS", "BROKEN", "EXPERIMENTAL", "DEBUG",
                            "TEST", "WERROR", "OBSOLETE", "DISABLE",
                            "ERROR_INJECTION", "FAULT_INJECT")

def _is_denied(name):
    """Centralized deny-list check, used by both enable_subtree and
    enable_by_prefix. Refined after finding a real regression: a blanket
    "DEBUG" pattern match blocks legitimate, wanted "_DEBUGFS" runtime
    introspection interfaces (L2TP_DEBUGFS, BT_DEBUGFS, CFG80211_DEBUGFS,
    MAC80211_DEBUGFS -- all confirmed =y/m in zabbly-config) along with
    genuinely-unwanted generic "_DEBUG" compile-time verbose/assertion
    flags. Those are different in kind: a debugfs interface is a runtime
    admin/introspection feature, not a dangerous compile-time debug
    build; only the latter should be excluded.

    The carve-out is anchored to the END of the name ("*_DEBUGFS"), which is
    how the "expose this subsystem under debugfs" switches are all spelled.
    Names where DEBUGFS appears mid-word introduce a *sub-option of* the
    debugfs interface (USB4_DEBUGFS_WRITE, USB4_DEBUGFS_MARGINING -- both
    prompted "(DANGEROUS)" and both off in zabbly-config), which is the
    dangerous-knob class the deny-list exists for.

    (A curated _WEAK_CIPHER_NAMES list used to live here to keep obsolete
    ciphers -- ANUBIS/KHAZAD/SEED/TEA/ARC4 -- from being swept in. It's gone:
    those all depend on CRYPTO_USER_API_ENABLE_OBSOLETE, which crypto.config
    now sets =n, making them invisible so the sweep can't reach them anyway.)"""
    upper = name.upper()
    for p in _DANGEROUS_BOOL_PATTERNS:
        if p not in upper:
            continue
        if p == "DEBUG" and upper.endswith("DEBUGFS"):
            continue  # allow debugfs interfaces specifically
        return True
    return False


# NOTE (measured, do not "fix"): the enable_* helpers deliberately OVERWRITE
# each other -- last writer wins. A monotonic "never lower an already-set
# value" rule looks obviously right (a sweep means "at least switch this on")
# and was tried here; it regressed the diff by 22-27 symbols either way it was
# applied. Broad prefix sweeps intentionally downgrade tristate drivers that an
# earlier umbrella had switched on wholesale to =y, and zabbly-config agrees
# with the downgrade far more often than not. Ordering is load-bearing.

def enable_subtree(node, label=None):
    while node:
        if isinstance(node.item, kconfiglib.Symbol):
            sym = node.item
            attempt = None
            if sym.orig_type == kconfiglib.TRISTATE:
                if not _is_denied(sym.name):
                    attempt = 1  # m -- only the driver itself
            elif sym.orig_type == kconfiglib.BOOL:
                # Previously only touched bool symbols WITH nested
                # children (category gates like MEDIA_SUPPORT_FILTER).
                # That silently skipped every leaf bool with no children
                # of its own -- which turned out to include genuine
                # feature toggles, not just debug flags (e.g.
                # IP_VS_PROTO_TCP/UDP: plain "yes I want this protocol"
                # bools, no sub-options, confirmed still wrong vs
                # zabbly-config despite IP_VS's own walk running). The
                # deny-list is the actual safety mechanism here, not
                # "does it have children" -- so touch every bool,
                # gate or leaf alike, and let the deny-list do its job.
                if not _is_denied(sym.name):
                    attempt = 2  # y

            if attempt is not None:
                sym.set_value(attempt)
                # Kconfiglib gives NO warning when a set_value() call is
                # silently capped by an unmet dependency (unlike
                # load_config(), which does warn on this) -- so the only
                # way to know is to check the actual resulting value
                # ourselves. Skip promptless symbols: those are internal
                # glue/library symbols only ever meant to be turned on via
                # select from elsewhere, so them staying at 0 is expected,
                # not a problem.
                has_prompt = any(n.prompt for n in sym.nodes)
                if has_prompt:
                    _diagnostics["attempted"] += 1
                    if sym.tri_value == attempt:
                        _diagnostics["stuck"] += 1
                    else:
                        _diagnostics["silently_capped"].append(
                            (label or "?", sym.name, sym.tri_value)
                        )
        if node.list:
            enable_subtree(node.list, label=label)
        node = node.next


def _track(sym, attempt, label):
    """Shared diagnostic-tracking helper: did this specific set_value()
    call actually stick? Used by every enable_* helper now, closing the
    blind spot found this round -- enable_umbrella was checking whether
    a symbol's CHILDREN stuck (via enable_subtree) but never checked its
    own top-level assignment, and enable_exact never checked anything at
    all. Both looked identical to 'never attempted' in cross-reference
    output even when they were attempted and silently failed."""
    has_prompt = any(n.prompt for n in sym.nodes)
    if not has_prompt:
        return
    _diagnostics["attempted"] += 1
    if sym.tri_value == attempt:
        _diagnostics["stuck"] += 1
    else:
        _diagnostics["silently_capped"].append((label, sym.name, sym.tri_value))


def enable_umbrella(name, value, label=None):
    """Set a known umbrella symbol to a value confirmed against
    zabbly-config, and walk its subtree if it has one. No-ops quietly if
    the symbol doesn't exist in this kernel tree (version skew)."""
    if name not in kconf.syms:
        print(f"note: umbrella {name} not found in this kernel tree -- skipped")
        return
    sym = kconf.syms[name]
    sym.set_value(value)
    _track(sym, value, label or name)
    if sym.nodes and sym.nodes[0].list:
        enable_subtree(sym.nodes[0].list, label=label or name)


def enable_exact(*names_and_values):
    """Set a small, fixed list of symbols to specific values, confirmed
    against zabbly-config. For subsystems with no meaningful driver zoo,
    where a subtree walk would be overkill -- same reasoning as
    virtualization.config being a flat fragment instead of a script."""
    for name, value in names_and_values:
        if name in kconf.syms:
            sym = kconf.syms[name]
            sym.set_value(value)
            _track(sym, value, "enable_exact")


def enable_menu(title, label=None):
    """Walk a plain `menu "..."` block by its title.

    The third structural shape in Kconfig, and until now the one we had no
    tool for. enable_umbrella() needs a `menuconfig` symbol to hang off;
    enable_by_prefix() needs the drivers to share a name prefix. A plain
    `menu` has neither -- there is no symbol to set and the contents are
    deliberately unrelated to each other. drivers/misc/Kconfig is the
    canonical example: `menu "Misc devices"` holds ~25 completely unrelated
    drivers (SGI_GRU, HP_ILO, IBM_ASM, PHANTOM, DS1682, OPEN_DICE, RPMB,
    ISL29003, ...) that share nothing but the menu they are printed under.

    Matching on the menu title is the only handle Kconfig gives us. Titles
    are stable across releases (they are user-visible UI text), and a
    missing title is a quiet no-op rather than an error, same as
    enable_umbrella's version-skew behaviour."""
    found = 0
    for node in kconf.node_iter():
        if node.item is kconfiglib.MENU and node.prompt and node.prompt[0] == title:
            found += 1
            if node.list:
                enable_subtree(node.list, label=label or title)
    if not found:
        print(f"note: menu {title!r} not found in this kernel tree -- skipped")


def enable_by_prefix(prefix):
    """For subsystems with no controlling umbrella symbol (MFD, hardware
    crypto devices, PINCTRL vendor drivers, ...) -- the driver options sit
    under a plain `menu` block, not a `menuconfig`-gated one, so there's
    nothing to set_value() on and walk from. Name-prefix filtering across
    the whole symbol table is the same technique used for NFT_*/MFD_*/
    NET_DSA_* earlier. Handles both bool and tristate, since some of
    these families (e.g. PINCTRL_*) mix both types."""
    for sym in kconf.unique_defined_syms:
        if not sym.name.startswith(prefix):
            continue
        if _is_denied(sym.name):
            continue
        attempt = None
        if sym.orig_type == kconfiglib.TRISTATE:
            attempt = 1  # m
        elif sym.orig_type == kconfiglib.BOOL:
            attempt = 2  # y
        if attempt is None:
            continue
        sym.set_value(attempt)
        has_prompt = any(n.prompt for n in sym.nodes)
        if has_prompt:
            _diagnostics["attempted"] += 1
            if sym.tri_value == attempt:
                _diagnostics["stuck"] += 1
            else:
                _diagnostics["silently_capped"].append((prefix.rstrip("_"), sym.name, sym.tri_value))



# ============================================================================
# Flavor lifecycle: start() -> policy calls -> load_slices() -> finish().
# ============================================================================

# The one Kconfig object a flavor script configures. start() fills this in;
# every helper above reads it. A flavor is one process building one kernel, so
# there is exactly one of these -- threading it through several hundred call
# sites would buy nothing.
kconf = None


def start(defconfig="arch/x86/configs/x86_64_defconfig"):
    """Open the kernel tree's Kconfig and seed it with an arch defconfig.

    Returns the Kconfig object for the flavor's own direct use (kconf.syms[...]
    for the handful of cases none of the enable_* helpers fit)."""
    global kconf
    kconf = kconfiglib.standard_kconfig()
    # This path genuinely lives inside the kernel tree, so a plain relative
    # path (resolved against cwd, which is $KERNEL_SRC after kconf-run.sh's
    # cd) is correct as-is -- don't route it through here().
    kconf.load_config(defconfig)
    return kconf


def load_slices(flavor, *names):
    """Load flavors/<flavor>/config_slices/<name>.config, in the order given.

    The order is spelled out at the call site rather than globbed on purpose:
    fragments deliberately overwrite each other (last writer wins), so a
    directory listing would put a load-bearing sequence at the mercy of
    alphabetical order.

    Fragments live under this repository, so resolve via here() rather than a
    bare relative path -- cwd is the kernel tree by the time we run."""
    for name in names:
        kconf.load_config(
            here("flavors", flavor, "config_slices", name + ".config"),
            replace=False)


def finish():
    """Print the walk diagnostics, surface real Kconfiglib warnings, and write
    the config out. The last thing a flavor script does."""
    # kconf.warnings does NOT catch silently-capped set_value() calls (only
    # load_config() overrides and promptless-symbol assignments) -- confirmed
    # by checking a real run's log: DRM_AMDGPU/SND_HDA_INTEL-style symbols we
    # attempted to enable via enable_subtree() produced zero warnings despite
    # not taking effect. This is the actual diagnostic: did each attempted
    # assignment (excluding promptless glue symbols, which are expected to
    # no-op) really stick?
    print(f"\nenable_subtree diagnostics: {_diagnostics['stuck']}/{_diagnostics['attempted']} "
          f"attempted assignments (tristate drivers + bool category gates, "
          f"both with a real prompt) actually stuck.")
    if _diagnostics["silently_capped"]:
        from collections import Counter
        by_label = Counter(l for l, _, _ in _diagnostics["silently_capped"])
        print(f"{len(_diagnostics['silently_capped'])} silently capped by an unmet "
              f"dependency, grouped by umbrella:")
        for label, count in by_label.most_common():
            print(f"  {label}: {count}")

        # NOTE: a large fraction of these are EXPECTED, not bugs -- e.g. most of
        # ETHERNET's capped list is drivers for ISA/Zorro/SPARC/m68k/VME/PowerPC
        # hardware that can't exist on x86_64 at all, which zabbly-config
        # (also x86_64) doesn't have enabled either. Printing only a sample here
        # was misleading last round -- write the FULL list to a file instead, so
        # it can be cross-referenced against the actual missing-vs-zabbly diff
        # (via cross_reference.py) to separate real gaps from arch-irrelevant
        # noise, rather than eyeballing a truncated sample.
        capped_path = here("output/capped_symbols.txt")
        with open(capped_path, "w") as f:
            for label, name, val in _diagnostics["silently_capped"]:
                f.write(f"{label}\tCONFIG_{name}\t{val}\n")
        print(f"full list written to {capped_path} -- cross-reference against "
              f"the missing-vs-zabbly diff with cross_reference.py before "
              f"treating any of this as a real problem")

    # Kconfiglib's own warnings are still worth surfacing for the two things
    # they DO catch: fragment files setting the same symbol twice (a real
    # ordering/overlap bug in a flavor's config_slices/ worth knowing about), and
    # genuine Kconfig-level oddities unrelated to our script.
    _real_warnings = [w for w in kconf.warnings if "no prompt" not in w]
    if _real_warnings:
        print(f"\n{len(_real_warnings)} other kconfiglib warnings (excluding the "
              f"expected 'no prompt' glue-symbol noise):")
        for w in _real_warnings:
            print(f"  {w}")

    kconf.write_config()
