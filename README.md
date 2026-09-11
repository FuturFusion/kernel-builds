# dotconfig_gen

Generate a Linux kernel `.config` programmatically, by walking the Kconfig tree
with [Kconfiglib](https://github.com/ulfalizer/Kconfiglib) instead of
hand-maintaining a 13 000-line config file.

The idea is to express configuration as *structure* wherever possible: "enable
this whole driver family as modules", "walk this menu", and fall back to
per-symbol data only where a symbol genuinely has no family, gate or prefix to
hang off. The generic flavor currently reproduces a real distro kernel config
([zabbly](https://github.com/zabbly/linux)'s x86_64 build) with a diff of zero,
which is what makes the machinery trustworthy enough to build other kernels
with.

## Layout

| Path | What it is |
| --- | --- |
| `genconfig.py` | The library: Kconfig tree-walking machinery. Sets no symbols; not runnable on its own. |
| `flavors/<name>/config.py` | A *flavor*: the policy for one kernel, that is, what to switch on and why. |
| `flavors/<name>/config_slices/*.config` | The data half of that flavor: per-symbol policy no structural sweep can express. |
| `genconfig.sh` | Entry point: `./genconfig.sh <arch> <flavor>`, both required. `<arch>` is a line from `arches` (`amd64`/`arm64`). |
| `arches` | Architectures the tooling targets, one per line; every pipeline iterates it. |
| `kconf-run.sh` | Runs any Kconfiglib script/tool against a kernel tree (what `make scriptconfig` would set up). |
| `configs/<version>/<flavor>-<arch>-config` | A committed, reviewed generated config (plus `-defconfig`), one per flavor per arch per tracked kernel version. |
| `misc/<series>/reference-<arch>-config` | The reference config `generic` aims to reproduce, one per kernel series per arch. Neither input nor output: it's how the result is judged. |

A flavor is a self-contained directory: `flavors/<name>/config.py` plus
`flavors/<name>/config_slices/`. Adding one requires no changes to
`genconfig.py`:

```
flavors/
  generic/
    config.py
    config_slices/
      block_devices.config
      containers.config
      ...
  server/
    config.py
    config_slices/
      ...
```

### The flavors

| Flavor | Purpose |
| --- | --- |
| `generic` | Full-featured distro kernel. Reproduces `misc/<series>/reference-<arch>-config` exactly; a diff of zero is the goal, and any line in it is a defect. |
| `server` | Hypervisor/container host kernel for x86_64 servers. **Currently a verbatim copy of `generic`**, used as a starting point, so that divergence shows up commit by commit rather than as one unreviewable drop. |

Both are judged against `misc/<series>/reference-<arch>-config`, where `<series>`
comes from `KERNEL_TREE_PATH`'s own version, and `<arch>` from the `genconfig.sh`
argument. There's no flavor-specific reference; read the diff per flavor
instead: zero lines is success for `generic`, while for a flavor that
deliberately strips things a large diff means it's doing its job.

The comparison itself is opt-in, via `--validate` (see [Usage](#usage)):
plain generation needs no reference at all. `--validate` fails fast if that
exact (series, arch) reference doesn't exist, rather than comparing against
the wrong one.

## Prerequisites

**1. Submodules.** Kconfiglib comes from the `yocto-kernel-tools` submodule:

```sh
git submodule update --init --recursive
```

**2. A kernel source tree.** You need a checkout of the kernel you are
configuring, somewhere on disk; this repo does not ship or fetch one. The
generated config is only meaningful for the tree it was generated against, since
symbol names, defaults and dependencies all change between releases.

```sh
git clone --depth 1 https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git ~/src/linux
```

**3. Standard kernel build dependencies.** Even though nothing is compiled here,
the tooling shells out to the kernel's own `make` and probes the toolchain the
same way Kconfig does (`CC_VERSION_TEXT`, `PAHOLE_VERSION`, etc.), so the usual set
has to be present:

```sh
# Debian / Ubuntu
sudo apt install build-essential flex bison bc libelf-dev libssl-dev \
                 dwarves python3
```

`dwarves` provides `pahole`, which gates `DEBUG_INFO_BTF` and everything
downstream of it. Note that `kconf-run.sh` currently hardcodes
`PAHOLE_VERSION=130` as a temporary workaround for build hosts without pahole
installed; drop that override once you have pahole >= 1.26.

**4. Your `.env`.** The tooling reads a `.env` file that is deliberately not in
git, because the paths are per-machine. Create it from the template before
running anything:

```sh
cp .env.example .env
$EDITOR .env
```

| Variable | Meaning |
| --- | --- |
| `GENERATED_CONFIG_PATH` | Base name for the generated config. `genconfig.sh` always appends `-<flavor>-<arch>`, so no flavor or arch can clobber another's output. |
| `KERNEL_TREE_PATH` | Your kernel source checkout. |
| `KERNEL_TREE_BUILD_PATH` | Scratch `O=` build directory, used only by normalization. |
| `NORMALIZE_CONFIG` | `true`/`false` (default `false`). See [Normalization](#normalization). |
| `VALIDATE_CONFIG` | `true`/`false` (default `false`). Whether to compare the result against `misc/<series>/reference-<arch>-config`. Off by default: generating a config doesn't need a reference at all, only this comparison does. |

## Usage

Run from the repository root:

```sh
./genconfig.sh amd64 generic            # arch and flavor are both required, no defaults
./genconfig.sh amd64 server             # any flavor under flavors/
./genconfig.sh arm64 generic            # arch selects the seed defconfig + kernel ARCH
./genconfig.sh amd64 generic --validate # also compare against the reference config
./genconfig.sh --help                   # flags and defaults
```

`<arch>` picks the seed defconfig (`amd64` -> `arch/x86/configs/x86_64_defconfig`,
`arm64` -> `arch/arm64/configs/defconfig`) and the `ARCH` Kconfig is evaluated
for; `<flavor>` picks `flavors/<flavor>/config.py`.

By default this writes `generated_config-<flavor>-<arch>` and stops; no
reference required. Pass `--validate` (or `VALIDATE_CONFIG=true` in `.env`)
to also compare against `misc/<series>/reference-<arch>-config`, leaving the
analysis in `output/<flavor>/<arch>/`. Without `--validate`, that directory
still gets `capped_symbols.txt` (a diagnostic of the generator's own sweep),
but none of the reference-comparison files below:

| File | Contents |
| --- | --- |
| `output/<flavor>/<arch>/diff` | Side-by-side diff against the reference config. |
| `output/<flavor>/<arch>/missing_from_ours.txt` | Symbols the reference enables that we don't. |
| `output/<flavor>/<arch>/changed_from_ours.txt` | Symbols where the two configs disagree. |
| `output/<flavor>/<arch>/capped_symbols.txt` | Assignments the walker attempted that were silently capped by an unmet dependency. |

Most of `capped_symbols.txt` is expected noise: drivers for hardware that
cannot exist on x86_64 get "capped" quite correctly. `cross_reference.py` (run
automatically by `genconfig.sh`) intersects it with the missing-vs-reference
list to surface only the genuine gaps.

To add a flavor, copy an existing one and start editing:

```sh
cp -r flavors/generic flavors/server    # then trim flavors/server/
./genconfig.sh amd64 server
```

A flavor loads the `config_slices/` sitting next to it. `config.py` derives its
own name from its directory, so a copy needs no edit to point at the right
fragments.

## Normalization

By default the generator stops at what Kconfiglib produced. Normalization runs
the result through the kernel's *real* Kconfig afterwards: `make olddefconfig`
to expand it, and `make savedefconfig` to reduce it to its minimal form. This is
the authoritative check that the config is one the kernel itself would accept.

It is opt-in because it is the one part of the tooling that needs a working
kernel build environment: without flex and bison you get nothing generated at
all, so requiring them for everyone would be a steep price for an optional
verification step.

```sh
./genconfig.sh amd64 generic --normalize      # this run only
./genconfig.sh amd64 generic --no-normalize   # this run only, even if .env asks for it
```

Set `NORMALIZE_CONFIG=true` in `.env` to make it the default; the flags always
win over `.env`. Normalizing our own config happens whenever `--normalize` is
on, whether `--validate` is used or not: a real build (e.g. a `.deb`) needs it either way:

| File | Contents |
| --- | --- |
| `<config>-defconfig` | The minimal form of our config. |

Combine `--normalize` with `--validate` to also normalize the reference side
and get the minimal-form comparison:

| File | Contents |
| --- | --- |
| `output/<flavor>/<arch>/reference-config` | The reference put through the same toolchain. |
| `output/<flavor>/<arch>/reference-config-defconfig` | Its minimal form. |
| `output/<flavor>/<arch>/diff-defconfig` | Minimal-form diff: what the two configs *really* disagree about, with everything implied by dependencies and defaults stripped out. |

Both sides go through the same toolchain, or the comparison measures the
normalizer rather than the generator. The normalized reference is written to
`output/<flavor>/<arch>/`, never back over the tracked reference file.

## Other tools

```sh
./check_slices.py           # every flavor; or ./check_slices.py generic
```

Within one flavor, each symbol must be set in exactly one slice. Overlaps are
how ordering bugs get in: whichever fragment loads last silently wins, and the
loser looks like it is doing something when it is not. Flavors are checked
independently: two flavors setting the same symbol differently is the point,
not a conflict. Run this after editing any slice.

```sh
./menuconfig.sh             # browse the tree interactively (Kconfiglib menuconfig)
./normalize-config.sh <input-config> <output-config> <output-defconfig>
                            # the normalization step on its own; set
                            # KERNEL_ARCH (x86_64 / arm64) for a cross target
python3 compare_configs.py <ours> <reference> [missing_out] [changed_out]
./check-config-hardening.sh # run kernel-hardening-checker over the result
                            # (defaults to $GENERATED_CONFIG_PATH; takes an
                            # explicit config path as an argument)
```

The hardening report is informational. This config targets parity with a
general-purpose distro kernel, which is nowhere near a hardened one, so FAIL
lines are expected rather than defects. `check-config-hardening.sh` exits
non-zero only if the checker itself could not run.

## Continuous integration

`.github/workflows/generate-config.yml` runs on `ubuntu-latest` for every push
and pull request, with two matrix jobs that discover their own axes (so a new
reference, flavor, or arch needs no workflow edit):

- **`reference-diff`**: checks how closely the config matches, one leg per `(series, arch)` that has a
  reference, always **generic** (the only flavor that aims to reproduce one).
  Diffs against the reference; lands in the job summary.
- **`all-flavors`**: coverage, one leg per **(flavor, arch)**, all against the
  newest tracked `configs/<x>` version. Covers every flavor including
  `.noautomation` ones (that marker only opts out of the *downstream*
  automation) and every arch. No reference diff, just checks that generation
  succeeds.

Both jobs cache the kernel source tree per version, run the hardening report
into the job summary, and publish the config plus `output/<flavor>/<arch>/` as
an artifact. Nothing here is enforced against a target: the runner's compiler
differs from the one each reference was built with, so `CC_VERSION_TEXT` and
gcc-version-gated symbols show up in `reference-diff` even when otherwise clean.

### Building a `.deb`

`.github/workflows/build-deb.yml` is a separate, manually-triggered workflow
(`workflow_dispatch` only: it never runs on push or pull request) that
packages an actual kernel with `make bindeb-pkg`. It prompts for a precise
kernel version (e.g. `6.19.4`, not just a series) and a flavor, and runs as a
matrix over target distros: `debian-12`, `debian-13`, `ubuntu-24.04`.

Each target builds inside its own container (via `podman`, preinstalled on
the GitHub-hosted runner image, so there's nothing to set up) rather than on the
runner's own Ubuntu directly. That's not just packaging convenience: this
repo's own tooling probes the toolchain at generation time
(`CC_VERSION_TEXT`, `PAHOLE_VERSION`), so config generation has to happen
inside the same container as the build, or the config could end up gated on
a different compiler/pahole than the one actually building the kernel.
Config generation, `make bindeb-pkg`, and package collection all run as one
script inside each container; only the checkout, the cached kernel source
tree, and a directory for the finished `.deb`s are bind-mounted in.

It's kept separate and manual on purpose: packaging a real kernel, three
times over, once per target, is far heavier than generating a config, and
disk space in particular is tight on GitHub-hosted runners once container
storage is added on top of the build's own object files and debug info.

### New stable release -> PR -> tag -> build

`.github/workflows/check-new-stable-release.yml` runs on a schedule and looks
at every version kernel.org currently calls `stable`, which can be two
release lines at once (e.g. `7.1.13` and `7.2.3` while `7.1` winds down). The
series of the newest `configs/<x>` is "the series we track"; each stable
version is then one of:

- **Maintenance**: a newer point release *in the tracked series*. Regular PR
  on `kernel-config/v<version>`, per-(flavor, arch) diffs against the previous
  tracked version as comments. This is the PR `auto-merge-config.yml` may merge
  on its own (below).
- **Next series**: a version in a series *newer* than the tracked one. Draft
  PR on `kernel-config/v<series>.x`, one branch reused for the whole series,
  diffed against the newest `configs/<x>` regardless of series. Never
  auto-merged: a manual review covers the (large, cross-series) diff, merges it, and
  pushes the `v<version>-1` tag themselves. When a newer point release in that
  series appears, the same draft PR is force-updated to it (a
  `<!-- next-series: X.Y.Z -->` marker in the PR body tracks the current
  target) with fresh diff comments.
- **Older**: ignored.

The download / generate / diff steps shared by both PR paths live in the
composite action `.github/actions/generate-configs`, which generates
`configs/<version>/<flavor>-<arch>-config` for every flavor times every arch in
`arches`.

`.github/workflows/auto-merge-config.yml` then runs (off that workflow
completing, since a PR opened by `GITHUB_TOKEN` triggers nothing itself). It
only ever considers a ready-for-review PR whose branch is a strict
`v<major>.<minor>.<patch>` (so the next-series draft is never touched), and
decides whether that PR is trivial:

- **Same series**: there must already be a `configs/<same-series>.*` to diff
  against. A new series (`7.1.x` -> `7.2.0`) is always left for manual review.
- **Toolchain-only**: across every flavor and arch, every config symbol that
  changed vs. that previous version must be toolchain/version bookkeeping
  (`CONFIG_CC_*`, `CONFIG_GCC*`, `CONFIG_CLANG*`, `CONFIG_LD_*`, `CONFIG_AS_*`,
  `CONFIG_PAHOLE*`, `CONFIG_RUST*`, `CONFIG_TOOLCHAIN_*`; the `allow_re` in
  that workflow is the single lever). Any other changed symbol (a module or
  feature that turned on or off) blocks the auto-merge.
- **CI green**: every check reported on the PR's head commit (`lint.yml`,
  `generate-config.yml`) must have completed with a passing conclusion. No
  checks yet, any still running, or any failed all block the auto-merge; a
  content-clean PR just gets a "waiting on CI" comment instead and is
  re-evaluated on the next run.

If all three hold, it merges the PR, pushes `v<version>-1`, and calls
`_release.yml` directly to build and release (a `GITHUB_TOKEN` tag push does
not trigger `release-on-tag.yml`). Otherwise it just comments why and leaves
the PR for manual review, and the reviewer merges it and pushes the tag themselves.

`.github/workflows/release-on-tag.yml` is the manual entry point: pushing any
`v<version>-N` tag (a first release, or a `-2` re-spin of the same kernel)
runs the same `_release.yml`. It also has a `workflow_dispatch` to re-run a
release for a tag that already exists.

## Writing or editing a flavor

A flavor is the directory `flavors/<name>/`: `config.py` (the policy) plus
`config_slices/*.config` (the data). Creating that directory is all it takes
for `./genconfig.sh <arch> <name>` and every discovery-driven workflow to pick
it up. To keep a work-in-progress or special-purpose flavor out of the
downstream automation (new-release config generation, PRs, release builds)
while still building it by hand, add an empty `flavors/<name>/.noautomation`
file. It stays in the `generate-config.yml` CI matrix either way: a flavor
that no longer builds cleanly should be seen there, not hidden.

The structural helpers in `genconfig.py` map onto the three shapes Kconfig
actually uses. Picking the right one for a subsystem is most of the work:

| Kconfig shape | Tool |
| --- | --- |
| `menuconfig X` with nested children | `enable_umbrella(name, value)`: sets **and walks** |
| Flat driver zoo sharing a name prefix | `enable_by_prefix(prefix)`: tristate->m, bool->y |
| Plain `menu "..."` with unrelated contents | `enable_menu(title)` |
| A lone symbol with no family | `enable_exact((name, value), ...)`: sets **without** walking |

Two things that are easy to get wrong, both learned the hard way:

- **Ordering is load-bearing.** Sweeps deliberately overwrite each other; the last
  writer wins, and a sweep can only reach a symbol that is already *visible*,
  so gates must be enabled before the families that hang off them. A monotonic
  "never lower an already-set value" rule looks obviously correct and makes
  things measurably worse.
- **Set vs. walk is a real distinction.** `enable_umbrella` on a gate whose
  subtree you don't actually want (`STAGING`, `ACCESSIBILITY`) drags the whole
  subtree in. Use `enable_exact` to make a subtree merely *reachable*.

Values are tristate integers throughout: `0` = n, `1` = m, `2` = y.

Symbols with no prompt ignore user values entirely; they take
`max(defaults, selects)`, so setting one from data is decorative. If a symbol
refuses to stick, it is usually an ordering or visibility problem rather than a
promptless one.
