# vimvibe RPM: repackages the release tarball (compiled core + Python overlay), so building needs no Rust.
# Build with packaging/make-rpm.sh (Fedora container) or: rpmbuild -bb --define "_sourcedir <dir with the tarball>" vimvibe.spec
%global debug_package %{nil}
%global __strip /bin/true

Name:           vimvibe
Version:        %{?vv_version}%{!?vv_version:2.1.1}
Release:        1%{?dist}
Summary:        Keyboard-driven "click anything by typing its name" overlay for KDE Plasma (Wayland)
License:        MIT
URL:            https://github.com/OverRevvv/vimvibe
Source0:        vimvibe-%{version}-linux-x86_64.tar.gz
ExclusiveArch:  x86_64

Requires:       python3-pyside6
Requires:       layer-shell-qt
Requires:       glib2
Requires:       systemd
# OCR labels for apps that expose nothing to accessibility
Recommends:     spectacle
Recommends:     tesseract

%description
vimvibe labels every button, tab, link and menu item of the focused window; type a few letters of its name and
press Enter to click it. Also has a keyboard mouse (grid and H J K L movement), scrolling, text-field jumping like
Vimium, and OCR and grid fallbacks for apps without an accessibility tree.

%prep
%setup -q -n vimvibe-%{version}-linux-x86_64

%build
# nothing to build: the tarball ships the compiled core

%install
install -Dm755 vimvibe-core %{buildroot}%{_bindir}/vimvibe-core
# the launcher template carries @CORE@ / @PALETTE_DIR@ placeholders for where the files ended up
sed -e 's|@CORE@|%{_bindir}/vimvibe-core|' -e 's|@PALETTE_DIR@|%{_datadir}/vimvibe|' packaging/vimvibe > vimvibe.launcher
install -Dm755 vimvibe.launcher %{buildroot}%{_bindir}/vimvibe
for f in palette/vimvibe_*.py; do install -Dm644 "$f" %{buildroot}%{_datadir}/vimvibe/$(basename "$f"); done
install -Dm644 packaging/icons/vimvibe.svg %{buildroot}%{_datadir}/vimvibe/vimvibe.svg
mkdir -p %{buildroot}%{_datadir}/icons
cp -r packaging/icons/hicolor %{buildroot}%{_datadir}/icons/
printf '[Desktop Entry]\nType=Application\nName=vimvibe Settings\nComment=Click anything by typing its name\nExec=vimvibe settings\nIcon=vimvibe\nCategories=Utility;Accessibility;\n' > vimvibe.desktop
install -Dm644 vimvibe.desktop %{buildroot}%{_datadir}/applications/vimvibe.desktop

%files
%doc README.md
%license LICENSE
%{_bindir}/vimvibe
%{_bindir}/vimvibe-core
%{_datadir}/vimvibe/
%{_datadir}/icons/hicolor/*/apps/vimvibe.*
%{_datadir}/applications/vimvibe.desktop

%changelog
* Sat Oct 24 2026 OverRevvv <rdude1612@gmail.com> - 2.1.1-1
- Real pointer clicks, Enter twice double-clicks, MIT license

* Fri Oct 23 2026 OverRevvv <rdude1612@gmail.com> - 2.1.0-1
- Initial package
