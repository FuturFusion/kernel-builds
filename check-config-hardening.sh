#!/bin/sh
#
# Usage: ./check-config-hardening.sh [config]
#
# Run kernel-hardening-checker over a generated config -- by default whatever
# GENERATED_CONFIG_PATH in .env points at.
#
# The result is informational. The generic flavor targets parity with a
# general-purpose distro kernel, which is nowhere near a hardened one, so FAIL
# lines are expected rather than defects. This script's exit status reflects
# only whether the checker ran: non-zero means the tool itself errored out, not
# that checks failed.

set -e

DIR="$(dirname "$(realpath "$0")")"
CHECKER="$DIR/kernel-hardening-checker/bin/kernel-hardening-checker"

if [ ! -x "$CHECKER" ]; then
    echo "error: $CHECKER not found -- run: git submodule update --init --recursive" >&2
    exit 1
fi

CONFIG="${1:-}"
if [ -z "$CONFIG" ]; then
    if [ ! -f "$DIR/.env" ]; then
        echo "error: no .env -- copy .env.example to .env, or pass a config path" >&2
        exit 1
    fi
    . "$DIR/.env"
    CONFIG="$GENERATED_CONFIG_PATH"
fi

# GENERATED_CONFIG_PATH is normally relative to the repository root.
case "$CONFIG" in
    /*) ;;
    *) CONFIG="$DIR/$CONFIG" ;;
esac

if [ ! -f "$CONFIG" ]; then
    echo "error: config not found: $CONFIG (run ./genconfig.sh first)" >&2
    exit 1
fi

exec "$CHECKER" -c "$CONFIG"
