from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import select
import subprocess
import time
import urllib.request

from .command import InstallError, Runner


def online() -> bool:
    try:
        with urllib.request.urlopen("https://geo.mirror.pkgbuild.com/core/os/x86_64/core.db", timeout=12) as response:
            return response.status == 200 and bool(response.read(64))
    except (OSError, ValueError):
        return False


def interfaces(r: Runner) -> list[dict]:
    links = json.loads(r.run(["ip", "-j", "address", "show"]))
    return [dict(name=i["ifname"], wireless=Path(f"/sys/class/net/{i['ifname']}/wireless").exists(),
                 state=i.get("operstate", "unknown"), addresses=[a["local"] for a in i.get("addr_info", [])])
            for i in links if i["ifname"] != "lo"]


def valid_interface(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", name) or not Path(f"/sys/class/net/{name}").exists():
        raise InstallError("Invalid network interface")


def scan(r: Runner, iface: str) -> list[dict]:
    valid_interface(iface)
    r.run(["systemctl", "start", "iwd"])
    r.run(["rfkill", "unblock", "wifi"])
    r.run(["ip", "link", "set", "dev", iface, "up"])
    r.run(["iwctl", "station", iface, "scan"], timeout=45)
    # iwctl scan is asynchronous. Poll until a completed scan yields networks.
    for _ in range(8):
        text = r.run(["iwctl", "station", iface, "get-networks"], timeout=20)
        networks = parse_networks(text)
        if networks:
            return networks
        time.sleep(0.5)
    return []


def parse_networks(text: str) -> list[dict]:
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    result = []
    for line in text.splitlines():
        match = re.match(r"^\s*(?:>\s*)?(.+?)\s{2,}(psk|open|8021x)\s+(\S+)\s*$", line)
        if match:
            result.append(dict(ssid=match[1].strip(), security=match[2], signal=match[3]))
    return result


def connect(r: Runner, iface: str, ssid: str, password: str, hidden=False):
    valid_interface(iface)
    if not ssid or len(ssid.encode()) > 32 or any(c in ssid + password for c in "\n\r\x00"):
        raise InstallError("Invalid SSID/passphrase")
    # iwctl's credential agent reads a terminal. Use a private PTY, never
    # --passphrase (which exposes credentials in process arguments).
    import pty
    import termios
    master, slave = pty.openpty()
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    command = ["iwctl", "station", iface, "connect-hidden" if hidden else "connect", ssid]
    process = None
    try:
        process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                                   env={**os.environ, "LC_ALL": "C"}, start_new_session=True)
        os.close(slave)
        slave = -1
        deadline = time.monotonic() + 75
        buffer = b""
        sent = False
        while process.poll() is None and time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    buffer = (buffer + os.read(master, 4096))[-8192:]
                except OSError:
                    break
                if any(prompt in buffer.lower() for prompt in (b"passphrase", b"password")):
                    if not sent:
                        os.write(master, (password + "\n").encode())
                        sent = True
                        buffer = b""
        try:
            code = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise InstallError("Wi-Fi connection timed out; rescan and check credentials") from None
        if code:
            raise InstallError("Wi-Fi connection failed; check password, rfkill and signal. Enterprise Wi-Fi requires manual iwd setup.")
        r.note(f"Wi-Fi association completed on {iface}; credentials omitted")
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        if slave != -1:
            os.close(slave)
    wait_online()


def wait_online():
    for _ in range(6):
        if online():
            return
        time.sleep(1)
    raise InstallError("Link connected but Arch repository HTTPS check failed. Check DHCP, DNS and captive portal.")


def ethernet(r: Runner, iface: str, address="", gateway="", dns=""):
    valid_interface(iface)
    if address:
        address = str(ipaddress.IPv4Interface(address))
        gateway = str(ipaddress.IPv4Address(gateway))
        servers = [str(ipaddress.ip_address(s)) for s in dns.split()]
        if not servers:
            raise InstallError("At least one DNS server is required")
        body = f"[Match]\nName={iface}\n[Network]\nAddress={address}\nGateway={gateway}\n" + "".join(f"DNS={s}\n" for s in servers)
    else:
        body = f"[Match]\nName={iface}\n[Network]\nDHCP=yes\n"
    directory = Path("/run/systemd/network")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"00-archway-{iface}.network").write_text(body)
    r.run(["systemctl", "start", "systemd-networkd", "systemd-resolved"])
    r.run(["ip", "link", "set", "dev", iface, "up"])
    r.run(["networkctl", "reload"])
    r.run(["networkctl", "reconfigure", iface])
    wait_online()
