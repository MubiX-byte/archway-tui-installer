#!/usr/bin/env python3
"""Validate sfdisk plans on newly-created regular files, never block devices."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.partitions import plan
from main import demo_config


def main():
    if not shutil.which("sfdisk"):
        raise SystemExit("sfdisk is required; install util-linux/fdisk on the Linux test host")
    count = 0
    with tempfile.TemporaryDirectory(prefix="archway-storage-test-") as directory:
        for firmware in ("UEFI", "BIOS"):
            for home, swap in ((0, 0), (4, 0), (0, 2), (4, 2)):
                c = replace(demo_config(firmware), home_gib=home, swap_gib=swap)
                layout = plan(c)
                image = Path(directory) / f"{firmware}-{home}-{swap}.img"
                with image.open("xb") as output:
                    output.truncate(32 * 1024**3)
                assert stat.S_ISREG(image.stat().st_mode), "Only a new regular image file is allowed"
                result = subprocess.run(["sfdisk", "--no-reread", "--no-tell-kernel", str(image)],
                                        input=layout.table, text=True, capture_output=True)
                if result.returncode:
                    raise AssertionError(result.stdout + result.stderr)
                table = json.loads(subprocess.check_output(["sfdisk", "--json", str(image)], text=True))["partitiontable"]
                assert table["label"] == "gpt"
                assert len(table["partitions"]) == len(layout.partitions) + (firmware == "BIOS")
                sector = table.get("sectorsize", 512)
                boot = table["partitions"][0 if firmware == "UEFI" else 1]
                assert boot["size"] * sector == 1024**3
                assert table["partitions"][-1]["size"] * sector >= 20 * 1024**3
                count += 1
                image.unlink()
    print(f"PASS: {count} UEFI/BIOS/home/swap plans applied to isolated regular image files")


if __name__ == "__main__":
    main()
