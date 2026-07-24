#!/usr/bin/env bash
#
# kconf-run.sh -- run any Kconfiglib tool or Kconfiglib-based script against
# a kernel source tree, without patching scripts/kconfig/Makefile.
#
# It replicates what `make scriptconfig` sets up (srctree/ARCH/SRCARCH/CC/LD/
# KERNELVERSION env vars) and then either:
#   - execs a pip-installed Kconfiglib console script (menuconfig,
#     olddefconfig, savedefconfig, listnewconfig, genconfig, setconfig,
#     defconfig, allnoconfig, allyesconfig, alldefconfig, guiconfig), or
#   - execs an arbitrary standalone script via `python3 <path>` if you pass
#     a real file path instead of a tool name.
#
set -euo pipefail

# Capture the directory you actually ran this from, before anything cd's
# elsewhere -- this is where the generated config ends up by default.
ORIG_PWD="$(pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") -k <kernel_src> [-a <arch>] [-c <cc>] [-l <ld>] -- <tool-or-script> [args...]

  -k   Path to kernel source tree (required)
  -a   Target ARCH (default: x86_64)
  -c   Compiler to report to Kconfig (default: \$CC or gcc)
  -l   Linker to report to Kconfig (default: \$LD or ld)
  -o   Output config filename, written to the directory you ran this from,
       NOT the kernel tree (default: .config)
  --   Everything after this is the Kconfiglib tool name or script path,
       followed by its own arguments.

Note on -o: it works by setting KCONFIG_CONFIG to an absolute path back in
your invocation directory, which is what nearly all Kconfig tools (C and
Kconfiglib alike) read/write as their working config file. One notable
exception: 'savedefconfig' writes its own '--out <file>' argument rather
than honoring KCONFIG_CONFIG for output -- pass an absolute path to that
flag yourself if you use it (see example below).

Built-in Kconfiglib tools (installed via 'pip install kconfiglib'):
  menuconfig, guiconfig, oldconfig, olddefconfig, savedefconfig,
  listnewconfig, genconfig, setconfig, defconfig, allnoconfig,
  allyesconfig, alldefconfig

Examples:
  $(basename "$0") -k ~/src/linux -- menuconfig
  $(basename "$0") -k ~/src/linux -o my.config -- olddefconfig
  $(basename "$0") -k ~/src/linux -- savedefconfig --out "\$PWD/my_defconfig"
  $(basename "$0") -k ~/src/linux -- listnewconfig
  $(basename "$0") -k ~/src/linux -- ~/storage/dev/dotconfig_gen/flavors/generic/config.py

Note: if you pass a bare tool name (no '/' in it) that happens to match both
a pip-installed Kconfiglib console script AND a same-named script of your
own that isn't on PATH, the installed one wins. Pass a path (./flavors/generic/config.py
or an absolute path) to be unambiguous about running your own script.
EOF
    exit 1
}

KERNEL_SRC=""
ARCH="x86_64"
CC="${CC:-gcc}"
LD="${LD:-ld}"
OUTFILE=".config"

while getopts "k:a:c:l:o:h" opt; do
    case "$opt" in
        k) KERNEL_SRC="$OPTARG" ;;
        a) ARCH="$OPTARG" ;;
        c) CC="$OPTARG" ;;
        l) LD="$OPTARG" ;;
        o) OUTFILE="$OPTARG" ;;
        h|*) usage ;;
    esac
done
shift $((OPTIND - 1))

[[ "${1:-}" == "--" ]] && shift
[[ -z "$KERNEL_SRC" || $# -eq 0 ]] && usage
[[ -d "$KERNEL_SRC" ]] || { echo "error: kernel source dir '$KERNEL_SRC' not found" >&2; exit 1; }

# Map ARCH -> SRCARCH the same way the top-level kernel Makefile does.
case "$ARCH" in
    x86_64|i386) SRCARCH="x86" ;;
    *)           SRCARCH="$ARCH" ;;
esac

KERNEL_SRC="$(cd "$KERNEL_SRC" && pwd)"  # normalize to absolute path

export srctree="$KERNEL_SRC"
export ARCH SRCARCH CC LD
export KERNELVERSION="$(make -s -C "$KERNEL_SRC" kernelversion)"

# Recent kernels (the PAHOLE_VERSION computation was hoisted out of
# init/Kconfig and into the top-level Makefile in Dec 2025, mirroring how
# CC_VERSION_TEXT/RUSTC_VERSION_TEXT already work) expect these to already
# be present as environment variables rather than computed inline by a
# Kconfig $(shell,...) macro. Without them, PAHOLE_VERSION-gated options
# (e.g. DEBUG_INFO_BTF) show up as "non-int default (undefined)".
export PAHOLE="${PAHOLE:-pahole}"
if [[ -x "$KERNEL_SRC/scripts/pahole-version.sh" ]]; then
    export PAHOLE_VERSION="$("$KERNEL_SRC/scripts/pahole-version.sh" "$PAHOLE" 2>/dev/null || echo 0)"
else
    export PAHOLE_VERSION=0
fi
# TEMPORARY: this build host has no pahole, so the detection above yields 0,
# which forces DEBUG_INFO_BTF (and the whole BTF-dependent cluster) off and
# diverges from zabbly-config, which was built WITH pahole. init/Kconfig's
# PAHOLE_VERSION default is literally "$(PAHOLE_VERSION)" (this env var), so
# hardcoding a recent version here makes those symbols resolve identically.
# Drop this override once pahole >= 1.26 is installed on the build host.
export PAHOLE_VERSION=130
export CC_VERSION_TEXT="$("$CC" --version 2>/dev/null | head -n1)"

# Resolve the output config to an absolute path in the directory you ran
# this from -- NOT the kernel tree, even though we're about to cd there.
# KCONFIG_CONFIG is the standard env var nearly every Kconfig tool (C and
# Kconfiglib alike) reads/writes as its working config file, so pointing it
# here covers menuconfig, olddefconfig, oldconfig, listnewconfig, setconfig,
# and any custom script that calls kconf.load_config()/write_config() with
# no explicit filename.
case "$OUTFILE" in
    /*) OUT_CONFIG="$OUTFILE" ;;
    *)  OUT_CONFIG="$ORIG_PWD/$OUTFILE" ;;
esac
export KCONFIG_CONFIG="$OUT_CONFIG"

TOOL="$1"; shift

# Resolve TOOL to an absolute path *before* we cd into the kernel tree --
# otherwise a relative path like ./flavors/generic/config.py would be looked up relative
# to $KERNEL_SRC instead of the directory you actually ran this from.
if [[ -f "$TOOL" ]]; then
    TOOL="$(cd "$(dirname "$TOOL")" && pwd)/$(basename "$TOOL")"
fi

cd "$KERNEL_SRC"

echo "kconf-run: output config -> $KCONFIG_CONFIG" >&2
echo "kconf-run: (if you're using 'savedefconfig', remember its --out arg" >&2
echo "kconf-run:  is independent of KCONFIG_CONFIG -- pass an absolute path" >&2
echo "kconf-run:  to it explicitly, e.g. --out \"$ORIG_PWD/my_defconfig\")" >&2

if [[ -f "$TOOL" ]]; then
    # A path to a standalone Kconfiglib-based script (e.g. a flavor's config.py,
    # or the enable_subtree/disable_subtree scripts from earlier).
    exec python3 "$TOOL" Kconfig "$@"
else
    # A Kconfiglib built-in tool -- pip installs these as real executables.
    if ! command -v "$TOOL" >/dev/null 2>&1; then
        echo "error: '$TOOL' is neither a file nor found on PATH." >&2
        echo "       Is kconfiglib installed? (pip install kconfiglib --break-system-packages)" >&2
        echo "       If installed with --user, make sure its bin dir is on PATH." >&2
        exit 1
    fi
    exec "$TOOL" Kconfig "$@"
fi