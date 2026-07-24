#!/bin/bash
#
# Run the kernel's own Kconfig over $KERNEL_TREE_BUILD_PATH/.config: expand it
# with olddefconfig, then reduce it to its minimal form with savedefconfig.
#
# Put the config you want normalized at $KERNEL_TREE_BUILD_PATH/.config first;
# the results are left at .config and defconfig in the same directory.
# genconfig.sh --normalize drives this. Unlike the rest of the tooling this
# needs a working kernel build environment (flex, bison, bc, libelf, libssl),
# which is why it is opt-in.

set -ex

SCRIPT_DIR="$(dirname "$(realpath "$0")")"

set -a
source "$SCRIPT_DIR/.env"
set +a

[ ! -z "$KERNEL_TREE_PATH" ]
echo "Using kernel tree: $KERNEL_TREE_PATH"

[ ! -z "$KERNEL_TREE_BUILD_PATH" ]
echo "Using kernel tree build path: $KERNEL_TREE_BUILD_PATH"

mkdir -p "$KERNEL_TREE_BUILD_PATH"
cd "$KERNEL_TREE_PATH"

time -p make O="$KERNEL_TREE_BUILD_PATH" olddefconfig

time -p make O="$KERNEL_TREE_BUILD_PATH" savedefconfig
