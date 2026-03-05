# AUR package files for `hiresti`

This directory is the local source of truth for the AUR package metadata.

## Update workflow

1. Bump `pkgver` in [`PKGBUILD`](./PKGBUILD).
2. Recompute the source tarball checksum:

   ```bash
   curl -L "https://github.com/yelanxin/hiresTI/archive/refs/tags/v${pkgver}.tar.gz" | sha256sum
   ```

   If the upstream release tag is wrong or missing, pin `_commit` in `PKGBUILD`
   to the intended release commit, recompute the checksum from
   `https://github.com/yelanxin/hiresTI/archive/${_commit}.tar.gz`, and bump
   `pkgrel`.

   When pinning `_commit` for an existing `pkgver`, keep the `source` filename
   unique as well. Reusing `hiresti-${pkgver}.tar.gz` will collide with an
   older cached tag archive in `makepkg` and produce a false checksum failure.

3. Regenerate `.SRCINFO` on an Arch machine:

   ```bash
   makepkg --printsrcinfo > .SRCINFO
   ```

## First push to AUR

```bash
git clone ssh://aur@aur.archlinux.org/hiresti.git /tmp/hiresti-aur
cp PKGBUILD .SRCINFO /tmp/hiresti-aur/
cd /tmp/hiresti-aur
git add PKGBUILD .SRCINFO
git commit -m "Initial import"
git push origin master
```

## Later updates

```bash
cd /tmp/hiresti-aur
cp /path/to/hiresTI/aur/hiresti/PKGBUILD .
cp /path/to/hiresTI/aur/hiresti/.SRCINFO .
git add PKGBUILD .SRCINFO
git commit -m "Update to 1.4.9"
git push origin master
```
