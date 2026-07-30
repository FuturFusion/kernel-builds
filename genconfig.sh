#!/bin/bash
#
# Usage: ./genconfig.sh [flavor] [--normalize|--no-normalize] [--validate|--no-validate]
#
# A flavor is a directory: flavors/<flavor>/config.py (the policy) plus
# flavors/<flavor>/config_slices/ (the data). genconfig.py itself is
# flavor-agnostic machinery and is never run directly. Default flavor: generic.
#
# Normalization runs the result through the kernel's real Kconfig
# (make olddefconfig + savedefconfig, via fix-config.sh) instead of stopping at
# what Kconfiglib produced. It is off by default because it needs a working
# kernel build environment -- flex, bison, bc, libelf, libssl -- which plain
# config generation does not. Set NORMALIZE_CONFIG=true in .env to turn it on
# permanently; the flags override .env for a single run.
#
# Validation compares the generated config against the misc/<series>/
# zabbly-config matching the kernel tree's own version, and is what needs
# that reference to exist at all. It is off by default: generating a config
# is a legitimate thing to want on its own (e.g. to build a .deb from it),
# and a reference is only needed for the "does this match zabbly-config"
# question, not for generation itself. Set VALIDATE_CONFIG=true in .env to
# turn it on permanently; the flags override .env for a single run.

usage() {
    cat <<EOF
Usage: $(basename "$0") [flavor] [--normalize|--no-normalize] [--validate|--no-validate]

  flavor            Which kernel to build: flavors/<flavor>/config.py plus
                    flavors/<flavor>/config_slices/. Default: generic.
  --normalize       Run the result through the kernel's real Kconfig
                    (make olddefconfig + savedefconfig) afterwards.
  --no-normalize    Skip that, even if .env asks for it.
  --validate        Compare the result against the misc/<series>/zabbly-config
                    matching the kernel tree's version. Requires that
                    reference to exist -- fails if it doesn't.
  --no-validate     Skip that, even if .env asks for it. Generation doesn't
                    need a reference config at all; only this comparison does.

Normalization is off by default because it needs a working kernel build
environment (flex, bison, bc, libelf, libssl) that plain config generation
does not. Set NORMALIZE_CONFIG=true in .env to turn it on permanently.

Validation is off by default because a reference config is only needed to
answer "does this match zabbly-config", not to generate a config in the first
place -- e.g. building a .deb from the result needs no reference at all. Set
VALIDATE_CONFIG=true in .env to turn it on permanently.

Either flag pair given on the command line overrides .env for this run only.
EOF
}

set -e

SCRIPT_DIR="$(dirname "$(realpath "$0")")"

FLAVOR=""
NORMALIZE_OVERRIDE=""
VALIDATE_OVERRIDE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --normalize)    NORMALIZE_OVERRIDE=true ;;
        --no-normalize) NORMALIZE_OVERRIDE=false ;;
        --validate)     VALIDATE_OVERRIDE=true ;;
        --no-validate)  VALIDATE_OVERRIDE=false ;;
        -h|--help)      usage; exit 0 ;;
        -*)             echo "error: unknown option '$1'" >&2; usage >&2; exit 1 ;;
        *)
            if [ -n "$FLAVOR" ]; then
                echo "error: more than one flavor given ('$FLAVOR', '$1')" >&2
                exit 1
            fi
            FLAVOR="$1"
            ;;
    esac
    shift
done
FLAVOR="${FLAVOR:-generic}"

set -x

FLAVOR_SCRIPT="$SCRIPT_DIR/flavors/${FLAVOR}/config.py"
if [ ! -f "$FLAVOR_SCRIPT" ]; then
    echo "error: unknown flavor '$FLAVOR' -- no such file: $FLAVOR_SCRIPT" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091  # .env is generated at runtime, not present at lint time
source "$SCRIPT_DIR/.env"
set +a

[ -n "$GENERATED_CONFIG_PATH" ]

# Only the default flavor claims the plain output name; the rest are suffixed
# so they cannot clobber each other.
if [ "$FLAVOR" != "generic" ]; then
    GENERATED_CONFIG_PATH="${GENERATED_CONFIG_PATH}-${FLAVOR}"
fi

# Command-line flags beat .env, which beats the default (off), for both
# independent toggles.
NORMALIZE_CONFIG="${NORMALIZE_OVERRIDE:-${NORMALIZE_CONFIG:-false}}"
case "$NORMALIZE_CONFIG" in
    true|false) ;;
    *) echo "error: NORMALIZE_CONFIG must be true or false, got '$NORMALIZE_CONFIG'" >&2
       exit 1 ;;
esac

VALIDATE_CONFIG="${VALIDATE_OVERRIDE:-${VALIDATE_CONFIG:-false}}"
case "$VALIDATE_CONFIG" in
    true|false) ;;
    *) echo "error: VALIDATE_CONFIG must be true or false, got '$VALIDATE_CONFIG'" >&2
       exit 1 ;;
esac

[ -n "$KERNEL_TREE_PATH" ]
echo "Using kernel tree: $KERNEL_TREE_PATH"

[ -n "$KERNEL_TREE_BUILD_PATH" ]
echo "Using kernel tree build path: $KERNEL_TREE_BUILD_PATH"

# The kernel tree's own version, used for the config header comment
# regardless of validation, and additionally to pick a reference config when
# validating. Strip an -rcN/-whatever suffix first, then take the first two
# dot-separated components: "6.19.4" and "6.19-rc3" both key on "6.19"; a
# tree that reports a bare two-component version ("7.1") is used as-is.
KERNEL_VERSION="$(make -s -C "$KERNEL_TREE_PATH" kernelversion)"
KERNEL_SERIES="$(echo "${KERNEL_VERSION%%-*}" | cut -d. -f1,2)"

# Every reference config lives under misc/<series>/zabbly-config -- one per
# kernel series, not one for the whole repo. Only look for it, and only
# require it to exist, when actually validating: generating a config is a
# legitimate thing to want with no reference in play at all (e.g. building a
# .deb from the result), so a missing reference must not block that.
REFERENCE_CONFIG=""
if [ "$VALIDATE_CONFIG" = "true" ]; then
    REFERENCE_CONFIG="${SCRIPT_DIR}/misc/${KERNEL_SERIES}/zabbly-config"
    if [ ! -f "$REFERENCE_CONFIG" ]; then
        echo "error: no reference config for kernel series '$KERNEL_SERIES' (kernel tree at $KERNEL_TREE_PATH reports version '$KERNEL_VERSION')" >&2
        echo "       expected to find it at: $REFERENCE_CONFIG" >&2
        # shellcheck disable=SC2012  # a friendly listing in an error message, not parsing-critical
        echo "       available series: $(ls "${SCRIPT_DIR}/misc" 2>/dev/null | tr '\n' ' ')" >&2
        echo "       or run without --validate to generate without comparing against a reference" >&2
        exit 1
    fi
    echo "Kernel tree version: $KERNEL_VERSION (series $KERNEL_SERIES) -- validating against $REFERENCE_CONFIG"
else
    echo "Kernel tree version: $KERNEL_VERSION (series $KERNEL_SERIES) -- not validating against a reference (pass --validate to compare)"
fi

# "$$PYTHONPATH" here used to expand to the shell PID followed by the literal
# string "PYTHONPATH" -- harmless, but it never actually preserved an
# inherited PYTHONPATH the way it meant to.
export PYTHONPATH="$SCRIPT_DIR/yocto-kernel-tools/Kconfiglib${PYTHONPATH:+:$PYTHONPATH}"

export KCONFIG_CONFIG_HEADER="#
# Automatically generated by genconfig.sh; DO NOT EDIT.
# Please, look into flavors/${FLAVOR}/config.py and flavors/${FLAVOR}/config_slices/*.config
# Linux/x86 ${KERNEL_VERSION} Kernel Configuration
#
"

# Analysis is written per flavor, so building one does not wipe out the
# analysis of another. output/ is generated data and gitignored, so it does not
# exist in a fresh clone -- create it rather than letting finish() fail on the
# first run. genconfig.py reads this to place capped_symbols.txt (written
# unconditionally -- it's a diagnostic of the enable_subtree() walk itself,
# not of the comparison against a reference).
export GENCONFIG_OUTPUT_DIR="${SCRIPT_DIR}/output/${FLAVOR}"
rm -rf "$GENCONFIG_OUTPUT_DIR"
mkdir -p "$GENCONFIG_OUTPUT_DIR"
rm -f "$GENERATED_CONFIG_PATH"
./kconf-run.sh -k "$KERNEL_TREE_PATH" -o "$GENERATED_CONFIG_PATH" -- "$FLAVOR_SCRIPT"

if [ "$NORMALIZE_CONFIG" = "true" ]; then
    # Fail with something legible rather than 30 lines of make output ending in
    # "flex: not found". These are the two that plain config generation never
    # needs, so they are the ones actually likely to be missing.
    for tool in flex bison; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            echo "error: normalization needs a kernel build environment, but '$tool' is not installed." >&2
            echo "       Debian/Ubuntu: sudo apt install build-essential flex bison bc libelf-dev libssl-dev" >&2
            echo "       Or run without it: ./genconfig.sh --no-normalize" >&2
            exit 1
        fi
    done

    echo "Normalizing through the real Kconfig (make olddefconfig + savedefconfig)"
    mkdir -p "$KERNEL_TREE_BUILD_PATH"

    # Ours: rewritten in place. It is generated output, so there is nothing to
    # lose, and every consumer below should see the normalized form. This
    # happens regardless of --validate -- a normalized config is what a real
    # build (e.g. a .deb) needs, reference or no reference.
    cp "$GENERATED_CONFIG_PATH" "${KERNEL_TREE_BUILD_PATH}/.config"
    "${SCRIPT_DIR}/fix-config.sh"
    cp "${KERNEL_TREE_BUILD_PATH}/.config" "$GENERATED_CONFIG_PATH"
    cp "${KERNEL_TREE_BUILD_PATH}/defconfig" "${GENERATED_CONFIG_PATH}-defconfig"

    if [ "$VALIDATE_CONFIG" = "true" ]; then
        # The reference has to go through the same toolchain or the comparison
        # below is measuring the normalizer rather than the generator. But it is
        # written under output/ rather than back over misc/<series>/zabbly-config: a
        # run must not rewrite a tracked reference file. Doing exactly that in
        # place is why a misc/<series>/zabbly-config.orig had to exist as a
        # pristine copy to recover from, and a reference silently regenerated by
        # the same toolchain as the thing it is checking would make a clean diff
        # meaningless.
        #
        # Note this reuses KERNEL_TREE_BUILD_PATH/.config as scratch space,
        # clobbering the normalized copy of OUR config that's currently sitting
        # there -- fine here since we already copied it out to
        # GENERATED_CONFIG_PATH above, but anything downstream that wants
        # KERNEL_TREE_BUILD_PATH/.config to be ours (e.g. a build step chained
        # after this script) needs to re-copy it from GENERATED_CONFIG_PATH first.
        NORMALIZED_REFERENCE="${GENCONFIG_OUTPUT_DIR}/reference-config"
        cp "$REFERENCE_CONFIG" "${KERNEL_TREE_BUILD_PATH}/.config"
        "${SCRIPT_DIR}/fix-config.sh"
        cp "${KERNEL_TREE_BUILD_PATH}/.config" "$NORMALIZED_REFERENCE"
        cp "${KERNEL_TREE_BUILD_PATH}/defconfig" "${NORMALIZED_REFERENCE}-defconfig"
        REFERENCE_CONFIG="$NORMALIZED_REFERENCE"
    fi
fi

# Everything from here down is the comparison against a reference, so none of
# it runs without --validate. Every flavor built against this kernel series is
# compared against that series' reference, since it is the only one available
# for it and a diff is more informative than no diff -- but read it
# differently per flavor. For generic, a diff of zero is the goal and any
# line is a defect. For a flavor that deliberately strips things, the diff is
# the list of what it dropped, and a big one means it is doing its job.
if [ "$VALIDATE_CONFIG" = "true" ]; then
    python3 compare_configs.py "$GENERATED_CONFIG_PATH" "$REFERENCE_CONFIG" "${GENCONFIG_OUTPUT_DIR}/missing_from_ours.txt" "${GENCONFIG_OUTPUT_DIR}/changed_from_ours.txt"
    python3 cross_reference.py "${GENCONFIG_OUTPUT_DIR}/capped_symbols.txt" "${GENCONFIG_OUTPUT_DIR}/changed_from_ours.txt"
    diff -y --suppress-common-lines "$REFERENCE_CONFIG" "$GENERATED_CONFIG_PATH" > "${GENCONFIG_OUTPUT_DIR}/diff" || true

    # savedefconfig strips everything implied by dependencies and defaults, so this
    # second diff is the minimal statement of what the two configs really disagree
    # about. Only exists when normalization ran.
    if [ "$NORMALIZE_CONFIG" = "true" ]; then
        diff -y --suppress-common-lines "${REFERENCE_CONFIG}-defconfig" "${GENERATED_CONFIG_PATH}-defconfig" > "${GENCONFIG_OUTPUT_DIR}/diff-defconfig" || true
    fi
fi
