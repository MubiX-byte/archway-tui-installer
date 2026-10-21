#!/usr/bin/env python3
"""Read current official repo databases without installing anything.

This is a development availability check. The installer uses pacman signature
verification and dependency resolution on the Live ISO before modifying disks.
"""
from dataclasses import replace
import io
from pathlib import Path
import sys
import tarfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.config import KERNELS
from installer.hardware import demo_hardware
from installer.packages import ALLOWED_EXTRAS, DESKTOP_PACKAGES, resolve
from main import demo_config


def main():
    names, groups = set(), set()
    for repo in ("core", "extra", "multilib"):
        url = f"https://geo.mirror.pkgbuild.com/{repo}/os/x86_64/{repo}.db"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for entry in archive:
                if not entry.isfile() or not entry.name.endswith("/desc"):
                    continue
                stream = archive.extractfile(entry)
                fields = stream.read().decode().split("\n\n")
                for field in fields:
                    parts = field.splitlines()
                    if parts and parts[0] == "%NAME%":
                        names.update(parts[1:])
                    elif parts and parts[0] == "%GROUPS%":
                        groups.update(parts[1:])
        print(f"Read {repo}: {len(data)} bytes")
    required = set(ALLOWED_EXTRAS)
    for kernel in KERNELS:
        for desktop in DESKTOP_PACKAGES:
            hw = {**demo_hardware(), "gpus": ["Intel Graphics", "NVIDIA AD104 RTX 4070", "AMD Radeon"]}
            c = replace(demo_config(), kernel=kernel, desktop=desktop, gpu_driver="nvidia-open", extras=["steam"],
                        encrypt=True, snapshots=True)
            p, _ = resolve(c, hw)
            required.update(p)
    required.add("xf86-video-nouveau")
    missing = required - names - groups
    if missing:
        print("MISSING: " + ", ".join(sorted(missing)), file=sys.stderr)
        return 1
    print(f"PASS: {len(required)} selected package/group names exist in current official repositories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
