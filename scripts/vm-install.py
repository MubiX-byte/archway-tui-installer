#!/usr/bin/env python3
"""Acceptance fixture. Only runs inside a VM with our explicit disk serial."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.command import Runner
from installer.config import Config, Secrets
from installer.core import Installer
from installer.disks import inventory
from installer.hardware import detect


def main():
    if not Path("/run/archiso").is_dir():
        raise SystemExit("This acceptance fixture requires Arch Live ISO")
    r = Runner(Path("/var/log/archway-vm.log"), lambda line: print(line, flush=True))
    targets = [d for d in inventory(r) if d.path == "/dev/vda" and d.node.get("serial") == "ARCHWAY-CI-ONLY"]
    if len(targets) != 1 or targets[0].blocked or int(targets[0].node["size"]) != 40 * 1024**3:
        raise SystemExit("Refusing: missing dedicated 40 GiB virtual disk with serial ARCHWAY-CI-ONLY")
    disk = targets[0]
    hw = detect(r)
    c = Config(disk=disk.path, fingerprint=disk.identity, firmware=hw["firmware"],
               bootloader="systemd-boot" if hw["firmware"] == "UEFI" else "grub",
               bluetooth=False, extras=["nano"], serial_console=True, username="archtest")
    # These credentials are local to a disposable, network-isolated acceptance VM.
    s = Secrets(password="Archway-QEMU-only-2026", root_password="Archway-QEMU-only-2026")
    Installer(r).install(c, s, hw, "ERASE /dev/vda")
    print("ARCHWAY_INSTALL_OK", flush=True)
    r.run(["systemctl", "poweroff"])


if __name__ == "__main__":
    main()
