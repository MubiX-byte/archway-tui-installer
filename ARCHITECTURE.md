# Architecture and safety boundaries

`main.py` parses read-only CLI options and gates live operation. `tui/` renders
curses screens and collects choices. `installer/config.py` owns public configuration
and a separate, non-printable Secrets object. Neither a public JSON plan nor an
installation summary contains account, Wi-Fi or encryption passwords.

`hardware.py` collects lscpu/lspci/lsusb/sysfs data; `drivers.py` computes a
conservative recommendation. `packages.py` resolves official package names and
groups. No driver installer is downloaded from the internet and no AUR build is
run as root. NVIDIA open DKMS is opt-in and requires an identified architecture.

`disks.py` inventories lsblk trees and blocks mounted/live/read-only/held devices.
Loop backing files are traced with losetup/findmnt. A SHA-256 identity binds the
device path, size, major/minor, serial, WWN, model and current partition metadata.
The fingerprint is a consistency check, not cryptographic authentication of hardware.
`partitions.py` builds the GPT or existing-partition plan. Manual editing is a
separate, explicitly authorized cfdisk process with its own Write confirmation.

`core.Installer.install` is the sole unattended destructive entry. Its ordering is:

1. Match the typed disk token and validate secrets.
2. Require official x86_64 Live ISO/root; verify firmware and Secure Boot state.
3. Require an empty, unmounted `/mnt`; validate hardware identity and manual layout.
4. Validate keymap/timezone, HTTPS reachability and synchronized clock.
5. Refresh official pacman databases; check package/group existence and resolution.
6. Re-read device identity, mounted state and manual layout immediately before writing.
7. Apply the reviewed table/filesystems, open LUKS if chosen, and mount the target.
8. pacstrap, fstab, accounts, locale, services, initramfs, bootloader, verification.
9. Sync and release only resources acquired by this run.

`command.Runner` is the subprocess boundary. All commands use argument arrays,
`shell=False` by default, exit-code checks and timeouts. Password commands use
stdin and suppress all subprocess output, including failures. Wi-Fi credentials
are handled by iwctl's agent through a private PTY without output logging. The
target NetworkManager profile is the one intentional persistent credential store
and is mode 0600. Root filesystem is always new; retained home and EFI are
mounted only after explicit selection. `write_target` rejects traversal and
symlink escapes from the target root.

The progress bar counts completed installation stages; no timer simulates work.
UI and workers communicate through a queue; curses calls remain on the main
thread. Raw terminal mode keeps Ctrl+C from accidentally killing a partitioning
worker. Network scans and package downloads may be retried from the UI; formatting
is never automatically retried. A failed installation leaves resources inspectable
and exposes an explicit cleanup action. Busy mounts stop cleanup rather than
forcing unmount or closing a still-used mapper.

Remaining safety limits: a device can change between the last check and a kernel
write, root can always modify the live machine from another console, and firmware
or hardware faults cannot be rolled back. Run only one installation session and
do not hotplug/modify target storage during installation. Back up data independently.

There is no dependency on curses in the engine; unit tests mock the Runner and
hardware boundary. Demo mode selects synthetic data and has explicit branches
that refuse networking, partition editors, package retry and actual installation.
