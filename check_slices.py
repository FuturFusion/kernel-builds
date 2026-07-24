#!/usr/bin/env python3
"""Sanity-check flavors/*/config_slices/: within one flavor, every CONFIG symbol
must be set in exactly one place. Overlaps between fragments are how ordering
bugs get in -- whichever file happens to load last silently wins, and the loser
looks like it is doing something when it is not. Run after editing any slice.

Flavors are checked independently: flavors/generic/ and flavors/server/ setting
the same symbol to different values is the whole point of having separate
flavors, not a conflict.

Usage: ./check_slices.py [flavor ...]     (default: every flavor present)
Exit status: 0 clean, 1 if anything overlaps.
"""
import re, os, glob, sys, collections

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FLAVOR_DIR = os.path.join(SCRIPT_DIR, "flavors")

flavors = sys.argv[1:] or sorted(
    d for d in os.listdir(FLAVOR_DIR)
    if os.path.isdir(os.path.join(FLAVOR_DIR, d, "config_slices"))
)
if not flavors:
    sys.exit(f"no flavor directories found under {FLAVOR_DIR}")

failed = False
for flavor in flavors:
    files = sorted(glob.glob(
        os.path.join(FLAVOR_DIR, flavor, "config_slices", "*.config")))
    if not files:
        print(f"{flavor}: no *.config files -- nothing to check")
        continue

    occ = collections.defaultdict(list)
    for f in files:
        rel = os.path.relpath(f, SCRIPT_DIR)
        for n, line in enumerate(open(f), 1):
            s = line.strip()
            m = re.match(r'CONFIG_([A-Z0-9_]+)=(.*)', s)
            if m:
                occ[m.group(1)].append((rel, n, m.group(2)))
                continue
            m = re.match(r'# CONFIG_([A-Z0-9_]+) is not set', s)
            if m:
                occ[m.group(1)].append((rel, n, 'n'))

    dup = {k: v for k, v in occ.items() if len(v) > 1}
    print(f"{flavor}: {len(occ)} distinct symbols across {len(files)} slices")
    if not dup:
        print(f"{flavor}: OK -- slices are disjoint")
        continue

    failed = True
    for k, v in sorted(dup.items()):
        kind = "CONFLICT" if len({x[2] for x in v}) > 1 else "duplicate"
        print(f"{kind}: {k}")
        for f, n, val in v:
            print(f"    {f}:{n} = {val}")

sys.exit(1 if failed else 0)
