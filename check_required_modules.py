#!/usr/bin/env python3
"""Map kernel module names to the Kconfig symbols that build them, and check
that a flavor's mandatory modules are actually enabled in a generated config.

The hard part is going from a module name (`dm_crypt`) to the Kconfig symbol
that builds it (`CONFIG_DM_CRYPT`). Kconfig itself never mentions module or
object-file names -- that link lives only in the Kbuild Makefiles:

    obj-$(CONFIG_DM_CRYPT) += dm-crypt.o        ->  dm_crypt   <- CONFIG_DM_CRYPT
    obj-$(CONFIG_VXLAN)    += vxlan.o           ->  vxlan      <- CONFIG_VXLAN

So this script walks every Makefile/Kbuild under a kernel tree, harvests
those `obj-$(CONFIG_x) += name.o` lines into a  module -> {symbols}  map, and
either dumps that map whole or uses it to classify each name in a modules
list as:

    ok        mapped to a symbol that is =y or =m in the config
    MISSING   mapped to a symbol that is =n / absent
    UNMAPPED  no `obj-$(CONFIG_x)` line builds a matching object

The heuristic is deliberately simple (one regex, plus '-'<->'_' folding). It
covers the large majority of in-tree modules; things it cannot see are
out-of-tree modules (zfs, spl), modules whose name is computed in the
Makefile with $(foreach)/$(patsubst), and plain `obj-m += x.o` with no
CONFIG. Those surface as UNMAPPED rather than being silently treated as fine.

Usage:
    ./check_required_modules.py dump-map [--kernel-tree PATH]
    ./check_required_modules.py validate --modules-list PATH --config PATH [--kernel-tree PATH]

dump-map prints the *complete* module -> CONFIG map found in the kernel tree
-- every module Kbuild can build, not just ones from any particular list --
and takes no list or config: what the tree can build does not depend on
either. validate is the opposite: --modules-list and --config are both
required, with no flavor-based (or any other) defaulting -- pass exactly the
files you mean to check.

Env (same as genconfig.sh; falls back to ./.env, and expands ~):
    KERNEL_TREE_PATH   kernel source tree to scan (overridden by --kernel-tree)

Exit status (validate): 0 if every required module is ok, 1 otherwise
(MISSING, or UNMAPPED unless --allow-unmapped, or a usage/IO problem).
"""
import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# obj-$(CONFIG_FOO) += a.o b.o dir/       (continuation lines already joined)
# Also accepts ${CONFIG_FOO} and := ; the RHS is tokenised afterwards.
_OBJ_RE = re.compile(
    r"^\s*obj-\$[({]CONFIG_(?P<sym>[A-Za-z0-9_]+)[)}]\s*[:+]?=\s*(?P<rhs>.*\S)\s*$"
)

# Directories with Makefiles that never build kernel modules we care about;
# pruning them avoids bogus matches (e.g. tools/ has its own obj- rules).
_PRUNE_DIRS = {".git", "Documentation", "samples", "tools", "scripts", "usr"}


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


def build_module_map(kernel_tree):
    if not os.path.isdir(kernel_tree):
        sys.exit(f"error: kernel tree is not a directory: {kernel_tree}")
    if not os.path.isfile(os.path.join(kernel_tree, "Makefile")):
        sys.exit(f"error: no top-level Makefile under {kernel_tree} -- not a kernel tree?")

    mod_to_syms = {}
    makefiles = 0
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
                if not m:
                    continue
                sym = m.group("sym")
                for tok in m.group("rhs").split():
                    if not tok.endswith(".o"):
                        continue  # a subdir (dir/) or a $(var) -- skip
                    stem = tok[:-2]
                    if "$" in stem or "(" in stem:
                        continue  # computed name, can't resolve statically
                    mod = norm(os.path.basename(stem))
                    if not mod:
                        continue
                    mod_to_syms.setdefault(mod, set()).add(sym)
    if not mod_to_syms:
        sys.exit(f"error: scanned {makefiles} Makefiles under {kernel_tree} "
                 "but found no obj-$(CONFIG_*) lines -- wrong path?")
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


def cmd_dump_map(args):
    kernel_tree = resolve_kernel_tree(args)
    mod_map = build_module_map(kernel_tree)
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
    mod_map = build_module_map(kernel_tree)
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
        print("\n-- MISSING (mapped symbol is =n / absent) " + "-" * 30)
        for mod, syms in missing:
            states = ", ".join(f"CONFIG_{s}={config.get(s, 'absent')}" for s in syms)
            print(f"  {mod:<32} {states}")

    if unmapped:
        print("\n-- UNMAPPED (no obj-$(CONFIG_*) line matched) " + "-" * 26)
        for mod in unmapped:
            print(f"  {mod}")

    failed = bool(missing) or (bool(unmapped) and not args.allow_unmapped)
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="action", required=True)

    p_map = sub.add_parser(
        "dump-map",
        help="print the complete module -> CONFIG map found in the kernel tree "
             "(no list, no config, no flavor)")
    p_map.add_argument("--kernel-tree",
                        help="kernel source tree (default: $KERNEL_TREE_PATH, then ./.env)")
    p_map.set_defaults(func=cmd_dump_map)

    p_val = sub.add_parser(
        "validate",
        help="check that every module in --modules-list is =y/=m in --config")
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

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
