"""
Cross-reference genconfig_validate_zabbly.py's capped_symbols.txt against
compare_configs.py-style missing-vs-zabbly output, to separate genuine
gaps from expected noise (e.g. ETHERNET drivers for architectures that
can't exist on x86_64 at all -- those get "capped" too, correctly, and
zabbly-config doesn't have them either).

A symbol is worth investigating only if BOTH are true:
  1. Our enable_subtree() walker tried to enable it and failed (present
     in capped_symbols.txt)
  2. zabbly-config actually has it enabled (present in the "missing from
     ours" side of the diff) -- i.e. it's a REAL gap, not something
     neither config wants.

Usage:
    python3 cross_reference.py capped_symbols.txt missing_from_ours.txt

Where missing_from_ours.txt is one CONFIG_X=val per line, same format
compare_configs.py's "missing from ours" section uses.
"""
import sys
from collections import defaultdict


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <capped_symbols.txt> <missing_from_ours.txt>")
        sys.exit(1)

    capped_by_umbrella = defaultdict(list)
    with open(sys.argv[1]) as f:
        for line in f:
            label, name, val = line.rstrip("\n").split("\t")
            capped_by_umbrella[label].append(name)

    missing = set()
    with open(sys.argv[2]) as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                missing.add(line.split("=")[0])

    total_capped = sum(len(v) for v in capped_by_umbrella.values())
    print(f"{total_capped} symbols were capped across all umbrellas")
    print(f"{len(missing)} symbols are actually missing vs zabbly-config")
    print()

    real_problems = defaultdict(list)
    for label, names in capped_by_umbrella.items():
        for name in names:
            if name in missing:
                real_problems[label].append(name)

    total_real = sum(len(v) for v in real_problems.values())
    print(f"=== {total_real} genuine gaps (capped AND actually missing vs zabbly) ===")
    for label, names in sorted(real_problems.items(), key=lambda x: -len(x[1])):
        print(f"\n{label}: {len(names)}")
        for n in names:
            print(f"  {n}")

    noise = total_capped - total_real
    print(f"\n({noise} other capped symbols are noise -- zabbly doesn't have "
          f"them enabled either, most likely arch-irrelevant hardware)")


if __name__ == "__main__":
    main()
