#!/bin/bash

set -ex

SCRIPT_DIR="$(dirname "$(realpath "$0")")"

set -a
source "$SCRIPT_DIR/.env"
set +a

[ ! -z "$GENERATED_CONFIG_PATH" ]

[ ! -z "$KERNEL_TREE_PATH" ]
echo "Using kernel tree: $KERNEL_TREE_PATH"

[ ! -z "$KERNEL_TREE_BUILD_PATH" ]
echo "Using kernel tree build path: $KERNEL_TREE_BUILD_PATH"

export PYTHONPATH="$SCRIPT_DIR/yocto-kernel-tools/Kconfiglib":$$PYTHONPATH

./kconf-run.sh -k "$KERNEL_TREE_PATH" -o "$GENERATED_CONFIG_PATH" -- "${SCRIPT_DIR}/yocto-kernel-tools/Kconfiglib/menuconfig.py"