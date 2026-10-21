from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re

from .command import InstallError

KERNELS = ("linux", "linux-lts", "linux-zen", "linux-hardened")
FILESYSTEMS = ("ext4", "btrfs", "xfs")
DESKTOPS = ("none", "plasma", "gnome", "xfce", "cinnamon", "hyprland", "i3")


@dataclass
class Partition:
    device: str
    mount: str
    fs: str
    format: bool = True


@dataclass
class Config:
    disk: str = ""
    fingerprint: str = ""
    firmware: str = "UEFI"
    mode: str = "automatic"
    filesystem: str = "ext4"
    home_gib: int = 0
    swap_gib: int = 0
    encrypt: bool = False
    zram: bool = True
    snapshots: bool = False
    kernel: str = "linux"
    bootloader: str = "systemd-boot"
    desktop: str = "none"
    gpu_driver: str = "auto"
    bluetooth: bool = True
    hostname: str = "archlinux"
    username: str = "arch"
    locale: str = "pl_PL.UTF-8"
    timezone: str = "Europe/Warsaw"
    keymap: str = "pl"
    ntp: bool = True
    sudo: bool = True
    os_prober: bool = False
    serial_console: bool = False
    extras: list[str] = field(default_factory=lambda: ["nano", "git"])
    partitions: list[Partition] = field(default_factory=list)
    network: str = ""
    net_interface: str = ""
    net_address: str = ""
    net_gateway: str = ""
    net_dns: str = ""
    wifi_ssid: str = ""
    wifi_security: str = "wpa-psk"
    wifi_hidden: bool = False

    def public(self):
        return asdict(self)

    def validate(self, *, size: int | None = None):
        if not re.fullmatch(r"/dev/[A-Za-z0-9_./-]+", self.disk) or ".." in self.disk:
            raise InstallError("Select a valid disk")
        if not self.fingerprint:
            raise InstallError("Disk identity is missing; select the disk again")
        if self.firmware not in ("UEFI", "BIOS") or self.mode not in ("automatic", "manual"):
            raise InstallError("Invalid firmware or partition mode")
        if self.kernel not in KERNELS or self.filesystem not in FILESYSTEMS or self.desktop not in DESKTOPS:
            raise InstallError("Unknown kernel, filesystem or desktop")
        if self.bootloader not in ("systemd-boot", "grub"):
            raise InstallError("Unknown bootloader")
        if self.firmware == "BIOS" and self.bootloader != "grub":
            raise InstallError("BIOS requires GRUB")
        if self.gpu_driver not in ("auto", "mesa", "nouveau", "nvidia-open"):
            raise InstallError("Unknown GPU driver selection")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", self.username) or self.username == "root":
            raise InstallError("Username must be a regular Linux username, not root")
        if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", self.hostname):
            raise InstallError("Hostname must be one valid DNS label")
        if not re.fullmatch(r"[a-z]{2}_[A-Z]{2}\.UTF-8", self.locale):
            raise InstallError("Use a UTF-8 locale, e.g. pl_PL.UTF-8")
        if not re.fullmatch(r"[A-Za-z0-9_+/-]+", self.timezone) or ".." in self.timezone:
            raise InstallError("Invalid timezone")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.keymap):
            raise InstallError("Invalid console keymap")
        if self.home_gib < 0 or self.swap_gib < 0:
            raise InstallError("Sizes cannot be negative")
        if size is not None and size < (self.home_gib + self.swap_gib + 24) * 1024**3:
            raise InstallError("Allow at least 24 GiB for root and boot, plus home/swap")
        if self.encrypt and (self.mode == "manual" or self.home_gib or self.swap_gib):
            raise InstallError("Encryption supports automatic root + zram only; no unencrypted home/swap")
        if self.snapshots and self.filesystem != "btrfs":
            raise InstallError("Snapshots require Btrfs")
        if self.mode == "manual":
            mounts = [p.mount for p in self.partitions]
            devices = [p.device for p in self.partitions]
            if len(mounts) != len(set(mounts)) or len(devices) != len(set(devices)):
                raise InstallError("A partition or mountpoint is selected twice")
            if "/" not in mounts or "/boot" not in mounts:
                raise InstallError("Manual mode needs root and a separate /boot partition")
            for p in self.partitions:
                if p.mount not in ("/", "/boot", "/home", "swap"):
                    raise InstallError("Unsupported mountpoint")
                if p.fs not in (*FILESYSTEMS, "vfat", "swap"):
                    raise InstallError("Unsupported filesystem")
                if p.mount == "swap" and p.fs != "swap":
                    raise InstallError("Swap needs the swap filesystem")
                if p.mount != "swap" and p.fs == "swap":
                    raise InstallError("Swap cannot be mounted as a filesystem")
                if p.mount in ("/", "/home") and p.fs == "vfat":
                    raise InstallError("Root/home need a Linux filesystem")
                if p.mount == "/" and not p.format:
                    raise InstallError("Root must be freshly formatted; retained home/EFI are supported")
                if p.mount == "/" and p.fs != self.filesystem:
                    raise InstallError("Root filesystem does not match configuration")
                if self.firmware == "UEFI" and p.mount == "/boot" and p.fs != "vfat":
                    raise InstallError("UEFI needs a FAT32 ESP mounted at /boot")
                if self.firmware == "BIOS" and p.mount == "/boot" and p.fs != "ext4":
                    raise InstallError("BIOS /boot must use ext4")


@dataclass(repr=False)
class Secrets:
    password: str = ""
    root_password: str = ""
    luks: str = ""
    wifi_password: str = ""

    def validate(self, c: Config):
        for value in (self.password, self.root_password, self.luks):
            if any(ch in value for ch in ("\n", "\r", "\x00")):
                raise InstallError("Secrets cannot contain newline or NUL")
        if len(self.password) < 8:
            raise InstallError("User password needs at least 8 characters")
        if self.root_password and len(self.root_password) < 8:
            raise InstallError("Root password needs at least 8 characters")
        if not c.sudo and not self.root_password:
            raise InstallError("Enable sudo or set a root password for administration")
        if c.encrypt and len(self.luks) < 12:
            raise InstallError("Encryption passphrase needs at least 12 characters")
