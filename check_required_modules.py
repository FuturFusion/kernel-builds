#!/usr/bin/env python3
"""Map kernel module names to the Kconfig symbols that build them, and check
that a flavor's mandatory modules are actually enabled in a generated config.

The hard part is going from a module name (`dm_crypt`) to the Kconfig symbol
that builds it (`CONFIG_DM_CRYPT`). Kconfig itself never mentions module or
object-file names -- that link lives only in the Kbuild Makefiles:

    obj-$(CONFIG_DM_CRYPT) += dm-crypt.o        ->  dm_crypt   <- CONFIG_DM_CRYPT
    obj-$(CONFIG_VXLAN)    += vxlan.o           ->  vxlan      <- CONFIG_VXLAN

So this script walks every Makefile/Kbuild under a kernel tree, harvesting
those `obj-$(CONFIG_x) += name.o` lines into a module -> {symbols} map --
each side genuinely many-to-many:

  - one symbol, several modules: obj-$(CONFIG_X) += a.o b.o is two
    independent modules sharing one gate, e.g. CONFIG_ISDN -> isdn1, isdn2.
  - one module, several symbols: a shared object with no CONFIG_ of its own,
    listed under every driver that uses it (e.g. libahci.o under
    CONFIG_SATA_AHCI, CONFIG_SATA_AHCI_PLATFORM, ...). Its real build state
    is derived from all of them (see derive_state()): built-in if any user
    is =y, else a module if any user is =m.

That raw map still overclaims one thing: a symbol only builds a *module* if
it can actually be =m, i.e. it's `tristate` in Kconfig, not `bool` -- a
bool-gated obj-$(CONFIG_X) += a.o b.o c.o (object files that always link
into vmlinux together) is not three loadable modules, and treating it as one
is exactly how CONFIG_XFRM (bool) used to show up mapped to
xfrm_state/xfrm_input/xfrm_output as if they were separate modules. So every
(module, symbol) pair is dropped unless the symbol is declared `tristate` in
the kernel's own Kconfig (parsed via Kconfiglib, same as genconfig.py).

What survives is used three ways:

    dump-map         prints the whole map
    validate         classifies each name in a modules list as:
                        ok        some mapped symbol is =y or =m
                        MISSING   every mapped symbol is =n / absent
                        UNMAPPED  no tristate obj-$(CONFIG_x) line builds it
    gen-module-list  for every module, derives its build state from its
                     symbols' config values, as modname,config,value CSV

Beyond bool-vs-tristate, the object-file heuristic itself is deliberately
simple (one regex, plus '-'<->'_' folding); composite modules (`foo-y :=
a.o b.o`, `foo-$(CONFIG_X) += c.o`) are handled for free -- the constituents
never match the `obj-` pattern, so only `foo` itself, from its own
`obj-$(CONFIG_FOO) += foo.o` line, ever enters the map. One `$(foreach)`/
`$(eval)` idiom is special-cased (`_TARGET_RE`, see drivers/platform/x86/
intel and lenovo); a handful of cases neither regex can reach at all are
listed by hand in `_KNOWN_EXTRA`. Beyond those, it still cannot see
out-of-tree modules (zfs, spl), other computed Makefile names, or plain
`obj-m += x.o` with no CONFIG at all.

Usage:
    ./check_required_modules.py dump-map --arch ARCH [--kernel-tree PATH]
    ./check_required_modules.py validate --arch ARCH --modules-list PATH --config PATH [--kernel-tree PATH]
    ./check_required_modules.py gen-module-list --arch ARCH --config PATH [--output PATH] [--kernel-tree PATH]

--arch is required for all three actions (no default) -- it's a line from
./arches (amd64, arm64), and selects which Kconfig tree (arch/<x>/Kconfig)
gets parsed for symbol types, same mapping genconfig.sh uses. dump-map takes
no list or config: what the tree can build does not depend on either.
validate and gen-module-list both take --config, required, with no
flavor-based (or any other) defaulting -- pass exactly the file you mean to
check.

Env (same as genconfig.sh; falls back to ./.env, and expands ~):
    KERNEL_TREE_PATH   kernel source tree to scan (overridden by --kernel-tree)

Exit status: validate returns 0 if every required module is ok, 1 otherwise
(MISSING, or UNMAPPED unless --allow-unmapped, or a usage/IO problem). The
other two actions return 0 unless they hit a usage/IO problem.
"""
import argparse
import contextlib
import csv
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# obj-$(CONFIG_FOO) += a.o b.o dir/       (continuation lines already joined)
# Also accepts ${CONFIG_FOO} and := ; the RHS is tokenised afterwards.
_OBJ_RE = re.compile(
    r"^\s*obj-\$[({]CONFIG_(?P<sym>[A-Za-z0-9_]+)[)}]\s*[:+]?=\s*(?P<rhs>.*\S)\s*$"
)

# <prefix>-target-$(CONFIG_FOO) += bar.o : an auto-prefixing idiom (e.g.
# drivers/platform/x86/intel, drivers/platform/x86/lenovo). A $(foreach)
# $(eval) further down turns each entry into
#   <prefix>-<bar>-y := bar.o ; obj-$(CONFIG_FOO) += <prefix>-<bar>.o
# which $(eval) makes invisible to a static regex, so this matches the
# pre-expansion form directly and predicts its result instead.
_TARGET_RE = re.compile(
    r"^\s*(?P<prefix>[A-Za-z0-9_]+)-target-\$[({]CONFIG_(?P<sym>[A-Za-z0-9_]+)[)}]"
    r"\s*[:+]?=\s*(?P<rhs>.*\S)\s*$"
)

# Directories with Makefiles that never build kernel modules we care about;
# pruning them avoids bogus matches (e.g. tools/ has its own obj- rules).
_PRUNE_DIRS = {".git", "Documentation", "samples", "tools", "scripts", "usr"}

# module -> symbol pairs no static Makefile read can derive, kept here by
# hand. nfnetlink.o is declared bool-gated inside a composite in
# net/netfilter/Makefile (netfilter-$(CONFIG_NETFILTER_NETLINK) += nfnetlink.o),
# yet still ends up as its own loadable nfnetlink.ko -- verified against
# lsmod, not something the tristate rule below can see.
_KNOWN_EXTRA = {
    "nfnetlink": "NETFILTER_NETLINK",
}

# arch -> (kernel ARCH, SRCARCH), same mapping as genconfig.sh's case
# statement. Kept in sync by hand; there is no single source both scripts
# could read a Python dict and a shell case statement from.
_ARCH_MAP = {
    "amd64": ("x86_64", "x86"),
    "arm64": ("arm64", "arm64"),
}


def norm(name):
    """Fold the module-name spelling: the .ko basename uses '-', module names
    (and CONFIG symbols) use '_'. Compare everything with '_'."""
    return name.replace("-", "_")


def load_env_kernel_tree():
    val = os.environ.get("KERNEL_TREE_PATH")
    if not val:
        env_path = os.path.join(SCRIPT_DIR, ".env")
        try:
            with open(env_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("KERNEL_TREE_PATH="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except FileNotFoundError:
            pass
    if not val:
        sys.exit(
            "error: KERNEL_TREE_PATH is not set and ./.env has none.\n"
            "       Point it at a kernel source tree (same var genconfig.sh uses),\n"
            "       or pass --kernel-tree explicitly."
        )
    return os.path.abspath(os.path.expanduser(val))


def resolve_kernel_tree(args):
    return (os.path.abspath(os.path.expanduser(args.kernel_tree))
            if args.kernel_tree else load_env_kernel_tree())


def resolve_arch(arch):
    if arch not in _ARCH_MAP:
        sys.exit(f"error: unknown arch '{arch}' -- expected one of: "
                 f"{' '.join(sorted(_ARCH_MAP))}")
    return _ARCH_MAP[arch]


def load_kconfig(kernel_tree, arch):
    """Parse the kernel tree's Kconfig for the given arch and return the
    Kconfig object, so callers can read sym.orig_type. Mirrors the
    environment kconf-run.sh sets up for genconfig.py, minus anything that
    only matters for evaluating *values* (this only needs symbol types)."""
    kernel_arch, srcarch = resolve_arch(arch)

    kconfiglib_dir = os.path.join(SCRIPT_DIR, "yocto-kernel-tools", "Kconfiglib")
    if kconfiglib_dir not in sys.path:
        sys.path.insert(0, kconfiglib_dir)
    try:
        import kconfiglib
    except ImportError:
        sys.exit("error: can't import kconfiglib -- run "
                 "'git submodule update --init --recursive'")

    try:
        kernelversion = subprocess.run(
            ["make", "-s", "-C", kernel_tree, f"ARCH={kernel_arch}", "kernelversion"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"error: 'make kernelversion' failed in {kernel_tree}: {e}")

    cc = os.environ.get("CC", "gcc")
    try:
        cc_version_text = subprocess.run(
            [cc, "--version"], capture_output=True, text=True, check=True,
        ).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        cc_version_text = ""

    os.environ["srctree"] = kernel_tree
    os.environ["ARCH"] = kernel_arch
    os.environ["SRCARCH"] = srcarch
    os.environ["KERNELVERSION"] = kernelversion
    os.environ.setdefault("CC", cc)
    os.environ.setdefault("LD", "ld")
    os.environ["CC_VERSION_TEXT"] = cc_version_text
    os.environ.setdefault("PAHOLE", "pahole")
    # Same temporary override as kconf-run.sh: build hosts without pahole
    # would otherwise force the whole BTF-dependent cluster off.
    os.environ.setdefault("PAHOLE_VERSION", "130")

    try:
        return kconfiglib.Kconfig(os.path.join(kernel_tree, "Kconfig"))
    except kconfiglib.KconfigError as e:
        sys.exit(f"error: failed to parse Kconfig under {kernel_tree}: {e}")


def tristate_symbols(kconf):
    import kconfiglib
    return {name for name, sym in kconf.syms.items()
            if sym.orig_type == kconfiglib.TRISTATE}


def build_module_map(kernel_tree, tristate_syms):
    if not os.path.isdir(kernel_tree):
        sys.exit(f"error: kernel tree is not a directory: {kernel_tree}")
    if not os.path.isfile(os.path.join(kernel_tree, "Makefile")):
        sys.exit(f"error: no top-level Makefile under {kernel_tree} -- not a kernel tree?")

    pairs = set()
    makefiles = 0
    non_tristate = 0
    for root, dirs, files in os.walk(kernel_tree):
        if root == kernel_tree:
            dirs[:] = [d for d in dirs if d not in _PRUNE_DIRS]
        for fname in files:
            if fname not in ("Makefile", "Kbuild") and not fname.endswith(".Makefile"):
                continue
            makefiles += 1
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            text = text.replace("\\\n", " ")  # join continuations
            for line in text.splitlines():
                m = _OBJ_RE.match(line)
                prefix = None
                if not m:
                    m = _TARGET_RE.match(line)
                    if not m:
                        continue
                    prefix = m.group("prefix")
                sym = m.group("sym")
                for tok in m.group("rhs").split():
                    if not tok.endswith(".o"):
                        continue  # a subdir (dir/) or a $(var) -- skip
                    stem = tok[:-2]
                    if "$" in stem or "(" in stem:
                        continue  # computed name, can't resolve statically
                    base = os.path.basename(stem)
                    if not base:
                        continue
                    mod = norm(f"{prefix}-{base}" if prefix else base)
                    if sym not in tristate_syms:
                        non_tristate += 1
                        continue
                    pairs.add((mod, sym))
    pairs.update(_KNOWN_EXTRA.items())
    if not pairs:
        sys.exit(f"error: scanned {makefiles} Makefiles under {kernel_tree} "
                 "but found no obj-$(CONFIG_*) line gated by a tristate symbol "
                 "-- wrong path, or wrong --arch?")

    # Both directions are legitimate: one symbol can build several modules
    # (obj-$(CONFIG_X) += a.o b.o), and one module can be listed under several
    # symbols (a shared object like libahci.o, built by any of its users).
    mod_to_syms = {}
    for mod, sym in pairs:
        mod_to_syms.setdefault(mod, set()).add(sym)
    if non_tristate:
        print(f"note: dropped {non_tristate} non-tristate obj-$(CONFIG_*) matches",
              file=sys.stderr)
    return mod_to_syms


def read_required_list(path):
    mods = []
    seen = set()
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key = norm(line)
            if key not in seen:
                seen.add(key)
                mods.append(line)
    if not mods:
        sys.exit(f"error: {path} lists no modules")
    return mods


def read_config(path):
    values = {}
    set_re = re.compile(r"^CONFIG_([A-Za-z0-9_]+)=(.+)$")
    notset_re = re.compile(r"^# CONFIG_([A-Za-z0-9_]+) is not set$")
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = set_re.match(line)
            if m:
                values[m.group(1)] = m.group(2)
                continue
            m = notset_re.match(line)
            if m:
                values[m.group(1)] = "n"
    return values


def derive_state(syms, config):
    """A module's real build state when several symbols can build it (a
    shared object): =y from any user wins outright, else =m from any user."""
    for value in ("y", "m"):
        hit = min((s for s in syms if config.get(s) == value), default=None)
        if hit:
            return hit, value
    return None


def cmd_dump_map(args):
    kernel_tree = resolve_kernel_tree(args)
    kconf = load_kconfig(kernel_tree, args.arch)
    mod_map = build_module_map(kernel_tree, tristate_symbols(kconf))
    for mod in sorted(mod_map):
        syms = " ".join("CONFIG_" + s for s in sorted(mod_map[mod]))
        print(f"{mod}\t{syms}")
    print(f"# {len(mod_map)} modules harvested from {kernel_tree}", file=sys.stderr)
    return 0


def cmd_validate(args):
    kernel_tree = resolve_kernel_tree(args)
    if not os.path.isfile(args.modules_list):
        sys.exit(f"error: no modules list at {args.modules_list}")
    if not os.path.isfile(args.config):
        sys.exit(f"error: no config at {args.config}")

    required = read_required_list(args.modules_list)
    kconf = load_kconfig(kernel_tree, args.arch)
    mod_map = build_module_map(kernel_tree, tristate_symbols(kconf))
    config = read_config(args.config)

    def lookup(mod):
        return sorted(mod_map.get(norm(mod), ()))

    ok, missing, unmapped = [], [], []
    for mod in required:
        syms = lookup(mod)
        if not syms:
            unmapped.append(mod)
            continue
        enabled = [s for s in syms if config.get(s) in ("y", "m")]
        if enabled:
            ok.append((mod, enabled))
        else:
            missing.append((mod, syms))

    print(f"kernel tree : {kernel_tree}")
    print(f"modules list: {args.modules_list}  ({len(required)} modules)")
    print(f"config      : {args.config}")
    print(f"map         : {len(mod_map)} modules harvested from Makefiles")
    print()
    print(f"ok       {len(ok)}")
    print(f"MISSING  {len(missing)}")
    print(f"UNMAPPED {len(unmapped)}")

    if missing:
        print("\n-- MISSING (every mapped symbol is =n / absent) " + "-" * 30)
        for mod, syms in missing:
            states = ", ".join(f"CONFIG_{s}={config.get(s, 'absent')}" for s in syms)
            print(f"  {mod:<32} {states}")

    if unmapped:
        print("\n-- UNMAPPED (no obj-$(CONFIG_*) line matched) " + "-" * 26)
        for mod in unmapped:
            print(f"  {mod}")

    failed = bool(missing) or (bool(unmapped) and not args.allow_unmapped)
    return 1 if failed else 0


def cmd_gen_module_list(args):
    kernel_tree = resolve_kernel_tree(args)
    if not os.path.isfile(args.config):
        sys.exit(f"error: no config at {args.config}")

    kconf = load_kconfig(kernel_tree, args.arch)
    mod_map = build_module_map(kernel_tree, tristate_symbols(kconf))
    config = read_config(args.config)

    rows = []
    for mod, syms in mod_map.items():
        state = derive_state(syms, config)
        if state:
            sym, value = state
            rows.append((mod, f"CONFIG_{sym}", value))
    rows.sort()

    with contextlib.ExitStack() as stack:
        out = (stack.enter_context(open(args.output, "w", newline=""))
               if args.output else sys.stdout)
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["modname", "config", "value"])
        writer.writerows(rows)

    print(f"{len(rows)} rows written from {args.config}", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="action", required=True)

    arch_help = ("target architecture, required (no default) -- a line from "
                 "./arches (amd64, arm64); selects which Kconfig tree is "
                 "parsed for symbol types")

    p_map = sub.add_parser(
        "dump-map",
        help="print the complete module -> CONFIG map found in the kernel tree "
             "(no list, no config, no flavor)")
    p_map.add_argument("--arch", required=True, help=arch_help)
    p_map.add_argument("--kernel-tree",
                        help="kernel source tree (default: $KERNEL_TREE_PATH, then ./.env)")
    p_map.set_defaults(func=cmd_dump_map)

    p_val = sub.add_parser(
        "validate",
        help="check that every module in --modules-list is =y/=m in --config")
    p_val.add_argument("--arch", required=True, help=arch_help)
    p_val.add_argument("--modules-list", required=True,
                        help="path to a modules list, e.g. flavors/server/must_have_modules.list "
                             "(required -- no flavor-based default)")
    p_val.add_argument("--config", required=True,
                        help="path to the generated config to check "
                             "(required -- no flavor-based default)")
    p_val.add_argument("--kernel-tree",
                        help="kernel source tree (default: $KERNEL_TREE_PATH, then ./.env)")
    p_val.add_argument("--allow-unmapped", action="store_true",
                        help="do not fail the run on UNMAPPED modules (still reported)")
    p_val.set_defaults(func=cmd_validate)

    p_gen = sub.add_parser(
        "gen-module-list",
        help="from --config's =y/=m symbols, emit a modname,config,value CSV of the modules they build")
    p_gen.add_argument("--arch", required=True, help=arch_help)
    p_gen.add_argument("--config", required=True,
                        help="path to the generated config to read "
                             "(required -- no flavor-based default)")
    p_gen.add_argument("--output",
                        help="write the CSV here instead of stdout")
    p_gen.add_argument("--kernel-tree",
                        help="kernel source tree (default: $KERNEL_TREE_PATH, then ./.env)")
    p_gen.set_defaults(func=cmd_gen_module_list)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
