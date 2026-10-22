%global appdir %{_prefix}/lib/deepcool-control
# systemd-rpm-macros defines this on Fedora, but keep the spec usable in
# minimal build roots where the macro package is not installed.
%{!?_udevrulesdir:%global _udevrulesdir %{_prefix}/lib/udev/rules.d}

Name:           deepcool-control
Version:        1.2.3
Release:        1
Summary:        Native GTK4 app for DeepCool CH-series displays and case lighting

License:        MIT
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  desktop-file-utils

Requires:       gtk4
Requires:       libadwaita
Requires:       python3
Requires:       python3-gobject
Requires:       python3-psutil
Recommends:     openrgb

%description
DeepCool Control is a native GTK4/libadwaita app for DeepCool CH-series
digital case displays. It reads CPU and GPU temperature and utilisation
locally and drives the two three-digit readouts and ten-cell load bars over
USB HID.

Case and motherboard ARGB can be controlled from the Lighting page. MSI
Mystic Light boards are driven through a native HID backend; other
controllers use OpenRGB.

Supported displays include CH360 DIGITAL, CH560 DIGITAL and MORPHEUS.

This is an independent educational project and is not affiliated with
DeepCool.

%prep
%autosetup

%build
# Pure-Python application; no compilation is required.

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{appdir}
install -d %{buildroot}%{_datadir}/applications
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -d %{buildroot}%{_udevrulesdir}

cp -a src/deepcool_control %{buildroot}%{appdir}/deepcool_control
find %{buildroot}%{appdir}/deepcool_control -type d -name __pycache__ -prune -exec rm -rf {} +

cat > %{buildroot}%{_bindir}/deepcool-control <<'EOF'
#!/bin/sh
set -eu
export PYTHONPATH="%{appdir}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m deepcool_control "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/deepcool-control

install -m 0644 data/io.github.deepcool.Control.desktop \
  %{buildroot}%{_datadir}/applications/io.github.deepcool.Control.desktop
install -m 0644 data/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg \
  %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg
install -m 0644 data/99-deepcool-digital.rules \
  %{buildroot}%{_udevrulesdir}/99-deepcool-digital.rules
install -m 0644 data/99-deepcool-msi-mystic-light.rules \
  %{buildroot}%{_udevrulesdir}/99-deepcool-msi-mystic-light.rules

%check
desktop-file-validate data/io.github.deepcool.Control.desktop
%{python3} -m unittest discover -s tests -v

%post
if [ -x /usr/bin/udevadm ]; then
  /usr/bin/udevadm control --reload-rules || :
  /usr/bin/udevadm trigger --action=add --subsystem-match=hidraw || :
fi

%postun
if [ -x /usr/bin/udevadm ]; then
  /usr/bin/udevadm control --reload-rules || :
  /usr/bin/udevadm trigger --action=add --subsystem-match=hidraw || :
fi

%files
%license LICENSE
%doc README.md
%{_bindir}/deepcool-control
%{appdir}
%{_datadir}/applications/io.github.deepcool.Control.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.deepcool.Control.svg
%{_udevrulesdir}/99-deepcool-digital.rules
%{_udevrulesdir}/99-deepcool-msi-mystic-light.rules

%changelog
* Thu Oct 22 2026 DeepCool Linux contributors - 1.2.3-1
- Keep the display and native MSI lighting running through the background service

* Thu Oct 22 2026 DeepCool Linux contributors - 1.2.2-1
- Use a native MSI Mystic Light HID backend on MS-7D77 and render effects on the host

* Thu Oct 22 2026 DeepCool Linux contributors - 1.2.1-1
- Guard MSI Mystic Light writes with a safe mode, risk confirmation, and command log

* Thu Oct 22 2026 DeepCool Linux contributors - 1.2.0-1
- Add case and motherboard ARGB control through OpenRGB

* Thu Oct 22 2026 DeepCool Linux contributors - 1.1.3-1
- Reload display settings changed in the GUI while the background service runs

* Thu Oct 22 2026 DeepCool Linux contributors - 1.1.2-1
- Restart the background display daemon automatically and without a retry limit

* Thu Oct 22 2026 DeepCool Linux contributors - 1.1.1-1
- Keep the display update timer alive after transient write failures
- Open hidraw non-blocking so a stalled display cannot freeze the UI

* Thu Oct 22 2026 DeepCool Linux contributors - 1.1.0-1
- Add independent auto-cycle support for the GPU readout

* Thu Oct 22 2026 DeepCool Linux contributors - 1.0.0-1
- Initial Linux package
