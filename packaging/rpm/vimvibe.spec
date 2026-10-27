# vimvibe RPM (Fedora and openSUSE): repackages the release tarball (static core + Python overlay), so building needs
# no Rust. Build with packaging/make-rpm.sh [fedora|opensuse] (in a container of that distro) or:
#   rpmbuild -bb --define "_sourcedir <dir with the tarball>" vimvibe.spec
%global debug_package %{nil}
%global __strip /bin/true

Name:           vimvibe
Version:        %{?vv_version}%{!?vv_version:3.1.1}
Release:        1%{?dist}
Summary:        Keyboard-driven "click anything by typing its name" overlay for KDE Plasma (Wayland)
License:        MIT
URL:            https://github.com/OverRevvv/vimvibe
Source0:        vimvibe-%{version}-linux-x86_64.tar.gz
ExclusiveArch:  x86_64

# Dependency names differ per distro (checked on Fedora 44 and openSUSE Tumbleweed, see docs/packaging.md).
# python3-pyside6 is provided on both (openSUSE's python313-pyside6 provides it).
Requires:       python3-pyside6
%if 0%{?suse_version}
Requires:       libLayerShellQtInterface6
Requires:       glib2-tools
Recommends:     spectacle
Recommends:     tesseract-ocr
Recommends:     tesseract-ocr-traineddata-english
%else
Requires:       layer-shell-qt
Requires:       glib2
# OCR labels and text mode
Recommends:     spectacle
Recommends:     tesseract
Recommends:     tesseract-langpack-eng
%endif

%description
vimvibe labels every button, tab, link and menu item of the focused window; type a few letters of its name and
press Enter to click it. Also has a keyboard mouse (grid and H J K L movement), scrolling, text-field jumping like
Vimium, and OCR and grid fallbacks for apps without an accessibility tree.

%prep
%setup -q -n vimvibe-%{version}-linux-x86_64

%build
# nothing to build: the tarball ships the compiled core

%install
# the same layout as every other package (packaging/stage.sh, shipped in the tarball)
./packaging/stage.sh . %{buildroot} %{_prefix}
# the RPM tags the docs and licence itself (%doc / %license below)
rm -rf %{buildroot}%{_datadir}/doc/vimvibe %{buildroot}%{_datadir}/licenses/vimvibe

%files
%doc README.md
%license LICENSE
%{_bindir}/vimvibe
%{_bindir}/vimvibe-core
%{_datadir}/vimvibe/
%{_datadir}/icons/hicolor/*/apps/vimvibe.*
%{_datadir}/applications/vimvibe.desktop

%changelog
* Mon Oct 26 2026 OverRevvv <rdude1612@gmail.com> - 3.1.1-1
- Clicks from the mouse modes reach the app; keep popups open (Meta+Shift+Alt+Space); Chrome click offset

* Sat Oct 24 2026 OverRevvv <rdude1612@gmail.com> - 3.1.0-1
- Text mode: scrolling with Space chords, copying across many screens

* Sat Oct 24 2026 OverRevvv <rdude1612@gmail.com> - 3.0.0-1
- Text mode (Ctrl+T), mode cycling, settings export/import, Space-scroll fix

* Sat Oct 24 2026 OverRevvv <rdude1612@gmail.com> - 2.1.2-1
- Ctrl+I finds and cycles text fields in every mode

* Sat Oct 24 2026 OverRevvv <rdude1612@gmail.com> - 2.1.1-1
- Real pointer clicks, Enter twice double-clicks, MIT license

* Fri Oct 23 2026 OverRevvv <rdude1612@gmail.com> - 2.1.0-1
- Initial package
