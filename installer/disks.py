"""Device inventory and fail-closed protection of mounted/live devices."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .command import InstallError, Runner


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("children", []))


def mounted(node):
    return any(any(n.get("mountpoints") or []) for n in walk([node]))


def fingerprint(node):
    identity = [str(node.get(k, "")) for k in ("path", "size", "model", "serial", "wwn", "maj:min")]
    identity.append(json.dumps([{k: n.get(k) for k in ("path", "size", "type", "fstype", "uuid", "parttype")}
                                for n in walk(node.get("children", []))], sort_keys=True))
    return hashlib.sha256("|".join(identity).encode()).hexdigest()


@dataclass
class Disk:
    node: dict
    blocked: str = ""

    @property
    def path(self):
        return self.node["path"]

    @property
    def identity(self):
        return fingerprint(self.node)

    def label(self):
        n = self.node
        return (f"{self.path} | {n.get('model') or 'unknown'} | {int(n['size']) / 1024**3:.1f} GiB | "
                f"{n.get('tran') or 'disk'} | serial={n.get('serial') or '?'} | "
                f"{self.blocked or 'available'}")


def inventory(r: Runner) -> list[Disk]:
    data = json.loads(r.run(["lsblk", "--json", "--bytes", "--paths", "--output",
                            "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,WWN,MAJ:MIN,TRAN,RO,RM,FSTYPE,MOUNTPOINTS,PARTTYPE,PTTYPE,PARTLABEL,LABEL,UUID"]))
    nodes = data["blockdevices"]
    # Loop-backed ISO images may reside on an otherwise unmounted device. Resolve
    # loop backing files through findmnt rather than guessing /dev/sdX names.
    live_devices = set()
    try:
        loops = json.loads(r.run(["losetup", "--json", "--list", "--output", "NAME,BACK-FILE"], timeout=20))
        for loop in loops.get("loopdevices", []):
            backing = loop.get("back-file")
            if backing and Path(backing).exists():
                source = r.run(["findmnt", "-nro", "SOURCE", "-T", backing], timeout=20).strip().split("[")[0]
                if source.startswith("/dev/"):
                    live_devices.add(str(Path(source).resolve()))
    except (InstallError, ValueError) as exc:
        raise InstallError("Cannot establish loop/live-media ancestry; refusing disk operations") from exc
    disks = []
    for n in nodes:
        if n["type"] != "disk":
            continue
        reason = ""
        if n.get("ro"):
            reason = "READ ONLY"
        elif mounted(n):
            reason = "MOUNTED / SWAP / LIVE MEDIA"
        elif any(c.get("type") != "part" for c in walk(n.get("children", []))):
            reason = "ACTIVE DEVICE MAPPER / RAID HOLDER"
        elif any(str(Path(c["path"]).resolve()) in live_devices for c in walk([n])):
            reason = "LIVE IMAGE BACKING DEVICE"
        disks.append(Disk(n, reason))
    return disks


def checked_disk(r: Runner, path: str, identity: str) -> Disk:
    matches = [d for d in inventory(r) if d.path == path]
    if len(matches) != 1 or matches[0].identity != identity:
        raise InstallError("Disk identity changed or disappeared; select and review again")
    disk = matches[0]
    if disk.blocked:
        raise InstallError(f"Protected device {path}: {disk.blocked}. Unmount target partitions manually, never the live medium.")
    return disk


def partition_path(disk: str, number: int):
    return f"{disk}{'p' if disk[-1].isdigit() else ''}{number}"


def demo_disk():
    return Disk({"path": "/dev/demo0", "type": "disk", "size": 128 * 1024**3,
                 "model": "DEMO VIRTUAL DISK", "serial": "DEMO-ONLY", "wwn": "demo",
                 "maj:min": "0:0", "tran": "virtual", "children": []})
