#!/usr/bin/env python3
"""Archway entrypoint. CLI exports plans; actual installation requires the TUI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from installer import __version__
from installer.command import InstallError, Runner
from installer.config import Config, Partition
from installer.core import summary
from installer.disks import demo_disk
from installer.hardware import demo_hardware, detect


def demo_config(firmware="UEFI"):
    disk = demo_disk()
    return Config(disk=disk.path, fingerprint=disk.identity, firmware=firmware,
                  bootloader="systemd-boot" if firmware == "UEFI" else "grub")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Archway — Arch Linux TUI installer")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--demo", action="store_true", help="Synthetic hardware; prohibit all host changes")
    parser.add_argument("--plan", action="store_true", help="Print a dry-run plan and exit, never install")
    parser.add_argument("--json", action="store_true", help="Export public configuration with --plan")
    parser.add_argument("--firmware", choices=("UEFI", "BIOS"), default="UEFI", help="Demo firmware mode")
    parser.add_argument("--config", type=Path, help="Read a public JSON configuration for --plan only")
    args = parser.parse_args(argv)
    if args.json and not args.plan:
        parser.error("--json requires --plan")
    if args.config and not args.plan:
        parser.error("--config is only supported with --plan")
    try:
        if args.plan:
            hw = demo_hardware() if args.demo else detect(Runner())
            if args.config:
                raw = json.loads(args.config.read_text(encoding="utf-8"))
                raw["partitions"] = [Partition(**p) for p in raw.get("partitions", [])]
                c = Config(**raw)
            elif args.demo:
                c = demo_config(args.firmware)
            else:
                raise InstallError("Use --config for a real dry run, or --demo for a synthetic plan")
            c.validate()
            print(json.dumps(c.public(), ensure_ascii=False, indent=2) if args.json else "\n".join(summary(c, hw)))
            return 0
        if not args.demo and (sys.platform != "linux" or os.geteuid() != 0 or not Path("/run/archiso").exists()):
            raise InstallError("Run as root on the official x86_64 Arch Live ISO, or use --demo")
        try:
            from tui.app import launch
        except ImportError:
            raise InstallError("curses is unavailable. On Windows, pip install windows-curses for the optional demo. Arch ISO needs no pip packages.") from None
        launch(args.demo)
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Inspect /mnt and /var/log/archway-live.log before restarting; no rollback was performed.", file=sys.stderr)
        return 130
    except (InstallError, OSError, ValueError, TypeError) as exc:
        print(f"Archway: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
