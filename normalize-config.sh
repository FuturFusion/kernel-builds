#!/bin/bash
#
# Usage: ./normalize-config.sh <input-config> <output-config> <output-defconfig>
#
# Run the kernel's own Kconfig over <input-config>: expand it with
# olddefconfig, reduce it to its minimal form with savedefconfig, then verify
# that reduction was lossless by installing the defconfig as .config,
# re-expanding it, and byte-comparing against the first expansion. A mismatch
# means savedefconfig's output doesn't actually reproduce the config it was
# minimized from -- fail loudly rather than ship a lying defconfig.
#
# Needs a working kernel build environment (flex, bison, bc, libelf, libssl),
# which is why genconfig.sh --normalize keeps this opt-in.
#
# KERNEL_ARCH (e.g. x86_64, arm64) sets make's ARCH=; unset, it defaults to
# the build host's arch, same as a bare `make olddefconfig` would.

set -ex

SCRIPT_DIR="$(dirname "$(realpath "$0")")"

usage() {
    echo "Usage: $(basename "$0") <input-config> <output-config> <output-defconfig>" >&2
}

if [ $# -ne 3 ]; then
    echo "error: exactly 3 arguments required, got $#" >&2
    usage
    exit 1
fi
INPUT_CONFIG="$1"
OUTPUT_CONFIG="$2"
OUTPUT_DEFCONFIG="$3"

[ -f "$INPUT_CONFIG" ] || { echo "error: no such input config: $INPUT_CONFIG" >&2; exit 1; }

set -a
# shellcheck disable=SC1091  # .env is generated at runtime, not present at lint time
source "$SCRIPT_DIR/.env"
set +a

[ -n "$KERNEL_TREE_PATH" ]
echo "Using kernel tree: $KERNEL_TREE_PATH"

[ -n "$KERNEL_TREE_BUILD_PATH" ]
echo "Using kernel tree build path: $KERNEL_TREE_BUILD_PATH"

mkdir -p "$KERNEL_TREE_BUILD_PATH"
cp "$INPUT_CONFIG" "${KERNEL_TREE_BUILD_PATH}/.config"

cd "$KERNEL_TREE_PATH"

MAKEARGS=("O=$KERNEL_TREE_BUILD_PATH")
[ -n "${KERNEL_ARCH:-}" ] && MAKEARGS=("ARCH=$KERNEL_ARCH" "${MAKEARGS[@]}")

time -p make "${MAKEARGS[@]}" olddefconfig

# Saved aside before the steps below overwrite .config.
EXPANDED_CONFIG="${KERNEL_TREE_BUILD_PATH}/.config.expanded"
cp "${KERNEL_TREE_BUILD_PATH}/.config" "$EXPANDED_CONFIG"

time -p make "${MAKEARGS[@]}" savedefconfig

# Round-trip check: re-expand the defconfig and compare to $EXPANDED_CONFIG.
cp "${KERNEL_TREE_BUILD_PATH}/defconfig" "${KERNEL_TREE_BUILD_PATH}/.config"
time -p make "${MAKEARGS[@]}" olddefconfig

if ! cmp -s "$EXPANDED_CONFIG" "${KERNEL_TREE_BUILD_PATH}/.config"; then
    echo "error: round-trip check failed -- expanding the savedefconfig output" >&2
    echo "       does not reproduce the original expanded config byte-for-byte:" >&2
    diff -u "$EXPANDED_CONFIG" "${KERNEL_TREE_BUILD_PATH}/.config" >&2 || true
    exit 1
fi

cp "$EXPANDED_CONFIG" "$OUTPUT_CONFIG"
cp "${KERNEL_TREE_BUILD_PATH}/defconfig" "$OUTPUT_DEFCONFIG"
