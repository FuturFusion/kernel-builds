# dotconfig_gen

Generate a Linux kernel `.config` programmatically, by walking the Kconfig tree
with [Kconfiglib](https://github.com/ulfalizer/Kconfiglib) instead of
hand-maintaining a 13 000-line config file.

The idea is to express configuration as *structure* wherever possible — "enable
this whole driver family as modules", "walk this menu" — and fall back to
per-symbol data only where a symbol genuinely has no family, gate or prefix to
hang off. The generic flavor currently reproduces a real distro kernel config
([zabbly](https://github.com/zabbly/linux)'s x86_64 build) with a diff of zero,
which is what makes the machinery trustworthy enough to build other kernels
with.

## Layout

| Path | What it is |
| --- | --- |
| `genconfig.py` | The library: Kconfig tree-walking machinery. Sets no symbols; not runnable on its own. |
| `flavors/<name>/config.py` | A *flavor*: the policy for one kernel — what to switch on and why. |
| `flavors/<name>/config_slices/*.config` | The data half of that flavor: per-symbol policy no structural sweep can express. |
| `genconfig.sh` | Entry point. `./genconfig.sh [flavor]`, defaults to `generic`. |
| `kconf-run.sh` | Runs any Kconfiglib script/tool against a kernel tree (what `make scriptconfig` would set up). |
| `misc/zabbly-config` | The reference config the generic flavor aims to reproduce. Neither input nor output — it is how the result is judged. |

A flavor is a self-contained directory — `flavors/<name>/config.py` plus
`flavors/<name>/config_slices/`. Adding one requires no changes to
`genconfig.py`:

```
flavors/
├── generic/
│   ├── config.py
│   └── config_slices/
│       ├── block_devices.config
│       ├── containers.config
│       └── …
└── incus-os/
    ├── config.py
    └── config_slices/
        └── …
```

### The flavors

| Flavor | Purpose |
| --- | --- |
| `generic` | Full-featured distro kernel. Reproduces `misc/zabbly-config` exactly; a diff of zero is the goal, and any line in it is a defect. |
| `incus-os` | Hypervisor/container host kernel for x86_64 servers. **Currently a verbatim copy of `generic`** — the starting point, so that divergence shows up commit by commit rather than as one unreviewable drop. |

Both are compared against `misc/zabbly-config`, because it is the only reference
in the tree and a diff is more informative than no diff. Read them differently
though: for `generic` a diff of zero is success, while for a flavor that
deliberately strips things the diff is the list of what it dropped, and a large
one means it is working.

## Prerequisites

**1. Submodules.** Kconfiglib comes from the `yocto-kernel-tools` submodule:

```sh
git submodule update --init --recursive
```

**2. A kernel source tree.** You need a checkout of the kernel you are
configuring, somewhere on disk — this repo does not ship or fetch one. The
generated config is only meaningful for the tree it was generated against, since
symbol names, defaults and dependencies all change between releases.

```sh
git clone --depth 1 https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git ~/src/linux
```

**3. Standard kernel build dependencies.** Even though nothing is compiled here,
the tooling shells out to the kernel's own `make` and probes the toolchain the
same way Kconfig does (`CC_VERSION_TEXT`, `PAHOLE_VERSION`, …), so the usual set
has to be present:

```sh
# Debian / Ubuntu
sudo apt install build-essential flex bison bc libelf-dev libssl-dev \
                 dwarves python3
```

`dwarves` provides `pahole`, which gates `DEBUG_INFO_BTF` and everything
downstream of it. Note that `kconf-run.sh` currently hardcodes
`PAHOLE_VERSION=130` as a temporary workaround for build hosts without pahole
installed — drop that override once you have pahole ≥ 1.26.

**4. Your `.env`.** The tooling reads a `.env` file that is deliberately not in
git, because the paths are per-machine. Create it from the template before
running anything:

```sh
cp .env.example .env
$EDITOR .env
```

| Variable | Meaning |
| --- | --- |
| `GENERATED_CONFIG_PATH` | Where to write the generated config. Non-default flavors get `-<flavor>` appended, so they can't clobber each other. |
| `KERNEL_TREE_PATH` | Your kernel source checkout. |
| `KERNEL_TREE_BUILD_PATH` | Scratch `O=` build directory, used only by normalization. |
| `NORMALIZE_CONFIG` | `true`/`false` (default `false`) — see [Normalization](#normalization). |

## Usage

Run from the repository root:

```sh
./genconfig.sh              # same as ./genconfig.sh generic
./genconfig.sh incus-os     # any flavor under flavors/
./genconfig.sh --help       # flags and defaults
```

This writes `generated_config` (or `generated_config-<flavor>` for anything but
`generic`) and compares it against `misc/zabbly-config`, leaving the analysis in
`output/<flavor>/` — per flavor, so building one does not wipe out the analysis
of another:

| File | Contents |
| --- | --- |
| `output/<flavor>/diff` | Side-by-side diff against the reference config. |
| `output/<flavor>/missing_from_ours.txt` | Symbols the reference enables that we don't. |
| `output/<flavor>/changed_from_ours.txt` | Symbols where the two configs disagree. |
| `output/<flavor>/capped_symbols.txt` | Assignments the walker attempted that were silently capped by an unmet dependency. |

Most of `capped_symbols.txt` is expected noise — drivers for hardware that
cannot exist on x86_64 get "capped" quite correctly. `cross_reference.py` (run
automatically by `genconfig.sh`) intersects it with the missing-vs-reference
list to surface only the genuine gaps.

To add a flavor, copy an existing one and start editing:

```sh
cp -r flavors/generic flavors/server    # then trim flavors/server/
./genconfig.sh server
```

A flavor loads the `config_slices/` sitting next to it — `config.py` derives its
own name from its directory, so a copy needs no edit to point at the right
fragments.

## Normalization

By default the generator stops at what Kconfiglib produced. Normalization runs
the result through the kernel's *real* Kconfig afterwards — `make olddefconfig`
to expand it, `make savedefconfig` to reduce it to its minimal form — which is
the authoritative check that the config is one the kernel itself would accept.

It is opt-in because it is the one part of the tooling that needs a working
kernel build environment: without flex and bison you get nothing generated at
all, so requiring them for everyone would be a steep price for an optional
verification step.

```sh
./genconfig.sh --normalize      # this run only
./genconfig.sh --no-normalize   # this run only, even if .env asks for it
```

Set `NORMALIZE_CONFIG=true` in `.env` to make it the default; the flags always
win over `.env`. When it runs you additionally get:

| File | Contents |
| --- | --- |
| `<config>-defconfig` | The minimal form of our config. |
| `output/<flavor>/reference-config` | The reference put through the same toolchain. |
| `output/<flavor>/reference-config-defconfig` | Its minimal form. |
| `output/<flavor>/diff-defconfig` | Minimal-form diff — what the two configs *really* disagree about, with everything implied by dependencies and defaults stripped out. |

Both sides have to go through the same toolchain or the comparison measures the
normalizer rather than the generator. The normalized reference is written to
`output/<flavor>/`, never back over `misc/zabbly-config` — a run must not
rewrite a tracked reference file.

## Other tools

```sh
./check_slices.py           # every flavor; or ./check_slices.py generic
```

Within one flavor, each symbol must be set in exactly one slice. Overlaps are
how ordering bugs get in: whichever fragment loads last silently wins, and the
loser looks like it is doing something when it is not. Flavors are checked
independently — two flavors setting the same symbol differently is the point,
not a conflict. Run this after editing any slice.

```sh
./menuconfig.sh             # browse the tree interactively (Kconfiglib menuconfig)
./fix-config.sh             # the normalization step on its own: put a config
                            # at $KERNEL_TREE_BUILD_PATH/.config first
python3 compare_configs.py <ours> <reference> [missing_out] [changed_out]
./check-config-hardening.sh # run kernel-hardening-checker over the result
                            # (defaults to $GENERATED_CONFIG_PATH; takes an
                            # explicit config path as an argument)
```

The hardening report is informational. This config targets parity with a
general-purpose distro kernel, which is nowhere near a hardened one, so FAIL
lines are expected rather than defects — `check-config-hardening.sh` exits
non-zero only if the checker itself could not run.

## Continuous integration

`.github/workflows/generate-config.yml` runs the whole thing on `ubuntu-latest`
for every push and pull request, once per flavor as a matrix: it installs the
dependencies above, fetches and caches the kernel tree, generates the config,
and publishes it plus `output/<flavor>/` as build artifacts. The diff against
`misc/zabbly-config` and the hardening report both land in the run's job
summary.

Neither is enforced. Note that the runner's compiler differs from the one
`misc/zabbly-config` was built with, so `CC_VERSION_TEXT` and any
gcc-version-gated symbols will show up in the CI diff even when the local diff
is clean.

## Writing or editing a flavor

The structural helpers in `genconfig.py` map onto the three shapes Kconfig
actually uses. Picking the right one for a subsystem is most of the work:

| Kconfig shape | Tool |
| --- | --- |
| `menuconfig X` with nested children | `enable_umbrella(name, value)` — sets **and walks** |
| Flat driver zoo sharing a name prefix | `enable_by_prefix(prefix)` — tristate→m, bool→y |
| Plain `menu "..."` with unrelated contents | `enable_menu(title)` |
| A lone symbol with no family | `enable_exact((name, value), ...)` — sets **without** walking |

Two things that are easy to get wrong, both learned the hard way:

- **Ordering is load-bearing.** Sweeps deliberately overwrite each other — last
  writer wins — and a sweep can only reach a symbol that is already *visible*,
  so gates must be enabled before the families that hang off them. A monotonic
  "never lower an already-set value" rule looks obviously correct and makes
  things measurably worse.
- **Set vs. walk is a real distinction.** `enable_umbrella` on a gate whose
  subtree you don't actually want (`STAGING`, `ACCESSIBILITY`) drags the whole
  subtree in. Use `enable_exact` to make a subtree merely *reachable*.

Values are tristate integers throughout: `0` = n, `1` = m, `2` = y.

Symbols with no prompt ignore user values entirely — they take
`max(defaults, selects)` — so setting one from data is decorative. If a symbol
refuses to stick, it is usually an ordering or visibility problem rather than a
promptless one.
