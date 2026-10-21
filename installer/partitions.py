from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from .command import InstallError, Runner
from .config import Config, Partition, Secrets
from .disks import Disk, partition_path, walk


@dataclass
class Layout:
    partitions: list[Partition]
    table: str = ""


def plan(c: Config) -> Layout:
    if c.mode == "manual":
        return Layout(list(c.partitions))
    lines = ["label: gpt", "unit: sectors", ""]
    parts = []
    number = 1
    if c.firmware == "BIOS":
        lines.append("size=1MiB, type=21686148-6449-6e6f-744e-656564454649, name=BIOS boot")
        number += 1
    boot_type = "U" if c.firmware == "UEFI" else "L"
    lines.append(f"size=1GiB, type={boot_type}, name=Arch boot")
    parts.append(Partition(partition_path(c.disk, number), "/boot", "vfat" if c.firmware == "UEFI" else "ext4"))
    number += 1
    if c.swap_gib:
        lines.append(f"size={c.swap_gib}GiB, type=S, name=Arch swap")
        parts.append(Partition(partition_path(c.disk, number), "swap", "swap"))
        number += 1
    if c.home_gib:
        lines.append(f"size={c.home_gib}GiB, type=L, name=Arch home")
        parts.append(Partition(partition_path(c.disk, number), "/home", c.filesystem))
        number += 1
    lines.append("type=L, name=Arch root")
    parts.append(Partition(partition_path(c.disk, number), "/", c.filesystem))
    return Layout(parts, "\n".join(lines) + "\n")


def describe(c: Config) -> list[str]:
    layout = plan(c)
    lines = [f"{'ERASE ENTIRE DISK' if c.mode == 'automatic' else 'USE EXISTING PARTITIONS'}: {c.disk}",
             f"Disk fingerprint: {c.fingerprint}"]
    if layout.table:
        lines.extend(layout.table.splitlines())
    for p in layout.partitions:
        lines.append(f"{'FORMAT / DATA LOSS' if p.format else 'PRESERVE filesystem'} {p.device} -> {p.mount} ({p.fs})")
    if c.encrypt:
        lines.append("LUKS2 encrypted root. /boot remains unencrypted. Swap is zram only.")
    if c.filesystem == "btrfs":
        lines.append("Btrfs root subvolume @; @home when no separate home; @snapshots")
    return lines


def validate_manual(c: Config, disk: Disk):
    children = {p["path"]: p for p in walk(disk.node.get("children", [])) if p["type"] == "part"}
    for p in c.partitions:
        node = children.get(p.device)
        if not node:
            raise InstallError(f"{p.device} is not a partition of selected disk")
        if not p.format and node.get("fstype") != p.fs:
            raise InstallError(f"Preserved filesystem mismatch on {p.device}")
        minimum = 20 * 1024**3 if p.mount == "/" else 1024**3 if p.mount == "/boot" else 0
        if int(node["size"]) < minimum:
            raise InstallError(f"{p.mount} is too small (root >=20GiB, boot >=1GiB)")
        if c.firmware == "UEFI" and p.mount == "/boot":
            if str(node.get("parttype", "")).lower() not in ("c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "0xef"):
                raise InstallError("The boot partition must have the EFI System partition type")
    if c.firmware == "BIOS" and disk.node.get("pttype") == "gpt":
        if not any(str(p.get("parttype", "")).lower() == "21686148-6449-6e6f-744e-656564454649" for p in children.values()):
            raise InstallError("BIOS/GPT needs an existing BIOS boot partition (>=1MiB)")


class Storage:
    def __init__(self, r: Runner):
        self.r = r
        self.mounts: list[str] = []
        self.swaps: list[str] = []
        self.mapper = False

    def prepare(self, c: Config, secrets: Secrets) -> tuple[str, str]:
        layout = plan(c)
        r = self.r
        if c.mode == "automatic":
            # sfdisk replaces partition metadata; individual selected filesystems
            # are wiped below. No blanket wipefs on unrelated devices.
            r.run(["sfdisk", "--wipe", "always", "--wipe-partitions", "always", c.disk], input=layout.table)
            r.run(["partprobe", c.disk])
            r.run(["udevadm", "settle"])
        root_raw = next(p.device for p in layout.partitions if p.mount == "/")
        root_device = root_raw
        if c.encrypt:
            if Path("/dev/mapper/archway-root").exists():
                raise InstallError("Mapper archway-root already exists")
            r.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--key-file", "-", root_raw], input=secrets.luks, secret=True)
            r.run(["cryptsetup", "open", "--key-file", "-", root_raw, "archway-root"], input=secrets.luks, secret=True)
            self.mapper = True
            root_device = "/dev/mapper/archway-root"
        for p in layout.partitions:
            dev = root_device if p.mount == "/" else p.device
            if p.format:
                commands = {"ext4": ["mkfs.ext4", "-F"], "btrfs": ["mkfs.btrfs", "-f"],
                            "xfs": ["mkfs.xfs", "-f"], "vfat": ["mkfs.fat", "-F32"], "swap": ["mkswap"]}
                r.run([*commands[p.fs], dev])
        Path("/mnt").mkdir(exist_ok=True)
        if c.filesystem == "btrfs":
            self._mount(root_device, "/mnt")
            for sub in ("@", "@home", "@snapshots"):
                r.run(["btrfs", "subvolume", "create", f"/mnt/{sub}"])
            r.run(["umount", "/mnt"])
            self.mounts.remove("/mnt")
            self._mount(root_device, "/mnt", "subvol=@,compress=zstd")
            if not any(p.mount == "/home" for p in layout.partitions):
                self._mount(root_device, "/mnt/home", "subvol=@home,compress=zstd")
            self._mount(root_device, "/mnt/.snapshots", "subvol=@snapshots,compress=zstd")
        else:
            self._mount(root_device, "/mnt")
        for p in sorted(layout.partitions, key=lambda p: p.mount):
            if p.mount == "/":
                continue
            if p.mount == "swap":
                r.run(["swapon", p.device])
                self.swaps.append(p.device)
            else:
                self._mount(p.device, "/mnt" + p.mount)
        for mount in self.mounts:
            r.run(["mountpoint", "-q", mount])
        return root_raw, root_device

    def _mount(self, device, target, options=""):
        path = Path(target)
        if path.is_symlink() or not path.resolve().is_relative_to(Path("/mnt")):
            raise InstallError("Unsafe target mountpoint")
        path.mkdir(parents=True, exist_ok=True)
        self.r.run(["mount", *(["-o", options] if options else []), device, target])
        self.mounts.append(target)

    def cleanup(self):
        # Only resources opened by this run; stop on a busy mount, never force it.
        for swap in list(reversed(self.swaps)):
            self.r.run(["swapoff", swap])
            self.swaps.remove(swap)
        for mount in list(reversed(self.mounts)):
            self.r.run(["umount", mount])
            self.mounts.remove(mount)
        if self.mapper:
            self.r.run(["cryptsetup", "close", "archway-root"])
            self.mapper = False
