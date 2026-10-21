#!/usr/bin/env python3
"""Boot official ISO, exercise actual engine, boot resulting virtual disk."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import time
import urllib.request


def download(url, target):
    print(f"Downloading {url}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as dest:
        shutil.copyfileobj(response, dest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--firmware", choices=("bios", "uefi"), required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    work = args.work.resolve()
    # Refuse preexisting storage so a prior disk can never be silently replaced.
    work.mkdir(parents=True, exist_ok=True)
    image = work / "target.qcow2"
    if image.exists():
        raise SystemExit("Target image already exists; choose a fresh work directory")
    base = "https://geo.mirror.pkgbuild.com/iso/latest/"
    with urllib.request.urlopen(base + "sha256sums.txt", timeout=30) as response:
        sums = response.read().decode()
    match = re.search(r"^([a-f0-9]{64})\s+\*?(archlinux-\d{4}\.\d{2}\.\d{2}-x86_64\.iso)$", sums, re.M)
    if not match:
        raise SystemExit("Could not identify official ISO checksum")
    iso = work / match[2]
    download(base + match[2], iso)
    with iso.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != match[1]:
        raise SystemExit("ISO checksum mismatch")
    print(f"Verified ISO: {iso.name} sha256={digest}", flush=True)
    label = subprocess.check_output(["blkid", "-p", "-s", "LABEL", "-o", "value", str(iso)], text=True).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", label):
        raise SystemExit("Invalid ISO volume label")
    extract = work / "boot"
    extract.mkdir()
    subprocess.run(["bsdtar", "-xf", str(iso), "-C", str(extract), "arch/boot/x86_64/vmlinuz-linux", "arch/boot/x86_64/initramfs-linux.img"], check=True)
    subprocess.run(["qemu-img", "create", "-f", "qcow2", str(image), "40G"], check=True)
    accel = "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else "tcg"
    common = ["qemu-system-x86_64", "-m", "4096", "-smp", "2", "-accel", accel, "-display", "none", "-monitor", "none",
              "-serial", "stdio", "-no-reboot", "-drive", f"file={image},format=qcow2,if=none,id=target",
              "-device", "virtio-blk-pci,drive=target,serial=ARCHWAY-CI-ONLY",
              "-nic", "user,model=virtio-net-pci"]
    if args.firmware == "uefi":
        code = Path("/usr/share/OVMF/OVMF_CODE_4M.fd")
        template = Path("/usr/share/OVMF/OVMF_VARS_4M.fd")
        variables = work / "vars.fd"
        shutil.copyfile(template, variables)
        common += ["-drive", f"if=pflash,format=raw,readonly=on,file={code}", "-drive", f"if=pflash,format=raw,file={variables}"]
    install = [*common, "-cdrom", str(iso), "-kernel", str(extract / "arch/boot/x86_64/vmlinuz-linux"),
               "-initrd", str(extract / "arch/boot/x86_64/initramfs-linux.img"),
               "-append", f"archisobasedir=arch archisolabel={label} console=ttyS0,115200n8",
               "-virtfs", f"local,path={root},mount_tag=archway,security_model=none,readonly=on"]

    def session(argv, logfile, installing):
        child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        output = bytearray()
        state = 0
        deadline = time.monotonic() + (1500 if installing else 180)
        marker = b"ARCHWAY_INSTALL_OK" if installing else b"ARCHWAY_BOOT_OK"
        def send(text):
            child.stdin.write((text + "\n").encode())
            child.stdin.flush()
        try:
            with logfile.open("wb") as log:
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([child.stdout], [], [], 1)
                    if ready:
                        data = os.read(child.stdout.fileno(), 65536)
                        if not data:
                            break
                        log.write(data)
                        log.flush()
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                        output.extend(data)
                        recent = bytes(output[-12000:])
                        if state == 0 and b"login:" in recent:
                            send("root")
                            state = 1
                            output.clear()
                        elif state == 1 and b"Password:" in recent and not installing:
                            send("Archway-QEMU-only-2026")
                            state = 2
                            output.clear()
                        elif state in (0, 1, 2) and re.search(rb"(?:root@archiso[^\r\n]*#|root@archlinux[^\r\n]*#)", recent):
                            if installing:
                                send("mkdir -p /root/archway; mount -t 9p -o trans=virtio,version=9p2000.L archway /root/archway && python /root/archway/scripts/vm-install.py")
                            else:
                                send("id archtest && test -e /boot/vmlinuz-linux && systemctl is-enabled NetworkManager && echo ARCHWAY_BOOT_OK; poweroff")
                            state = 3
                            output.clear()
                        if marker in recent and state == 3:
                            # Shell input is echoed: accept only a standalone
                            # output line, not the echoed command containing it.
                            if re.search(rb"(?:^|\n)" + marker + rb"\r?(?:\n|$)", recent):
                                child.wait(timeout=90)
                                return
                    if child.poll() is not None:
                        break
            raise RuntimeError(f"VM acceptance failed: marker {marker!r} missing; see {logfile}")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    session(install, work / "install-serial.log", True)
    session(common, work / "boot-serial.log", False)
    print(f"PASS: actual {args.firmware.upper()} installation and disk-only reboot", flush=True)


if __name__ == "__main__":
    main()
