import json
import unittest
from dataclasses import replace

from installer.command import InstallError
from installer.config import Partition, Secrets
from main import demo_config


class ConfigTests(unittest.TestCase):
    def test_both_firmware_defaults(self):
        for mode in ("UEFI", "BIOS"):
            demo_config(mode).validate(size=128 * 1024**3)

    def test_invalid_fields(self):
        for change in ({"username": "root"}, {"username": "bad;command"}, {"hostname": "../etc"},
                       {"timezone": "../../etc"}, {"locale": "bad"}, {"keymap": "pl\nBAD"},
                       {"kernel": "oops"}, {"swap_gib": -1}, {"firmware": "BIOS", "bootloader": "systemd-boot"},
                       {"disk": "/dev/../etc"}, {"fingerprint": ""}, {"snapshots": True}):
            with self.subTest(change=change), self.assertRaises(InstallError):
                replace(demo_config(), **change).validate()

    def test_disk_capacity(self):
        with self.assertRaises(InstallError):
            replace(demo_config(), home_gib=100).validate(size=110 * 1024**3)

    def test_encryption_disallows_plaintext_home_swap(self):
        for change in ({"home_gib": 10}, {"swap_gib": 4}, {"mode": "manual"}):
            with self.assertRaises(InstallError):
                replace(demo_config(), encrypt=True, **change).validate()

    def test_password_rules_and_admin_access(self):
        with self.assertRaises(InstallError):
            Secrets(password="short").validate(demo_config())
        with self.assertRaises(InstallError):
            Secrets(password="valid-secret").validate(replace(demo_config(), sudo=False))
        with self.assertRaises(InstallError):
            Secrets(password="hello\nroot:evil").validate(demo_config())
        Secrets(password="valid-secret", root_password="root-secret").validate(replace(demo_config(), sudo=False))

    def test_public_configuration_never_contains_secrets(self):
        s = Secrets(password="very-sensitive", luks="also-sensitive")
        data = json.dumps(demo_config().public())
        self.assertNotIn(s.password, data)
        self.assertNotIn(s.luks, data)
        self.assertNotIn(s.password, repr(s))

    def test_manual_invariants(self):
        root = Partition("/dev/demo0p2", "/", "ext4")
        boot = Partition("/dev/demo0p1", "/boot", "vfat", False)
        c = replace(demo_config(), mode="manual", partitions=[root, boot])
        c.validate()
        for parts in ([root], [root, boot, boot], [replace(root, format=False), boot],
                      [root, replace(boot, fs="ext4")], [replace(root, mount="/../etc"), boot]):
            with self.assertRaises(InstallError):
                replace(c, partitions=parts).validate()
