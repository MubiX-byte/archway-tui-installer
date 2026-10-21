from __future__ import annotations

from pathlib import Path
import configparser
import io
import uuid

from .command import InstallError, Runner, write_target
from .config import Config, Secrets
from .packages import pacman_config


def configure(r: Runner, c: Config, secrets: Secrets):
    locale_source = Path("/mnt/usr/share/i18n/SUPPORTED").read_text()
    if f"{c.locale} UTF-8" not in locale_source:
        raise InstallError("Selected locale is not supported by installed glibc")
    zone = Path("/mnt/usr/share/zoneinfo") / c.timezone
    if not zone.is_file() or not zone.resolve().is_relative_to(Path("/mnt/usr/share/zoneinfo")):
        raise InstallError("Selected timezone is unavailable")
    write_target("/etc/locale.gen", f"{c.locale} UTF-8\nen_US.UTF-8 UTF-8\n" if c.locale != "en_US.UTF-8" else "en_US.UTF-8 UTF-8\n")
    write_target("/etc/locale.conf", f"LANG={c.locale}\n")
    write_target("/etc/vconsole.conf", f"KEYMAP={c.keymap}\n")
    write_target("/etc/hostname", c.hostname + "\n")
    write_target("/etc/hosts", f"127.0.0.1 localhost\n::1 localhost\n127.0.1.1 {c.hostname}.localdomain {c.hostname}\n")
    r.chroot(["ln", "-sf", f"/usr/share/zoneinfo/{c.timezone}", "/etc/localtime"])
    r.chroot(["hwclock", "--systohc"])
    r.chroot(["locale-gen"])
    r.chroot(["useradd", "-m", "-G", "wheel" if c.sudo else "users", "-s", "/bin/bash", c.username])
    r.chroot(["chpasswd"], input=f"{c.username}:{secrets.password}\n", secret=True)
    if secrets.root_password:
        r.chroot(["chpasswd"], input=f"root:{secrets.root_password}\n", secret=True)
    else:
        r.chroot(["passwd", "-l", "root"])
    if c.sudo:
        write_target("/etc/sudoers.d/10-wheel", "%wheel ALL=(ALL:ALL) ALL\n", 0o440)
        r.chroot(["visudo", "-cf", "/etc/sudoers"])
    write_target("/etc/pacman.conf", pacman_config("steam" in c.extras))
    if c.zram:
        write_target("/etc/systemd/zram-generator.conf", "[zram0]\nzram-size = min(ram / 2, 8192)\ncompression-algorithm = zstd\n")
    hooks = "base systemd autodetect microcode modconf kms keyboard sd-vconsole block"
    if c.encrypt:
        hooks += " sd-encrypt"
    hooks += " filesystems fsck"
    write_target("/etc/mkinitcpio.conf.d/archway.conf", f"HOOKS=({hooks})\n")
    r.chroot(["mkinitcpio", "-P"])
    services = ["NetworkManager.service"]
    if c.ntp:
        services.append("systemd-timesyncd.service")
    if c.bluetooth:
        services.append("bluetooth.service")
        write_target("/etc/bluetooth/main.conf", "[Policy]\nAutoEnable=true\n")
    manager = {"plasma": "sddm", "gnome": "gdm", "xfce": "lightdm", "cinnamon": "lightdm", "i3": "lightdm"}.get(c.desktop)
    if manager:
        services.append(manager + ".service")
    if c.snapshots:
        # Configure the already-mounted @snapshots without create-config trying
        # to replace that mountpoint. Snapshots are local and are not backups.
        template = Path("/mnt/usr/share/snapper/config-templates/default").read_text()
        import re
        template = re.sub(r'^SUBVOLUME=.*$', 'SUBVOLUME="/"', template, flags=re.M)
        write_target("/etc/snapper/configs/root", template)
        write_target("/etc/conf.d/snapper", 'SNAPPER_CONFIGS="root"\n')
        services += ["snapper-timeline.timer", "snapper-cleanup.timer"]
    r.chroot(["systemctl", "enable", *services])
    if manager:
        r.chroot(["systemctl", "set-default", "graphical.target"])
    if c.desktop == "hyprland":
        # Start through the user's TTY login; no display-manager auto-login.
        home = f"/home/{c.username}"
        xkb = {"pl": "pl", "us": "us", "de": "de", "fr": "fr", "uk": "gb"}.get(c.keymap, "us")
        write_target(home + "/.config/hypr/hyprland.conf", HYPRLAND.replace("kb_layout = pl", "kb_layout = " + xkb))
        r.chroot(["chown", "-R", f"{c.username}:{c.username}", home + "/.config"])
    write_network(c, secrets)


def write_network(c: Config, secrets: Secrets):
    if not c.net_interface:
        return  # NetworkManager automatically manages wired DHCP after reboot.
    profile = configparser.ConfigParser(interpolation=None)
    wifi = bool(c.wifi_ssid)
    profile["connection"] = {"id": "Archway connection", "uuid": str(uuid.uuid4()),
                             "type": "wifi" if wifi else "ethernet", "interface-name": c.net_interface,
                             "autoconnect": "true"}
    if wifi:
        profile["wifi"] = {"ssid": ";".join(str(b) for b in c.wifi_ssid.encode()) + ";", "mode": "infrastructure",
                           "hidden": "true" if c.wifi_hidden else "false"}
        if c.wifi_security != "open":
            if any(ch in secrets.wifi_password for ch in "\n\r\x00"):
                raise InstallError("Invalid Wi-Fi password")
            # GLib keyfile escaping, not shell quoting.
            escaped = secrets.wifi_password.replace("\\", "\\\\").replace(" ", "\\s")
            profile["wifi-security"] = {"key-mgmt": c.wifi_security, "psk": escaped}
    profile["ipv4"] = {"method": "auto"}
    if c.net_address:
        profile["ipv4"] = {"method": "manual", "address1": c.net_address + "," + c.net_gateway,
                           "dns": ";".join(c.net_dns.split()) + ";"}
    profile["ipv6"] = {"method": "auto"}
    output = io.StringIO()
    profile.write(output, space_around_delimiters=False)
    write_target("/etc/NetworkManager/system-connections/archway.nmconnection", output.getvalue(), 0o600)


HYPRLAND = """# Basic session: log in on a TTY, then run Hyprland.
monitor = , preferred, auto, 1
$mod = SUPER
exec-once = waybar
exec-once = mako
exec-once = nm-applet --indicator
exec-once = /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1
exec-once = swaybg -c '#152033'
bind = $mod, RETURN, exec, foot
bind = $mod, D, exec, fuzzel
bind = $mod, Q, killactive,
bind = $mod SHIFT, E, exit,
bind = $mod, F, fullscreen,
bind = , XF86AudioRaiseVolume, exec, wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+
bind = , XF86AudioLowerVolume, exec, wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
bind = , XF86AudioMute, exec, wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
bindm = $mod, mouse:272, movewindow
bindm = $mod, mouse:273, resizewindow
input {
    kb_layout = pl
    follow_mouse = 1
}
"""
