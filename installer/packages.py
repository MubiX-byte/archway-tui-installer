from __future__ import annotations

from .command import InstallError, Runner
from .config import Config
from .drivers import recommend

DESKTOP_PACKAGES = {
    "none": [],
    "plasma": ["plasma-meta", "konsole", "dolphin", "sddm", "xdg-desktop-portal-kde"],
    "gnome": ["gnome-shell", "gnome-control-center", "gnome-terminal", "nautilus", "gdm", "xdg-desktop-portal-gnome"],
    "xfce": ["xfce4", "xfce4-goodies", "xorg-server", "lightdm", "lightdm-gtk-greeter", "xdg-desktop-portal-gtk"],
    "cinnamon": ["cinnamon", "nemo", "gnome-terminal", "xorg-server", "lightdm", "lightdm-gtk-greeter", "xdg-desktop-portal-gtk"],
    "hyprland": ["hyprland", "waybar", "foot", "fuzzel", "mako", "swaybg", "polkit-gnome", "network-manager-applet", "xdg-desktop-portal-hyprland", "xdg-desktop-portal-gtk"],
    "i3": ["i3-wm", "i3status", "dmenu", "xterm", "xorg-server", "lightdm", "lightdm-gtk-greeter", "xdg-desktop-portal-gtk"],
}
EXTRAS = {
    "Internet": ["firefox", "chromium", "curl", "wget", "bind"],
    "System": ["git", "nano", "vim", "neovim", "htop", "btop", "fastfetch", "openssh"],
    "Multimedia": ["vlc", "pavucontrol"],
    "Gaming (multilib)": ["steam", "gamemode", "gamescope", "vulkan-tools"],
    "Development": ["python", "gcc", "make", "base-devel"],
}
ALLOWED_EXTRAS = set(sum(EXTRAS.values(), []))


def resolve(c: Config, hw: dict) -> tuple[list[str], str]:
    if set(c.extras) - ALLOWED_EXTRAS:
        raise InstallError("Unknown optional package selection")
    drivers, reason = recommend(hw, c.kernel, c.gpu_driver)
    packages = ["base", c.kernel, "mkinitcpio", "linux-firmware", "networkmanager", "sudo",
                "pipewire", "pipewire-alsa", "pipewire-pulse", "wireplumber", "alsa-utils",
                "dosfstools", "e2fsprogs", "btrfs-progs", "xfsprogs", "noto-fonts", "polkit"]
    packages += drivers + DESKTOP_PACKAGES[c.desktop] + c.extras
    if hw["vendor"] == "GenuineIntel":
        packages.append("intel-ucode")
    elif hw["vendor"] == "AuthenticAMD":
        packages.append("amd-ucode")
    if c.bluetooth:
        packages += ["bluez", "bluez-utils"]
    if c.bootloader == "grub":
        packages += ["grub", "efibootmgr"] if c.firmware == "UEFI" else ["grub"]
    if c.encrypt:
        packages.append("cryptsetup")
    if c.zram:
        packages.append("zram-generator")
    if c.snapshots:
        packages.append("snapper")
    if c.os_prober:
        packages += ["os-prober", "ntfs-3g"]
    if "steam" in c.extras:
        packages += ["lib32-mesa", "lib32-vulkan-icd-loader"]
        if "nvidia-utils" in packages:
            packages.append("lib32-nvidia-utils")
        if "vulkan-intel" in packages:
            packages.append("lib32-vulkan-intel")
        if "vulkan-radeon" in packages:
            packages.append("lib32-vulkan-radeon")
    return sorted(set(packages)), reason


def pacman_config(multilib: bool) -> str:
    # Dedicated config; do not alter the ISO's pacman configuration.
    return ("[options]\nArchitecture = auto\nCheckSpace\nSigLevel = Required DatabaseOptional\nLocalFileSigLevel = Optional\n"
            "[core]\nInclude = /etc/pacman.d/mirrorlist\n[extra]\nInclude = /etc/pacman.d/mirrorlist\n" +
            ("[multilib]\nInclude = /etc/pacman.d/mirrorlist\n" if multilib else ""))


def verify(r: Runner, packages: list[str], config: str):
    r.run(["pacman", "--config", config, "-Sy", "--noconfirm"], timeout=180)
    # Both real packages and current official package groups are supported.
    available = set(r.run(["pacman", "--config", config, "-Slq"]).splitlines())
    groups = set(line.split()[0] for line in r.run(["pacman", "--config", config, "-Sg"]).splitlines() if line)
    missing = set(packages) - available - groups
    if missing:
        raise InstallError("Unavailable in current official repositories: " + ", ".join(sorted(missing)))
    r.run(["pacman", "--config", config, "-Sp", "--print-format", "%n %v", "--", *packages], timeout=120)
