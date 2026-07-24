"""
Compare two full/expanded .config files and report what differs.

Usage:
    python3 compare_configs.py <ours.config> <reference.config> [missing_out.txt] [changed_out.txt]

The optional third/fourth arguments write the "missing from ours" and
"changed value" lists to files (one CONFIG_X=val per line for missing;
one CONFIG_X=val per line using OUR current value for changed, so it can
be cross-referenced the same way), for feeding into cross_reference.py.

Only meaningful for two FULLY EXPANDED configs (post olddefconfig /
write_config), not minimized savedefconfig-style fragments -- see the
earlier discussion on why scripts/diffconfig requires the same.
"""
import re
import sys


def parse(path):
    d = {}
    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r'^(CONFIG_[A-Za-z0-9_]+)=(.*)$', line)
            if m:
                d[m.group(1)] = m.group(2)
                continue
            m = re.match(r'^# (CONFIG_[A-Za-z0-9_]+) is not set$', line)
            if m:
                d[m.group(1)] = 'n'
    return d


def main():
    if len(sys.argv) not in (3, 4, 5):
        print(f"usage: {sys.argv[0]} <ours.config> <reference.config> [missing_out.txt] [changed_out.txt]")
        sys.exit(1)

    ours = parse(sys.argv[1])
    ref = parse(sys.argv[2])

    only_ref = sorted(set(ref) - set(ours))
    only_ours = sorted(set(ours) - set(ref))
    changed = sorted(k for k in (set(ours) & set(ref)) if ours[k] != ref[k])

    print(f"ours:              {len(ours)} symbols")
    print(f"reference:         {len(ref)} symbols")
    print(f"missing from ours: {len(only_ref)}")
    print(f"extra in ours:     {len(only_ours)}")
    print(f"different value:   {len(changed)}")

    for label, items in (
        ("--- missing from ours ---", only_ref),
        ("--- extra in ours ---", only_ours),
    ):
        if items:
            print(f"\n{label}")
            for k in items:
                print(f"  {k}={(ref if 'missing' in label else ours)[k]}")

    if changed:
        print("\n--- different value ---")
        for k in changed:
            print(f"  {k}: ours={ours[k]!r} reference={ref[k]!r}")

    if len(sys.argv) >= 4:
        with open(sys.argv[3], "w") as f:
            for k in only_ref:
                f.write(f"{k}={ref[k]}\n")
        print(f"\nmissing-from-ours list written to {sys.argv[3]}")

    if len(sys.argv) == 5:
        with open(sys.argv[4], "w") as f:
            for k in changed:
                f.write(f"{k}={ours[k]}\n")
        print(f"changed-value list written to {sys.argv[4]} (using OUR current value, "
              f"for cross-referencing against capped_symbols.txt)")


if __name__ == "__main__":
    main()