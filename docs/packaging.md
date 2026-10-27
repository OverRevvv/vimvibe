# Installing on your distro, and how the packages are made

vimvibe needs **KDE Plasma 6 on Wayland**. Every package below contains the same files and the same static core. Pick
the one for your distro from the [releases page](https://github.com/OverRevvv/vimvibe/releases), or use the tarball on
any distro.

## Install

| Distro | Package | Install |
|---|---|---|
| Fedora (KDE spin, or Plasma on Fedora) | `vimvibe-<v>-1.fcNN.x86_64.rpm` | `sudo dnf install ./vimvibe-*.fc*.rpm` |
| openSUSE Tumbleweed | `vimvibe-<v>-1.opensuse.x86_64.rpm` | `sudo zypper install --allow-unsigned-rpm ./vimvibe-*.opensuse.*.rpm` |
| Debian 13 (trixie) and later, Ubuntu / Kubuntu 25.10 and later | `vimvibe_<v>_amd64.deb` | `sudo apt install ./vimvibe_*_amd64.deb` |
| Arch, Manjaro, EndeavourOS | `vimvibe-bin` (AUR), or `vimvibe-bin-<v>-1-x86_64.pkg.tar.zst` | `yay -S vimvibe-bin`, or `sudo pacman -U ./vimvibe-bin-*.pkg.tar.zst` |
| Any other distro | `vimvibe-<v>-linux-x86_64.tar.gz` | unpack, then `./install.sh` (installs for your user; tells you what to install from your distro) |

The package manager pulls in what vimvibe needs: Python 3 with PySide6 (Qt 6), layer-shell-qt (keeps the overlay above
popups and menus), and gdbus. spectacle and tesseract are recommended: they give apps without an accessibility tree OCR
labels and power text mode.

Then, as your user:

```bash
vimvibe start          # starts it (and turns desktop accessibility on); restart the apps you want to use
vimvibe doctor         # checks the setup
```

*Launch at login* is in `vimvibe settings`. Remove it again with your package manager (or `./install.sh --uninstall`
for the tarball); your settings in `~/.config/vimvibe/` stay.

**Ubuntu 24.04 / Kubuntu 24.04** is not supported: it ships Plasma 5, has no PySide6 packages, and only the Qt 5
layer-shell-qt (the `.deb` refuses to install there, measured). **Debian 12** likewise has Plasma 5.

## Dependency names per distro

Checked in clean containers of each distro (see *How the packages are checked* below):

| Needed for | Fedora | openSUSE Tumbleweed | Debian 13 / Ubuntu 26.04 | Arch |
|---|---|---|---|---|
| the overlay (Python + Qt 6) | `python3-pyside6` | `python3-pyside6` (provided by `python313-pyside6`) | `python3-pyside6.qtcore`, `.qtgui`, `.qtwidgets`, `.qtdbus` | `pyside6` |
| staying above popups | `layer-shell-qt` | `libLayerShellQtInterface6` | `liblayershellqtinterface6` | `layer-shell-qt` |
| `gdbus` | `glib2` | `glib2-tools` | `libglib2.0-bin` | `glib2` |
| OCR and text mode (recommended) | `spectacle`, `tesseract`, `tesseract-langpack-eng` | `spectacle`, `tesseract-ocr`, `tesseract-ocr-traineddata-english` | `kde-spectacle`, `tesseract-ocr`, `tesseract-ocr-eng` | `spectacle`, `tesseract`, `tesseract-data-eng` |

## How the packages are made

One release tarball is the source of every package, and one script lays the files out for all of them, so the
packages can't drift apart:

```
packaging/make-tarball.sh     the tarball: static core + overlay + installer (+ stage.sh)
packaging/stage.sh            the install layout every package uses (/usr/bin, /usr/share/vimvibe, icons, .desktop)
packaging/deb/make-deb.sh     .deb with dpkg-deb (directly, or in a debian:stable container)
packaging/make-rpm.sh [fedora|opensuse]   .rpm with rpmbuild in a container of that distro (packaging/rpm/vimvibe.spec)
packaging/arch/make-arch.sh   Arch package with makepkg in an archlinux container, plus dist/aur/PKGBUILD and .SRCINFO
```

**The core is static (musl).** A core built on a new Fedora links against its new glibc and would not start on older
distros. `make-tarball.sh` therefore builds it for `x86_64-unknown-linux-musl`: with the musl target if installed
(the CI way: `rustup target add x86_64-unknown-linux-musl` and `musl-tools`), else inside `rust:1-alpine` with podman or
docker. The static core was checked on the developer desktop against the session bus, KWin, the accessibility bus and
the RemoteDesktop portal (open, close, global shortcuts, pointer).

**Releases.** Pushing a `v*` tag runs `.github/workflows/release.yml`, which builds all of the above on GitHub and
attaches them to the release together with `SHA256SUMS`, `aur-PKGBUILD` and `aur-SRCINFO`.

**Publishing to the AUR** (once the release exists, because the AUR package downloads the tarball from it):

```bash
git clone ssh://aur@aur.archlinux.org/vimvibe-bin.git && cd vimvibe-bin
curl -LO https://github.com/OverRevvv/vimvibe/releases/download/vX.Y.Z/aur-PKGBUILD && mv aur-PKGBUILD PKGBUILD
curl -LO https://github.com/OverRevvv/vimvibe/releases/download/vX.Y.Z/aur-SRCINFO && mv aur-SRCINFO .SRCINFO
git add PKGBUILD .SRCINFO && git commit -m "vimvibe X.Y.Z" && git push
```

## How the packages are checked

Every package is installed in a clean container of its distro, with the package manager resolving the dependencies,
and must pass:

```bash
vimvibe version && vimvibe-core --version
python3 -c 'import PySide6.QtWidgets, PySide6.QtDBus, ctypes; ctypes.CDLL("libLayerShellQtInterface.so.6")'
python3 /usr/share/vimvibe/vimvibe_palette.py --export /tmp/s.json     # the overlay's Python code runs
test -f /usr/share/applications/vimvibe.desktop
```

For example: `podman run --rm -v "$PWD/dist:/d:Z" debian:trixie bash -c "apt-get update && apt-get install -y /d/vimvibe_*_amd64.deb && vimvibe version"`.
A container has no desktop, so this proves the package installs, its dependencies resolve and the code loads; using
vimvibe itself still needs a Plasma session (see CONTRIBUTING.md → *Testing by hand*).
