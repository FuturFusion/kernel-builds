# Out-of-tree patches

Some fixes we need aren't upstream (yet, or ever) and have to be carried as
patches applied on top of the kernel source tree before config generation
and before building.

## Layout

```
patches/<series>/NNNN-slug.patch
```

`<series>` is `major.minor` (e.g. `7.2`), the same granularity as
`misc/<series>/reference-<arch>-config`. A patch lives at the series level,
**not** the exact point version: a maintenance bump (7.2.11 -> 7.2.12) reuses
`patches/7.2/` as-is, no copying needed. Only moving to a new series
(7.2 -> 7.3) needs a new directory -- see "Next-series" below.

Files are plain unified diffs in git's format (`a/path` / `b/path`), applied
with `patch -p1`. The easiest way to add one from an upstream/zabbly commit:

```
curl -L https://github.com/<repo>/commit/<sha>.patch -o patches/<series>/NNNN-slug.patch
```

Number patches `0001-`, `0002-`, ... in the order they must apply.

## How they get applied

`scripts/apply-kernel-patches.sh <kernel-tree-path> <series>` applies every
`patches/<series>/*.patch` to the tree, in filename order. It's a no-op if
the directory doesn't exist. A little context drift is fine -- but if a
patch turns out to already be applied to the tree (it likely landed
upstream), that's a hard failure, not a silent skip: a maintainer needs to
drop it from `patches/<series>/`. It's called automatically:

- Before every release build (`_build-kernel.yml`) -- **fatal** if a patch
  fails to apply; a build can't ship without a patch it's supposed to carry.
- Before CI's own config-validation checks (`setup-kernel-tree`, used by
  `generate-config.yml`) -- also fatal, which is what blocks
  `auto-merge-config.yml` from merging a config PR whose patches don't apply.
- Before config generation for a version PR (`generate-configs`, used by
  `check-new-stable-release.yml`) -- **not fatal** here: the PR still gets
  opened/updated and generation still runs against the unpatched tree
  either way, and a comment is posted on the PR with the raw
  patch-application output so a maintainer knows to fix it. The PR's own CI check
  above is what actually blocks auto-merge. (If a patch ever does touch
  Kconfig, a failed apply means the generated config in that PR is missing
  whatever the patch would have changed there too -- the comment and the
  failing CI check are both still your signal to not trust/merge it as-is.)

## Local/manual use

`genconfig.sh` does not apply patches to your own `KERNEL_TREE_PATH` --
that tree is yours to manage. If you're building for real with a local tree,
apply `patches/<series>/*.patch` yourself first.

## Next-series

When `check-new-stable-release.yml`'s next-series job first sees a new
series, it copies `patches/<old-series>/` to `patches/<new-series>/`
verbatim (only if the new directory doesn't exist yet, so it won't clobber
manual edits on a later force-update of the same draft). Next-series PRs are
never auto-merged anyway, so the reviewer is expected to check the patch
still applies (CI will fail loudly if not) and trim/update/drop it as
appropriate before merging.
