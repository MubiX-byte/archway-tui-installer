# Verification record and VM acceptance procedure

Initial development environment: Windows, Python 3.12.14, no WSL distribution,
QEMU or VirtualBox installed. No physical disk formatting was performed.

## Automated checks

- `python -m unittest discover -s tests -v`: 47 tests, successful; one symlink
  test skipped on Windows when symlink creation is not permitted.
- Python byte compilation: successful.
- Bash syntax of startup/VM scripts: successful with Git for Windows Bash.
- Both demo firmware plans: successful; tests assert no subprocess/network calls.
- `python scripts/verify-repos.py`: all 96 possible selected package/group names
  found in current official core/extra/multilib database snapshot during development.
  This check does not replace pacman's signature, dependency or build verification.
- GitHub Actions runs the unit suite on Linux/Windows, Python 3.11–3.13, and a
  real curses demo navigation smoke test inside a Linux PTY. Consult the actual
  run result; workflow presence alone is not evidence of passing execution.

## Not yet verified

- A complete Live ISO installation and successful reboot in BIOS or UEFI.
- LUKS unlock at boot; XFS/Btrfs boot; NVIDIA DKMS build on installed kernels.
- WPA2/WPA3 association against physical hardware, static network reachability,
  Bluetooth pairing, desktop rendering/audio and dual boot with actual Windows.

Mocked tests verify planning, validation, command boundaries and failure handling.
They cannot prove that boot firmware or actual hardware behaves correctly.

## Running the VM harness

On a Linux host with QEMU, install the host's QEMU and OVMF packages. Download
and verify a current official Arch ISO. Never attach physical host devices.

```bash
bash scripts/qemu-test.sh /absolute/path/archlinux.iso uefi
bash scripts/qemu-test.sh /absolute/path/archlinux.iso bios
```

The harness uses a newly created 64 GiB QCOW2, user-mode networking, 4 GiB RAM,
KVM when accessible (otherwise TCG), and isolated writable UEFI variables.
Set `OVMF_CODE`/`OVMF_VARS` if firmware paths differ on your distribution.
It prints a second command to boot the same disk without the ISO. Keep the
printed temporary directory until acceptance is complete. No files are deleted.

Inside the ISO, clone the repository and launch `bash scripts/run-installer.sh`.
Use only the virtual disk presented by QEMU. After the installer finishes,
power down, then execute the printed reboot-test command without the ISO.

## Required acceptance matrix

| Firmware | Storage | Kernel | Bootloader | Session | Required result |
|---|---|---|---|---|---|
| UEFI | ext4, automatic | linux | systemd-boot | none | Login, sudo, DHCP, NTP |
| BIOS | ext4, automatic | linux-lts | GRUB | XFCE | Boot from disk, graphical login |
| UEFI | Btrfs + ZRAM | linux-zen | systemd-boot | Plasma | Subvolumes, portal, sound |
| UEFI | XFS | linux-hardened | GRUB | GNOME | Login and service checks |
| UEFI | LUKS2/Btrfs | linux | systemd-boot | none | Unlock with correct secret; reject wrong one |
| BIOS | LUKS2/ext4 | linux-lts | GRUB | none | Separate /boot, unlock and login |
| UEFI | manual retained ESP/home | linux | GRUB | Cinnamon | Existing files retained |
| UEFI | manual retained Windows-like ESP | linux | systemd-boot | i3 | Microsoft directory unchanged |
| UEFI | ext4 | linux | systemd-boot | Hyprland | TTY login then functional session |

Also test cancellation before typed confirmation, mistyped token, disk identity
change, mounted/live media protection, absent packages, network loss before and
after formatting, busy cleanup, bad Wi-Fi password, and Secure Boot rejection.
Use disposable disk images and snapshots; destructive tests must never reference
host block devices. For ESP retention, record file hashes before/after.

After each successful boot check `findmnt`, `lsblk -f`, `systemctl --failed`,
`systemctl is-enabled NetworkManager`, `locale`, `timedatectl`, `sudo -v`, and
an HTTPS download. For Btrfs check `btrfs subvolume list /`, for ZRAM `zramctl`,
for Bluetooth `bluetoothctl show`, and for NVIDIA `dkms status`/`modinfo nvidia`.
Record the ISO date/checksum, repo commit, exact GPU PCI IDs, kernel version,
selected options, command output and pass/fail result. Do not publish credentials.
