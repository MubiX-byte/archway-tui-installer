from pathlib import Path

from .command import InstallError, Runner, write_target
from .config import Config


def kernel_options(c: Config, uuid: str, luks_uuid="") -> str:
    root = "/dev/mapper/archway-root" if c.encrypt else f"UUID={uuid}"
    options = f"root={root} rw"
    if c.encrypt:
        if not luks_uuid:
            raise InstallError("Missing LUKS UUID")
        options += f" rd.luks.name={luks_uuid}=archway-root"
    if c.filesystem == "btrfs":
        options += " rootflags=subvol=@"
    if c.serial_console:
        options += " console=tty0 console=ttyS0,115200n8"
    return options


def install(r: Runner, c: Config, root_raw: str, root_device: str):
    uuid = r.run(["blkid", "-s", "UUID", "-o", "value", root_device]).strip()
    luks = r.run(["cryptsetup", "luksUUID", root_raw]).strip() if c.encrypt else ""
    if not uuid:
        raise InstallError("Root filesystem UUID is missing")
    options = kernel_options(c, uuid, luks)
    if c.bootloader == "systemd-boot":
        r.chroot(["bootctl", "--esp-path=/boot", "install"])
        # Explicit entries; current mkinitcpio microcode hook embeds the CPU
        # microcode in the initramfs, so a separate ucode image is unnecessary.
        write_target("/boot/loader/loader.conf", "default archway.conf\ntimeout 4\neditor no\n")
        write_target("/boot/loader/entries/archway.conf",
                     f"title Arch Linux ({c.kernel})\nlinux /vmlinuz-{c.kernel}\ninitrd /initramfs-{c.kernel}.img\noptions {options}\n")
        r.chroot(["bootctl", "--esp-path=/boot", "is-installed"])
        if not Path("/mnt/boot/EFI/systemd/systemd-bootx64.efi").is_file():
            raise InstallError("systemd-boot EFI binary missing")
    else:
        if c.firmware == "UEFI":
            r.chroot(["grub-install", "--target=x86_64-efi", "--efi-directory=/boot", "--bootloader-id=Archway"])
        else:
            r.chroot(["grub-install", "--target=i386-pc", c.disk])
        # GRUB generates root= itself. Extra options are needed for LUKS/Btrfs.
        extra = " ".join(word for word in options.split() if word.startswith(("rd.luks.", "rootflags=", "console=")))
        write_target("/etc/default/grub", f'GRUB_DEFAULT=0\nGRUB_TIMEOUT=5\nGRUB_DISTRIBUTOR="Arch"\nGRUB_CMDLINE_LINUX="{extra}"\nGRUB_DISABLE_OS_PROBER={"false" if c.os_prober else "true"}\n')
        r.chroot(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
        r.chroot(["grub-script-check", "/boot/grub/grub.cfg"])
    for file in (f"vmlinuz-{c.kernel}", f"initramfs-{c.kernel}.img"):
        if not Path("/mnt/boot", file).is_file():
            raise InstallError(f"Missing boot image: {file}")
