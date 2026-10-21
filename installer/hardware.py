from __future__ import annotations

import json
from pathlib import Path
import platform
import re

from .command import Runner


def optional(r: Runner, argv: list[str]) -> str:
    try:
        return r.run(argv, timeout=20, check=False).strip()
    except RuntimeError:
        return ""


def secure_boot() -> bool | None:
    variables = list(Path("/sys/firmware/efi/efivars").glob("SecureBoot-*"))
    if not Path("/sys/firmware/efi").exists():
        return False
    if not variables:
        return None
    try:
        return variables[0].read_bytes()[4] == 1
    except (OSError, IndexError):
        return None


def detect(r: Runner) -> dict:
    pci = optional(r, ["lspci", "-Dnnk"])
    cpu = optional(r, ["lscpu", "-J"])
    try:
        info = {i["field"].rstrip(":"): i["data"] for i in json.loads(cpu)["lscpu"]}
    except (ValueError, KeyError, TypeError):
        info = {}
    gpus = [line for line in pci.splitlines() if re.search(r"VGA compatible|3D controller|Display controller", line)]
    try:
        memory = next(line for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemTotal:"))
        ram = f"{int(memory.split()[1]) / 1024**2:.1f} GiB"
    except (OSError, StopIteration):
        ram = "unknown"
    batteries = []
    for battery in Path("/sys/class/power_supply").glob("*"):
        if (battery / "capacity").exists():
            batteries.append(f"{battery.name}: {(battery / 'capacity').read_text().strip()}%")
    return {"firmware": "UEFI" if Path("/sys/firmware/efi").exists() else "BIOS",
            "secure_boot": secure_boot(), "arch": platform.machine(),
            "cpu": info.get("Model name", "unknown"), "vendor": info.get("Vendor ID", ""),
            "gpus": gpus, "pci": pci, "usb": optional(r, ["lsusb"]), "ram": ram,
            "battery": ", ".join(batteries) or "AC / unknown",
            "bluetooth": bool(list(Path("/sys/class/bluetooth").glob("hci*")))}


def demo_hardware():
    return {"firmware": "UEFI", "secure_boot": False, "arch": "x86_64",
            "cpu": "Demo AMD Ryzen", "vendor": "AuthenticAMD", "gpus": ["AMD Radeon [1002:744c]"],
            "pci": "Demo hardware (no host probes)", "usb": "Demo USB", "ram": "16 GiB",
            "battery": "AC", "bluetooth": True}
