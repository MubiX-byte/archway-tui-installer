"""Installation orchestration. Destructive work has a single reviewed entry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import time

from . import bootloader, networking, packages, system
from .command import InstallError, Runner, write_target
from .config import Config, Secrets
from .disks import checked_disk
from .hardware import secure_boot
from .partitions import Storage, describe, validate_manual


def summary(c: Config, hw: dict) -> list[str]:
    resolved, reason = packages.resolve(c, hw)
    lines = describe(c)
    lines += ["", f"Firmware: {c.firmware} | Kernel: {c.kernel} | Bootloader: {c.bootloader}",
              f"CPU: {hw['cpu']}", "GPU: " + "; ".join(hw["gpus"]), reason,
              f"Desktop: {c.desktop} | Bluetooth: {c.bluetooth} | Zram: {c.zram} | Snapshots: {c.snapshots}",
              f"User: {c.username} | Sudo: {c.sudo} | Host: {c.hostname}",
              f"Locale: {c.locale} | Keymap: {c.keymap} | Timezone: {c.timezone} | NTP: {c.ntp}",
              f"Network: {c.network or 'existing live connection (wired DHCP in target)'}",
              f"Other OS detection (GRUB): {c.os_prober}", "Packages (availability checked before erasure):", " ".join(resolved)]
    return lines


def preflight(r: Runner, c: Config):
    if platform.system() != "Linux" or platform.machine() != "x86_64" or os.geteuid() != 0:
        raise InstallError("Real installation requires root on x86_64 Arch Linux Live ISO")
    if not Path("/run/archiso").is_dir():
        raise InstallError("Official Arch Live ISO marker /run/archiso is missing")
    firmware = "UEFI" if Path("/sys/firmware/efi").exists() else "BIOS"
    if firmware != c.firmware:
        raise InstallError("Firmware mode changed; rebuild configuration")
    if secure_boot() is not False:
        raise InstallError("Secure Boot enabled or unreadable. This installer does not provision signed boot chains. Disable it in firmware yourself or use a documented signed installation workflow.")
    needed = ["lsblk", "losetup", "findmnt", "sfdisk", "partprobe", "udevadm", "pacstrap", "pacman", "genfstab",
              "arch-chroot", "mount", "umount", "mountpoint", "blkid", "timedatectl", "loadkeys",
              "mkfs.ext4", "mkfs.btrfs", "mkfs.xfs", "mkfs.fat", "mkswap", "cryptsetup", "btrfs"]
    missing = [exe for exe in needed if not shutil.which(exe)]
    if missing:
        raise InstallError("Missing Live ISO tools: " + ", ".join(missing))
    r.run(["mountpoint", "-q", "/run/archiso/bootmnt"], check=False)
    # Never install over an existing mount, nonempty directory or symlink.
    if Path("/mnt").is_symlink() or (Path("/mnt").exists() and any(Path("/mnt").iterdir())):
        raise InstallError("/mnt must be empty and must not be a symlink")
    mounts = json.loads(r.run(["findmnt", "--json", "--output", "TARGET"]))
    def targets(items):
        for item in items:
            yield item["target"]
            yield from targets(item.get("children", []))
    if any(t == "/mnt" or t.startswith("/mnt/") for t in targets(mounts.get("filesystems", []))):
        raise InstallError("/mnt or a child is already mounted")
    disk = checked_disk(r, c.disk, c.fingerprint)
    c.validate(size=int(disk.node["size"]) if c.mode == "automatic" else None)
    if c.mode == "manual":
        validate_manual(c, disk)
    zone = Path("/usr/share/zoneinfo") / c.timezone
    if not zone.is_file() or ".." in c.timezone:
        raise InstallError("Timezone unavailable in Live ISO")
    r.run(["loadkeys", "--parse", c.keymap], timeout=20)
    if not networking.online():
        raise InstallError("Arch repository is unreachable over HTTPS; configure network first")
    # Always synchronize before package signature verification, independently of
    # the user's preference for NTP in the installed system.
    r.run(["timedatectl", "set-ntp", "true"])
    for _ in range(30):
        if r.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], timeout=10).strip() == "yes":
            break
        time.sleep(1)
    else:
        raise InstallError("Clock did not synchronize; fix NTP before installation")


class Installer:
    def __init__(self, r: Runner, progress=None):
        self.r = r
        self.progress = progress or (lambda done, total, name: None)
        self.storage = Storage(r)
        self.destructive_started = False
        self.stage = "Not started"

    def install(self, c: Config, secrets: Secrets, hw: dict, confirmation: str):
        expected = f"{'ERASE' if c.mode == 'automatic' else 'FORMAT'} {c.disk}"
        if confirmation != expected:
            raise InstallError("Typed disk confirmation does not match")
        secrets.validate(c)
        total = 9
        def stage(number, label):
            self.stage = label
            self.r.note(f"[{number}/{total}] {label}")
            self.progress(number - 1, total, label)
        stage(1, "Preflight: hardware, disks, network and clock")
        preflight(self.r, c)
        resolved, _ = packages.resolve(c, hw)
        with tempfile.TemporaryDirectory(prefix="archway-", dir="/run") as temp:
            config_path = Path(temp) / "pacman.conf"
            config_path.write_text(packages.pacman_config("steam" in c.extras))
            stage(2, "Verify packages in current signed repositories")
            packages.verify(self.r, resolved, str(config_path))
            # Review remains valid only for the identical disk and exact config.
            current_disk = checked_disk(self.r, c.disk, c.fingerprint)
            if c.mode == "manual":
                validate_manual(c, current_disk)
            stage(3, "Apply reviewed partition and filesystem plan")
            self.destructive_started = True
            root_raw, root_device = self.storage.prepare(c, secrets)
            stage(4, "Install base, kernel, drivers and desktop packages")
            self.r.run(["pacstrap", "-K", "-C", str(config_path), "/mnt", *resolved], timeout=14400)
            stage(5, "Generate and validate filesystem table")
            fstab = self.r.run(["genfstab", "-U", "/mnt"])
            if not any(line.split()[1:2] == ["/"] for line in fstab.splitlines() if line and not line.startswith("#")):
                raise InstallError("Generated fstab has no root entry")
            write_target("/etc/fstab", fstab)
            stage(6, "Configure accounts, locale, services and initramfs")
            system.configure(self.r, c, secrets)
            stage(7, "Install and validate bootloader")
            bootloader.install(self.r, c, root_raw, root_device)
            stage(8, "Verify installed packages, users and services")
            self.r.chroot(["pacman", "-Q", c.kernel, "networkmanager", "linux-firmware"])
            self.r.chroot(["id", c.username])
            self.r.chroot(["systemctl", "is-enabled", "NetworkManager.service"])
            self.r.chroot(["findmnt", "--verify", "--tab-file", "/etc/fstab"])
            # DKMS failures can be reported as successful pacman hook completion.
            if "nvidia-open-dkms" in resolved:
                modules = list(Path("/mnt/usr/lib/modules").glob("*/extramodules/nvidia.ko*"))
                modules += list(Path("/mnt/usr/lib/modules").glob("*/updates/dkms/nvidia.ko*"))
                if not modules:
                    raise InstallError("NVIDIA DKMS module missing; inspect build logs before reboot")
            write_target("/var/log/archway-plan.json", json.dumps(c.public(), indent=2) + "\n", 0o600)
            if self.r.log:
                write_target("/var/log/archway-install.log", self.r.log.read_text(), 0o600)
            stage(9, "Sync and unmount only this installer's resources")
            self.r.run(["sync"])
            self.storage.cleanup()
            self.progress(total, total, "Installation completed. Reboot is a separate explicit action.")
