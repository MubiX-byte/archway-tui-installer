import contextlib
from dataclasses import replace
import io
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from installer.bootloader import kernel_options
from installer.command import InstallError
from installer.config import Secrets
from installer.core import Installer, summary
from installer.hardware import demo_hardware, detect
from installer.packages import verify
from installer.partitions import Storage
from main import demo_config, main


class EngineTests(unittest.TestCase):
    def test_wrong_confirmation_never_enters_preflight(self):
        r = Mock()
        with patch("installer.core.preflight") as preflight:
            with self.assertRaises(InstallError):
                Installer(r).install(demo_config(), Secrets(password="password-long"), demo_hardware(), "yes")
            preflight.assert_not_called()
        r.run.assert_not_called()

    def test_offline_preflight_failure_never_formats(self):
        engine = Installer(Mock())
        with patch("installer.core.preflight", side_effect=InstallError("offline")), patch.object(engine.storage, "prepare") as prepare:
            with self.assertRaisesRegex(InstallError, "offline"):
                engine.install(demo_config(), Secrets(password="password-long"), demo_hardware(), "ERASE /dev/demo0")
            prepare.assert_not_called()
            self.assertFalse(engine.destructive_started)

    def test_package_failure_precedes_destructive_boundary(self):
        engine = Installer(Mock())
        real_temp = tempfile.TemporaryDirectory
        with patch("installer.core.preflight"), patch("installer.core.tempfile.TemporaryDirectory", side_effect=lambda **kwargs: real_temp()), patch("installer.core.packages.verify", side_effect=InstallError("missing package")), patch.object(engine.storage, "prepare") as prepare:
            with self.assertRaisesRegex(InstallError, "missing package"):
                engine.install(demo_config(), Secrets(password="password-long"), demo_hardware(), "ERASE /dev/demo0")
            prepare.assert_not_called()
            self.assertFalse(engine.destructive_started)

    def test_uuid_and_encrypted_btrfs_boot_options(self):
        c = replace(demo_config(), encrypt=True, filesystem="btrfs")
        opts = kernel_options(c, "fs-uuid", "luks-uuid")
        self.assertIn("root=/dev/mapper/archway-root", opts)
        self.assertIn("rd.luks.name=luks-uuid=archway-root", opts)
        self.assertIn("rootflags=subvol=@", opts)
        self.assertEqual(kernel_options(demo_config(), "root-uuid"), "root=UUID=root-uuid rw")

    def test_missing_package_detected(self):
        r = Mock()
        r.run.side_effect = ["", "base\nlinux\n", "xfce4 package\n"]
        with self.assertRaisesRegex(InstallError, "unavailable-name"):
            verify(r, ["base", "unavailable-name"], "/run/pacman.conf")

    def test_groups_verified_in_official_repositories(self):
        r = Mock()
        r.run.side_effect = ["", "base\nlinux\n", "xfce4 thunar\n", "base 1\nxfce4 2\n"]
        verify(r, ["base", "xfce4"], "/run/pacman.conf")
        self.assertEqual(r.run.call_args.args[0][-2:], ["base", "xfce4"])

    def test_cleanup_only_owned_resources_in_reverse_order(self):
        r = Mock()
        storage = Storage(r)
        storage.mounts = ["/mnt", "/mnt/home", "/mnt/boot"]
        storage.swaps = ["/dev/demo0p3"]
        storage.mapper = True
        storage.cleanup()
        commands = [c.args[0] for c in r.run.call_args_list]
        self.assertEqual(commands, [["swapoff", "/dev/demo0p3"], ["umount", "/mnt/boot"], ["umount", "/mnt/home"], ["umount", "/mnt"], ["cryptsetup", "close", "archway-root"]])

    def test_cleanup_busy_mount_stops_without_closing_mapper(self):
        r = Mock()
        r.run.side_effect = InstallError("busy")
        storage = Storage(r)
        storage.mounts = ["/mnt"]
        storage.mapper = True
        with self.assertRaises(InstallError):
            storage.cleanup()
        self.assertTrue(storage.mapper)
        self.assertEqual(storage.mounts, ["/mnt"])

    def test_demo_plans_make_no_subprocess_or_network_calls(self):
        for firmware in ("UEFI", "BIOS"):
            with patch("subprocess.run") as run, patch("urllib.request.urlopen") as network, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--demo", "--plan", "--firmware", firmware, "--json"]), 0)
                self.assertEqual(json.loads(output.getvalue())["firmware"], firmware)
                run.assert_not_called()
                network.assert_not_called()

    def test_hardware_is_mockable(self):
        r = Mock()
        def command(argv, **kwargs):
            if argv[0] == "lscpu":
                return '{"lscpu": [{"field":"Vendor ID:","data":"GenuineIntel"},{"field":"Model name:","data":"Test Intel"}]}'
            if argv[0] == "lspci":
                return '0000:01:00.0 VGA compatible controller: NVIDIA TU106 [10de:1f06]'
            return ""
        r.run.side_effect = command
        hw = detect(r)
        self.assertEqual(hw["vendor"], "GenuineIntel")
        self.assertIn("TU106", hw["gpus"][0])

    def test_summary_discloses_erase_and_driver_policy(self):
        lines = "\n".join(summary(demo_config(), demo_hardware()))
        self.assertIn("ERASE ENTIRE DISK", lines)
        self.assertIn("FORMAT / DATA LOSS", lines)
        self.assertIn("amd-ucode", lines)
