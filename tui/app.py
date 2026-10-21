from __future__ import annotations

import copy
import curses
from dataclasses import replace
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from installer import __version__
from installer.command import InstallError, Runner
from installer.config import Config, DESKTOPS, FILESYSTEMS, KERNELS, Partition, Secrets
from installer.core import Installer, summary
from installer import disks, hardware, networking, packages
from installer.partitions import describe
from .widgets import Cancelled, UI


class App:
    def __init__(self, screen, demo=False):
        self.ui = UI(screen)
        self.demo = demo
        self.events = queue.Queue()
        self.lines = []
        self.runner = Runner(None if demo else Path("/var/log/archway-live.log"), self.log)
        self.hw = hardware.demo_hardware() if demo else hardware.detect(self.runner)
        self.c = Config(firmware=self.hw["firmware"], bootloader="systemd-boot" if self.hw["firmware"] == "UEFI" else "grub")
        self.secrets = Secrets()
        self.internet = False if demo else networking.online()
        self.dirty_storage = None

    def log(self, line):
        self.events.put(("log", line))

    def drain(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.lines.extend(value.splitlines())
                self.lines = self.lines[-3000:]

    def error(self, exc):
        self.ui.view("Operation stopped", str(exc), "Review the cause before retrying. No automatic rollback is promised.")

    def run(self):
        while True:
            try:
                self.drain()
                subtitle = (f"v{__version__} | {'DEMO / NO SYSTEM CHANGES' if self.demo else self.hw['firmware']} | "
                            f"Internet: {'ready' if self.internet else 'not checked / offline'} | RAM: {self.hw['ram']}")
                selected = self.ui.menu("Welcome", ["Install Arch Linux", "Configure Network", "Hardware Information",
                                                        "Advanced Options", "View Logs", "Exit"], subtitle,
                                        info=["CPU: " + self.hw['cpu'], "GPU: " + "; ".join(self.hw['gpus']),
                                              "Power: " + self.hw['battery'] + f" | Secure Boot: {self.hw['secure_boot']}"])
                if selected == 0:
                    self.install_menu()
                elif selected == 1:
                    self.network()
                elif selected == 2:
                    self.ui.view("Hardware Information", json.dumps(self.hw, indent=2, ensure_ascii=False))
                elif selected == 3:
                    self.advanced()
                elif selected == 4:
                    self.drain()
                    self.ui.view("Diagnostic log (no credentials)", self.lines or ["No operations yet"])
                elif selected == 5:
                    if self.dirty_storage:
                        self.ui.view("Mounted installation remains", "Use Advanced Options > Clean up mounts before exit, or inspect /mnt from another console.")
                    return
            except Cancelled:
                continue
            except (InstallError, OSError, ValueError) as exc:
                self.error(exc)

    def busy(self, title, action):
        outcome = queue.Queue()
        def run():
            try:
                outcome.put((True, action()))
            except Exception as exc:
                outcome.put((False, exc))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        while thread.is_alive():
            self.drain()
            self.ui.frame(title, "Operation in progress. Waiting for the actual result.", "Please wait")
            h, _ = self.ui.screen.getmaxyx()
            for row, line in enumerate(self.lines[-max(1, h - 9):], 5):
                self.ui.put(row, 2, line)
            self.ui.screen.refresh()
            thread.join(0.1)
        ok, result = outcome.get()
        if not ok:
            raise result
        return result

    def pick(self, title, choices, current):
        labels = [f"{'●' if option == current else ' '} {option}" for option in choices]
        return choices[self.ui.menu(title, labels, selected=choices.index(current) if current in choices else 0)]

    def install_menu(self):
        while True:
            c = self.c
            in_menu = True
            try:
                labels = [f"Disk / partitions: {c.disk or 'NOT SELECTED'} ({c.mode})", f"Kernel: {c.kernel}",
                          f"Bootloader: {c.bootloader}", f"Desktop: {c.desktop}", "User, password and system settings",
                          f"Drivers: {c.gpu_driver} / Bluetooth: {c.bluetooth}", f"Optional software: {len(c.extras)} selected",
                          "Review full plan / DRY RUN", "Start Installation", "Back"]
                selected = self.ui.menu("Installation configuration", labels, "Configure each section, review the plan, then start")
                in_menu = False
                if selected == 0:
                    self.storage()
                elif selected == 1:
                    c.kernel = self.pick("Kernel", list(KERNELS), c.kernel)
                elif selected == 2:
                    c.bootloader = self.pick("Bootloader", ["systemd-boot", "grub"] if c.firmware == "UEFI" else ["grub"], c.bootloader)
                elif selected == 3:
                    desktop = self.pick("Desktop environment", list(DESKTOPS), c.desktop)
                    if desktop == "hyprland":
                        self.ui.view("Hyprland session", "Log in on a TTY after reboot and run Hyprland. SUPER+Enter opens foot; SUPER+D opens fuzzel. GPU support varies, especially with Nouveau. No automatic login.")
                    c.desktop = desktop
                elif selected == 4:
                    self.accounts()
                elif selected == 5:
                    self.drivers()
                elif selected == 6:
                    options = [p for group in packages.EXTRAS.values() for p in group]
                    c.extras = self.ui.checklist("Optional software — Steam enables official multilib", options, c.extras)
                elif selected == 7:
                    self.review()
                elif selected == 8:
                    self.start()
                else:
                    return
            except Cancelled:
                if in_menu:
                    return
                continue
            except (InstallError, OSError, ValueError) as exc:
                self.error(exc)

    def storage(self):
        available = [disks.demo_disk()] if self.demo else self.busy("Inspecting disks", lambda: disks.inventory(self.runner))
        if not available:
            raise InstallError("No disks detected")
        disk = available[self.ui.menu("Select target disk", [d.label() for d in available], "Mounted devices, swap devices and live media are protected")]
        if disk.blocked:
            raise InstallError(disk.blocked)
        details = [disk.label()]
        for node in disks.walk(disk.node.get("children", [])):
            details.append(f"{node['path']} | {int(node['size']) / 1024**3:.2f} GiB | {node.get('fstype') or '?'} | {node.get('label') or ''} | {node.get('parttype') or ''}")
        details.append("NTFS/BitLocker and existing EFI contents may belong to Windows. The installer never shrinks Windows partitions.")
        self.ui.view("Existing partition inventory", details)
        c = copy.deepcopy(self.c)
        c.disk, c.fingerprint = disk.path, disk.identity
        c.mode = self.pick("Partition mode", ["automatic", "manual"], c.mode)
        c.filesystem = self.pick("Root filesystem", list(FILESYSTEMS), c.filesystem)
        if c.mode == "automatic":
            c.home_gib = int(self.ui.input("Separate /home size in GiB (0 = shared root)", str(c.home_gib)))
            c.swap_gib = int(self.ui.input("Disk swap size in GiB (0 = none)", str(c.swap_gib)))
            c.encrypt = self.ui.confirm("Encrypt root with LUKS2?", "Separate home/swap must be 0. /boot remains unencrypted.")
            if c.encrypt:
                secret = self.password("LUKS passphrase (at least 12 characters)")
            else:
                secret = ""
            c.partitions = []
        else:
            c.encrypt = False
            c.home_gib = c.swap_gib = 0
            secret = ""
            c.partitions = self.manual_partitions(disk, c)
        c.zram = self.ui.confirm("Enable ZRAM swap?", "Compressed RAM swap; no hibernation support")
        c.snapshots = c.filesystem == "btrfs" and self.ui.confirm("Enable hourly local Btrfs snapshots?", "Snapper timeline; snapshots are not backups")
        c.validate(size=int(disk.node["size"]) if c.mode == "automatic" else None)
        if c.mode == "manual":
            from installer.partitions import validate_manual
            validate_manual(c, disk)
        self.c = c
        self.secrets.luks = secret

    def manual_partitions(self, disk, c):
        nodes = [n for n in disks.walk(disk.node.get("children", [])) if n["type"] == "part"]
        if not nodes:
            raise InstallError("No existing partitions. Use Advanced Options > Partition editor to create them, then select the disk again.")
        chosen = []
        for mount in ("/", "/boot", "/home", "swap"):
            options = [n for n in nodes if n["path"] not in [p.device for p in chosen]]
            labels = [f"{n['path']} | {int(n['size']) / 1024**3:.1f} GiB | {n.get('fstype') or 'unformatted'} | {n.get('label') or ''}" for n in options]
            if mount in ("/home", "swap"):
                labels.append("Skip")
            if not labels:
                raise InstallError("Insufficient partitions for root and separate boot")
            index = self.ui.menu(f"Select partition for {mount}", labels)
            if index == len(options):
                continue
            node = options[index]
            fs = c.filesystem if mount == "/" else "vfat" if mount == "/boot" and c.firmware == "UEFI" else "ext4" if mount == "/boot" else "swap" if mount == "swap" else self.pick("Home filesystem", list(FILESYSTEMS), c.filesystem)
            formatting = True
            if mount != "/":
                formatting = self.ui.confirm(f"FORMAT {node['path']}?", "No preserves its existing filesystem. Shared Windows EFI should normally be preserved.")
            chosen.append(Partition(node["path"], mount, fs, formatting))
        return chosen

    def password(self, title):
        value = self.ui.input(title, secret=True)
        repeat = self.ui.input("Repeat to confirm", secret=True)
        if value != repeat:
            raise InstallError("Passwords do not match")
        return value

    def accounts(self):
        while True:
            c = self.c
            index = self.ui.menu("Accounts and system", [f"Hostname: {c.hostname}", f"Username: {c.username}",
                                f"User password: {'set' if self.secrets.password else 'REQUIRED'}",
                                f"Root password: {'set' if self.secrets.root_password else 'locked'}",
                                f"Sudo: {c.sudo}", f"Timezone: {c.timezone}", f"Locale / language: {c.locale}",
                                f"Keyboard: {c.keymap}", f"NTP in target: {c.ntp}", "Back"])
            if index == 0:
                c.hostname = self.ui.input("Hostname", c.hostname)
            elif index == 1:
                c.username = self.ui.input("Username", c.username)
            elif index == 2:
                self.secrets.password = self.password("User password (at least 8 characters)")
            elif index == 3:
                self.secrets.root_password = self.password("Root password (empty locks root)")
            elif index == 4:
                c.sudo = not c.sudo
            elif index == 5:
                c.timezone = self.ui.input("IANA timezone", c.timezone, hint="Example: Europe/Warsaw")
            elif index == 6:
                c.locale = self.ui.input("System UTF-8 locale", c.locale, hint="Example: pl_PL.UTF-8 or en_US.UTF-8")
            elif index == 7:
                c.keymap = self.ui.input("Console keymap", c.keymap, hint="Example: pl, us, de")
            elif index == 8:
                c.ntp = not c.ntp
            else:
                return

    def drivers(self):
        while True:
            _, reason = packages.resolve(self.c, self.hw)
            index = self.ui.menu("Graphics and Bluetooth", [f"GPU selection: {self.c.gpu_driver}", "Explain recommendation",
                                f"Bluetooth service / firmware: {self.c.bluetooth}", "Back"])
            if index == 0:
                choice = self.pick("GPU driver policy", ["auto", "mesa", "nouveau", "nvidia-open"], self.c.gpu_driver)
                candidate = replace(self.c, gpu_driver=choice)
                packages.resolve(candidate, self.hw)
                self.c.gpu_driver = choice
            elif index == 1:
                self.ui.view("Driver recommendation", reason)
            elif index == 2:
                self.c.bluetooth = not self.c.bluetooth
            else:
                return

    def review(self):
        self.c.validate()
        self.ui.view("DRY RUN — no commands executed", summary(self.c, self.hw), "All FORMAT entries destroy data. Preserved EFI still receives bootloader files.")

    def start(self):
        self.c.validate()
        self.review()
        choice = self.ui.menu("Installation decision", ["Edit Configuration", "Cancel", "Start Installation"], "All changes and warnings are listed in the full plan")
        if choice != 2:
            return
        if self.demo:
            self.ui.view("DEMO completed safely", "The full plan was generated. Demo mode never runs installation, network or disk commands.")
            return
        if self.dirty_storage:
            raise InstallError("Previous run has mounted resources. Inspect or clean up before restarting.")
        self.secrets.validate(self.c)
        token = f"{'ERASE' if self.c.mode == 'automatic' else 'FORMAT'} {self.c.disk}"
        confirmation = self.ui.input("FINAL DATA LOSS CONFIRMATION", hint=f"Type exactly: {token}")
        if confirmation != token:
            raise InstallError("Confirmation did not match; installation was not started")
        engine = Installer(self.runner, lambda done, total, name: self.events.put(("progress", (done, total, name))))
        result = queue.Queue()
        def install():
            try:
                engine.install(copy.deepcopy(self.c), self.secrets, self.hw, confirmation)
                result.put(None)
            except Exception as exc:
                result.put(exc)
        thread = threading.Thread(target=install, daemon=True)
        thread.start()
        done, total, name = 0, 9, "Starting"
        while thread.is_alive() or not self.events.empty():
            try:
                kind, value = self.events.get(timeout=0.1)
                if kind == "progress":
                    done, total, name = value
                else:
                    self.lines.extend(value.splitlines())
                    self.lines = self.lines[-3000:]
            except queue.Empty:
                pass
            self.ui.frame("Installing Arch Linux", name, "Installation is running. Follow the log; do not power off.")
            h, w = self.ui.screen.getmaxyx()
            width = max(1, w - 10)
            completed = int(width * done / total)
            self.ui.put(5, 3, "[" + "#" * completed + "·" * (width - completed) + f"] {done}/{total}", curses.color_pair(5))
            for row, line in enumerate(self.lines[-max(1, h - 11):], 7):
                self.ui.put(row, 2, line)
            self.ui.screen.refresh()
        thread.join()
        error = result.get()
        if error:
            if engine.storage.mounts or engine.storage.mapper or engine.storage.swaps:
                self.dirty_storage = engine.storage
            self.ui.view("Installation stopped", [str(error), f"Failed stage: {engine.stage}",
                         f"Disk changes started: {engine.destructive_started}",
                         "No automatic retry or rollback of formatting. Inspect /mnt and logs on another console.",
                         "Use Advanced Options to retry safe package downloads or clean up owned mounts."])
        else:
            self.secrets.password = self.secrets.root_password = self.secrets.luks = self.secrets.wifi_password = ""
            self.ui.view("Installation complete", "All configured stages passed. Remove the ISO after reboot. Hyprland users: log in on a TTY and run Hyprland.")
            if self.ui.confirm("Reboot now?", "Choose No to return to the menu"):
                self.runner.run(["systemctl", "reboot"])

    def network(self):
        if self.demo:
            self.ui.view("Network — DEMO", "Live mode detects interfaces, scans iwd networks, supports hidden SSIDs, wired DHCP/static IPv4, and checks Arch HTTPS access. Demo never changes host networking.")
            return
        while True:
            choice = self.ui.menu("Configure Network", ["Wi-Fi / scan / hidden SSID", "Ethernet DHCP", "Ethernet static IPv4", "Status and HTTPS repository test", "Back"])
            if choice == 4:
                return
            devices = networking.interfaces(self.runner)
            if choice == 3:
                self.internet = self.busy("Testing repository access", networking.online)
                routes = self.runner.run(["ip", "route", "show"])
                self.ui.view("Network status", json.dumps(devices, indent=2) + "\n" + routes + f"\nArch HTTPS reachable: {self.internet}")
                continue
            options = [d for d in devices if d["wireless"] == (choice == 0)]
            if not options:
                raise InstallError("No matching interface found; inspect rfkill, firmware and hardware")
            iface = options[self.ui.menu("Select interface", [d["name"] + " | " + d["state"] for d in options])]["name"]
            if choice == 0:
                while True:
                    networks = self.busy("Scanning Wi-Fi networks", lambda: networking.scan(self.runner, iface))
                    labels = [f"{n['ssid']} | {n['signal']} | {n['security']}" for n in networks] + ["Hidden SSID", "Rescan"]
                    index = self.ui.menu("Wi-Fi networks", labels)
                    if index == len(networks) + 1:
                        continue
                    hidden = index == len(networks)
                    ssid = self.ui.input("Hidden SSID") if hidden else networks[index]["ssid"]
                    security = self.pick("Wi-Fi security", ["wpa-psk", "sae", "open"], "wpa-psk")
                    if not hidden and networks[index]["security"] == "8021x":
                        raise InstallError("Enterprise 802.1X requires manual iwd configuration")
                    password = self.ui.input("Wi-Fi passphrase", secret=True) if security != "open" else ""
                    self.busy("Connecting to Wi-Fi", lambda: networking.connect(self.runner, iface, ssid, password, hidden))
                    self.c.wifi_ssid, self.c.wifi_security, self.c.wifi_hidden = ssid, security, hidden
                    self.secrets.wifi_password = password
                    self.c.net_address = self.c.net_gateway = self.c.net_dns = ""
                    self.c.network = f"Wi-Fi {ssid} on {iface}"
                    break
            else:
                address = self.ui.input("IPv4 address with prefix", hint="Example: 192.168.1.20/24") if choice == 2 else ""
                gateway = self.ui.input("Gateway IPv4") if choice == 2 else ""
                dns = self.ui.input("DNS servers separated by spaces", "1.1.1.1 9.9.9.9") if choice == 2 else ""
                self.busy("Applying wired configuration", lambda: networking.ethernet(self.runner, iface, address, gateway, dns))
                self.c.net_address, self.c.net_gateway, self.c.net_dns = address, gateway, dns
                self.c.wifi_ssid = ""
                self.secrets.wifi_password = ""
                self.c.network = f"Ethernet {iface}: {address or 'DHCP'}"
            self.c.net_interface = iface
            self.internet = True
            self.ui.view("Network ready", "HTTPS access to the Arch repository succeeded. Connection settings will be saved for NetworkManager in the installed system.")

    def advanced(self):
        while True:
            choice = self.ui.menu("Advanced Options", ["Partition editor (cfdisk)", f"Detect other operating systems with GRUB: {self.c.os_prober}",
                                 "Retry package download into mounted target", "Clean up mounts from failed installation",
                                 f"Serial console ttyS0: {self.c.serial_console}", "Back"])
            if choice == 5:
                return
            if choice == 4:
                self.c.serial_console = not self.c.serial_console
                continue
            if choice == 1:
                self.c.os_prober = not self.c.os_prober
                continue
            if self.demo:
                self.ui.view("DEMO", "This action is disabled in demo mode; no host commands are run.")
                continue
            if choice == 0:
                available = disks.inventory(self.runner)
                if not available:
                    raise InstallError("No disks found")
                disk = available[self.ui.menu("Partition editor target", [d.label() for d in available])]
                if disk.blocked:
                    raise InstallError(disk.blocked)
                self.ui.view("Partition editing safety", [disk.label(), "cfdisk is an external keyboard partition editor. Review its layout and explicit Write confirmation before saving.", "No Windows shrinking is performed. Existing configurations must be rebuilt after editing."])
                token = f"EDIT {disk.path}"
                if self.ui.input("Authorize partition editor", hint=f"Type: {token}") != token:
                    continue
                disks.checked_disk(self.runner, disk.path, disk.identity)
                curses.def_prog_mode()
                curses.endwin()
                try:
                    subprocess.run(["cfdisk", disk.path], check=False)
                finally:
                    curses.reset_prog_mode()
                    self.ui.screen.clear()
                    self.c.disk = self.c.fingerprint = ""
                    self.c.partitions = []
            elif choice == 2:
                if not self.dirty_storage or "/mnt" not in self.dirty_storage.mounts:
                    raise InstallError("No mounted installation owned by this run")
                if self.ui.confirm("Retry safe package download?", "Only pacman runs in the target; disks are never reformatted"):
                    resolved, _ = packages.resolve(self.c, self.hw)
                    self.busy("Retrying packages", lambda: self.runner.chroot(["pacman", "-S", "--needed", "--noconfirm", *resolved], timeout=14400))
                    self.ui.view("Packages retried", "This does not resume later installation stages. Inspect/configure the target manually or clean up and start a fresh reviewed installation.")
            elif choice == 3:
                if not self.dirty_storage:
                    raise InstallError("No resources are held by this run")
                if self.ui.confirm("Unmount failed installation?", "Only mounts/swap/mappers opened by this run are released"):
                    self.busy("Cleaning up owned mounts", self.dirty_storage.cleanup)
                    self.dirty_storage = None


def launch(demo=False):
    curses.wrapper(lambda screen: App(screen, demo).run())
