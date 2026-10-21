#!/bin/bash
# apply-kernel-patches.sh <kernel-tree-path> <series>
#
# Applies patches/<series>/*.patch (if any) to the kernel tree at
# <kernel-tree-path>, in filename order. No-op if the directory doesn't
# exist or has no *.patch files.
#
# No -N/--batch: stdin here is the patch file itself, not a tty, so patch
# can't prompt interactively either way -- it defaults to "n" and skips,
# exiting 1, on the "reversed/previously applied" question. That already
# gives us exactly what we want: if the tree already has this change (it
# likely landed upstream), that's a hard failure, not a silent skip and
# never a silent reverse-apply. A maintainer then drops the patch from
# patches/<series>/.
set -uo pipefail

if [ $# -ne 2 ]; then
    echo "usage: $(basename "$0") <kernel-tree-path> <series>" >&2
    exit 1
fi

TREE="$1"
SERIES="$2"
SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
PATCHDIR="$SCRIPT_DIR/patches/$SERIES"

if [ ! -d "$PATCHDIR" ]; then
    echo "No patches/$SERIES -- nothing to apply to $TREE."
    exit 0
fi

shopt -s nullglob
patches=("$PATCHDIR"/*.patch)
if [ ${#patches[@]} -eq 0 ]; then
    echo "patches/$SERIES exists but has no *.patch files -- nothing to apply to $TREE."
    exit 0
fi

for p in "${patches[@]}"; do
    echo "Applying $(basename "$p") to $TREE"
    out="$(patch -p1 --no-backup-if-mismatch -r - -d "$TREE" < "$p" 2>&1)"
    rc=$?
    echo "$out"
    if echo "$out" | grep -q "Reversed (or previously applied) patch detected"; then
        echo "error: $(basename "$p") is already applied to $TREE." >&2
        echo "       The tree already contains this change -- it likely landed upstream." >&2
        echo "       Remove it from patches/$SERIES/, or confirm it's still needed." >&2
        exit 1
    elif [ $rc -ne 0 ]; then
        echo "error: failed to apply $(basename "$p") to $TREE" >&2
        exit 1
    elif echo "$out" | grep -q "with fuzz"; then
        echo "  -> applied with fuzz (context drifted a little but it was unambiguous) -- worth a look"
    fi
done
echo "Applied ${#patches[@]} patch(es) from patches/$SERIES to $TREE"
