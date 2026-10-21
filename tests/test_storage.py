import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from installer.command import InstallError
from installer.config import Partition
from installer.disks import Disk, checked_disk, demo_disk, fingerprint, inventory, partition_path
from installer.partitions import describe, plan, validate_manual
from main import demo_config


class PlanTests(unittest.TestCase):
    def test_uefi_esp_and_root(self):
        layout = plan(demo_config())
        self.assertIn("label: gpt", layout.table)
        self.assertEqual([(p.mount, p.fs) for p in layout.partitions], [("/boot", "vfat"), ("/", "ext4")])

    def test_bios_has_bios_grub_and_unencrypted_boot(self):
        layout = plan(replace(demo_config("BIOS"), encrypt=True))
        self.assertIn("21686148-6449-6e6f-744e-656564454649", layout.table)
        self.assertEqual(layout.partitions[0].device, "/dev/demo0p2")
        self.assertEqual(layout.partitions[0].fs, "ext4")

    def test_names_for_nvme_mmc_sata(self):
        for disk, expected in (("/dev/nvme0n1", "/dev/nvme0n1p3"), ("/dev/mmcblk0", "/dev/mmcblk0p3"), ("/dev/sdb", "/dev/sdb3")):
            self.assertEqual(partition_path(disk, 3), expected)

    def test_optional_home_swap_not_root(self):
        c = replace(demo_config(), home_gib=32, swap_gib=4)
        self.assertEqual([p.mount for p in plan(c).partitions], ["/boot", "swap", "/home", "/"])
        self.assertIn("size=32GiB", plan(c).table)

    def test_preserved_efi_is_never_marked_format(self):
        c = replace(demo_config(), mode="manual", partitions=[Partition("/dev/demo0p2", "/", "ext4"), Partition("/dev/demo0p1", "/boot", "vfat", False)])
        self.assertEqual(plan(c).table, "")
        self.assertIn("PRESERVE filesystem /dev/demo0p1 -> /boot (vfat)", describe(c))


class ProtectionTests(unittest.TestCase):
    def node(self):
        n = copy.deepcopy(demo_disk().node)
        n.update(ro=False, pttype="gpt", mountpoints=[None])
        n["children"] = [dict(path="/dev/demo0p1", type="part", size=2 * 1024**3, fstype="vfat", mountpoints=[None],
                              parttype="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"),
                          dict(path="/dev/demo0p2", type="part", size=64 * 1024**3, fstype="ext4", mountpoints=[None])]
        return n

    def inventory(self, n):
        runner = Mock()
        runner.run.side_effect = [json.dumps({"blockdevices": [n]}), '{"loopdevices": []}']
        return inventory(runner)[0]

    def test_live_partition_and_swap_block_entire_disk(self):
        for mount in ("/run/archiso/bootmnt", "[SWAP]", "/mnt", "/"):
            n = self.node()
            n["children"][0]["mountpoints"] = [mount]
            self.assertTrue(self.inventory(n).blocked)

    def test_readonly_and_active_mapper_blocked(self):
        n = self.node()
        n["ro"] = True
        self.assertTrue(self.inventory(n).blocked)
        n["ro"] = False
        n["children"][0]["children"] = [dict(path="/dev/mapper/crypt", type="crypt", mountpoints=[None])]
        self.assertTrue(self.inventory(n).blocked)

    def test_unmounted_disk_allowed(self):
        self.assertFalse(self.inventory(self.node()).blocked)

    def test_device_replacement_rejected(self):
        n = self.node()
        identity = fingerprint(n)
        n["serial"] = "REPLACED"
        with patch("installer.disks.inventory", return_value=[Disk(n)]), self.assertRaises(InstallError):
            checked_disk(Mock(), n["path"], identity)

    def test_partition_metadata_change_invalidates_plan(self):
        n = self.node()
        identity = fingerprint(n)
        n["children"][0]["fstype"] = "ntfs"
        self.assertNotEqual(identity, fingerprint(n))

    def test_manual_esp_type_and_capacity(self):
        n = self.node()
        c = replace(demo_config(), mode="manual", partitions=[Partition("/dev/demo0p2", "/", "ext4"), Partition("/dev/demo0p1", "/boot", "vfat", False)])
        validate_manual(c, Disk(n))
        n["children"][0]["size"] = 100 * 1024**2
        with self.assertRaises(InstallError):
            validate_manual(c, Disk(n))

    def test_manual_cannot_use_foreign_disk_or_mismatched_preserved_fs(self):
        c = replace(demo_config(), mode="manual", partitions=[Partition("/dev/foreign1", "/boot", "vfat", False)])
        with self.assertRaises(InstallError):
            validate_manual(c, Disk(self.node()))
        c.partitions = [Partition("/dev/demo0p1", "/boot", "ext4", False)]
        with self.assertRaises(InstallError):
            validate_manual(c, Disk(self.node()))
