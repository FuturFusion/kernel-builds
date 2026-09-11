#!/bin/bash
#
# Usage: ./genconfig.sh <arch> <flavor> [--normalize|--no-normalize] [--validate|--no-validate]
# Run with --help for details.

usage() {
    cat <<EOF
Usage: $(basename "$0") <arch> <flavor> [--normalize|--no-normalize] [--validate|--no-validate]

  arch              Target architecture, required (no default). One of the
                    lines in ./arches (amd64, arm64). Selects the seed
                    defconfig and the ARCH the real Kconfig sees.
  flavor            Which kernel to build, required (no default):
                    flavors/<flavor>/config.py plus
                    flavors/<flavor>/config_slices/.
  --normalize       Run the result through the kernel's real Kconfig
                    (make olddefconfig + savedefconfig) afterwards.
  --no-normalize    Skip that, even if .env asks for it.
  --validate        Compare the result against
                    misc/<series>/reference-<arch>-config matching the kernel
                    tree's version. Requires that reference to exist -- fails
                    if it doesn't.
  --no-validate     Skip that, even if .env asks for it. Generation doesn't
                    need a reference config at all; only this comparison does.

Normalization needs a working kernel build environment (flex, bison, bc,
libelf, libssl), which is why it's off by default. Validation needs a
reference config, which plain generation (e.g. for a .deb build) doesn't.
Set NORMALIZE_CONFIG/VALIDATE_CONFIG=true in .env to turn either on
permanently; the command-line flags override .env for a single run.
EOF
}

set -ex

SCRIPT_DIR="$(dirname "$(realpath "$0")")"

ARCH=""
FLAVOR=""
NORMALIZE_OVERRIDE=""
VALIDATE_OVERRIDE=""
POSITIONAL=()
while [ $# -gt 0 ]; do
    case "$1" in
        --normalize)    NORMALIZE_OVERRIDE=true ;;
        --no-normalize) NORMALIZE_OVERRIDE=false ;;
        --validate)     VALIDATE_OVERRIDE=true ;;
        --no-validate)  VALIDATE_OVERRIDE=false ;;
        -h|--help)      usage; exit 0 ;;
        -*)             echo "error: unknown option '$1'" >&2; usage >&2; exit 1 ;;
        *)              POSITIONAL+=("$1") ;;
    esac
    shift
done

case "${#POSITIONAL[@]}" in
    0) echo "error: arch and flavor are both required (no default for either)" >&2
       usage >&2
       exit 1 ;;
    1) echo "error: flavor is required (no default) -- got arch '${POSITIONAL[0]}' only" >&2
       usage >&2
       exit 1 ;;
    2) ;;
    *) echo "error: too many arguments: ${POSITIONAL[*]}" >&2
       usage >&2
       exit 1 ;;
esac
ARCH="${POSITIONAL[0]}"
FLAVOR="${POSITIONAL[1]}"

if [ ! -f "$SCRIPT_DIR/arches" ] || ! grep -qxF "$ARCH" "$SCRIPT_DIR/arches"; then
    echo "error: unknown arch '$ARCH' -- expected one of: $(tr '\n' ' ' < "$SCRIPT_DIR/arches" 2>/dev/null)" >&2
    exit 1
fi

# arch -> kernel ARCH, header arch label, seed defconfig.
case "$ARCH" in
    amd64) KERNEL_ARCH="x86_64" ; HEADER_ARCH="x86"   ; DEFCONFIG="arch/x86/configs/x86_64_defconfig" ;;
    arm64) KERNEL_ARCH="arm64"  ; HEADER_ARCH="arm64" ; DEFCONFIG="arch/arm64/configs/defconfig" ;;
    *)     echo "error: arch '$ARCH' is in ./arches but has no mapping in genconfig.sh" >&2 ; exit 1 ;;
esac

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

# e.g. generated_config-generic-amd64, generated_config-server-arm64.
GENERATED_CONFIG_PATH="$SCRIPT_DIR/${GENERATED_CONFIG_PATH}-${FLAVOR}-${ARCH}"

# Command-line flags beat .env, which beats the default (off).
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

# Strip an -rcN/-whatever suffix before deriving the series, so "6.19.4" and
# "6.19-rc3" both key on "6.19".
KERNEL_VERSION="$(make -s -C "$KERNEL_TREE_PATH" ARCH="$KERNEL_ARCH" kernelversion)"
KERNEL_SERIES="$(echo "${KERNEL_VERSION%%-*}" | cut -d. -f1,2)"

REFERENCE_CONFIG=""
if [ "$VALIDATE_CONFIG" = "true" ]; then
    REFERENCE_CONFIG="${SCRIPT_DIR}/misc/${KERNEL_SERIES}/reference-${ARCH}-config"
    if [ ! -f "$REFERENCE_CONFIG" ]; then
        echo "error: no $ARCH reference config for kernel series '$KERNEL_SERIES' (kernel tree at $KERNEL_TREE_PATH reports version '$KERNEL_VERSION')" >&2
        echo "       expected to find it at: $REFERENCE_CONFIG" >&2
        # shellcheck disable=SC2012  # a friendly listing in an error message, not parsing-critical
        echo "       available series: $(ls "${SCRIPT_DIR}/misc" 2>/dev/null | tr '\n' ' ')" >&2
        echo "       or run without --validate to generate without comparing against a reference" >&2
        exit 1
    fi
    echo "Kernel tree version: $KERNEL_VERSION (series $KERNEL_SERIES, $ARCH) -- validating against $REFERENCE_CONFIG"
else
    echo "Kernel tree version: $KERNEL_VERSION (series $KERNEL_SERIES, $ARCH) -- not validating against a reference (pass --validate to compare)"
fi

export PYTHONPATH="$SCRIPT_DIR/yocto-kernel-tools/Kconfiglib${PYTHONPATH:+:$PYTHONPATH}"

# Read by genconfig.py's start() and by normalize-config.sh (for `make ARCH=`).
export GENCONFIG_DEFCONFIG="$DEFCONFIG"
export KERNEL_ARCH

export KCONFIG_CONFIG_HEADER="#
# Automatically generated by genconfig.sh; DO NOT EDIT.
# Please, look into flavors/${FLAVOR}/config.py and flavors/${FLAVOR}/config_slices/*.config
# Linux/${HEADER_ARCH} ${KERNEL_VERSION} Kernel Configuration
#
"

# output/ is gitignored, so it won't exist in a fresh clone -- create it
# rather than letting finish() fail on the first run.
export GENCONFIG_OUTPUT_DIR="${SCRIPT_DIR}/output/${FLAVOR}/${ARCH}"
rm -rf "$GENCONFIG_OUTPUT_DIR"
mkdir -p "$GENCONFIG_OUTPUT_DIR"
rm -f "$GENERATED_CONFIG_PATH"
./kconf-run.sh -k "$KERNEL_TREE_PATH" -a "$KERNEL_ARCH" -o "$GENERATED_CONFIG_PATH" -- "$FLAVOR_SCRIPT"

if [ "$NORMALIZE_CONFIG" = "true" ]; then
    # Fail with something legible rather than 30 lines of make output ending
    # in "flex: not found".
    for tool in flex bison; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            echo "error: normalization needs a kernel build environment, but '$tool' is not installed." >&2
            echo "       Debian/Ubuntu: sudo apt install build-essential flex bison bc libelf-dev libssl-dev" >&2
            echo "       Or run without it: ./genconfig.sh $ARCH $FLAVOR --no-normalize" >&2
            exit 1
        fi
    done

    echo "Normalizing through the real Kconfig (make olddefconfig + savedefconfig)"

    # Rewritten in place; runs regardless of --validate since a normalized
    # config is what a real build needs either way.
    "${SCRIPT_DIR}/normalize-config.sh" "$GENERATED_CONFIG_PATH" "$GENERATED_CONFIG_PATH" "${GENERATED_CONFIG_PATH}-defconfig"

    if [ "$VALIDATE_CONFIG" = "true" ]; then
        # The reference must go through the same toolchain, or the comparison
        # below measures the normalizer rather than the generator -- but write
        # it under output/, never back over the tracked reference file.
        NORMALIZED_REFERENCE="${GENCONFIG_OUTPUT_DIR}/reference-config"
        "${SCRIPT_DIR}/normalize-config.sh" "$REFERENCE_CONFIG" "$NORMALIZED_REFERENCE" "${NORMALIZED_REFERENCE}-defconfig"
        REFERENCE_CONFIG="$NORMALIZED_REFERENCE"
    fi
fi

# Read the diff per flavor: for generic, zero lines is the goal; for a flavor
# that deliberately strips things, a big diff means it's doing its job.
if [ "$VALIDATE_CONFIG" = "true" ]; then
    python3 compare_configs.py "$GENERATED_CONFIG_PATH" "$REFERENCE_CONFIG" "${GENCONFIG_OUTPUT_DIR}/missing_from_ours.txt" "${GENCONFIG_OUTPUT_DIR}/changed_from_ours.txt"
    python3 cross_reference.py "${GENCONFIG_OUTPUT_DIR}/capped_symbols.txt" "${GENCONFIG_OUTPUT_DIR}/changed_from_ours.txt"
    diff -y --suppress-common-lines "$REFERENCE_CONFIG" "$GENERATED_CONFIG_PATH" > "${GENCONFIG_OUTPUT_DIR}/diff" || true

    # Minimal-form diff; only exists when normalization ran.
    if [ "$NORMALIZE_CONFIG" = "true" ]; then
        diff -y --suppress-common-lines "${REFERENCE_CONFIG}-defconfig" "${GENERATED_CONFIG_PATH}-defconfig" > "${GENCONFIG_OUTPUT_DIR}/diff-defconfig" || true
    fi
fi
