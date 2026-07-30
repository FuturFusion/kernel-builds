#!/bin/bash

set -ex

SCRIPT_DIR="$(dirname "$(realpath "$0")")"

set -a
# shellcheck disable=SC1091  # .env is generated at runtime, not present at lint time
source "$SCRIPT_DIR/.env"
set +a

[ -n "$GENERATED_CONFIG_PATH" ]

[ -n "$KERNEL_TREE_PATH" ]
echo "Using kernel tree: $KERNEL_TREE_PATH"

[ -n "$KERNEL_TREE_BUILD_PATH" ]
echo "Using kernel tree build path: $KERNEL_TREE_BUILD_PATH"

export PYTHONPATH="$SCRIPT_DIR/yocto-kernel-tools/Kconfiglib":$$PYTHONPATH

./kconf-run.sh -k "$KERNEL_TREE_PATH" -o "$GENERATED_CONFIG_PATH" -- "${SCRIPT_DIR}/yocto-kernel-tools/Kconfiglib/menuconfig.py"