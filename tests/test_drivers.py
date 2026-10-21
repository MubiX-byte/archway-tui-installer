from dataclasses import replace
import unittest

from installer.command import InstallError
from installer.drivers import recommend
from installer.hardware import demo_hardware
from installer.packages import DESKTOP_PACKAGES, resolve
from main import demo_config


class DriverTests(unittest.TestCase):
    def hw(self, *names):
        return {**demo_hardware(), "gpus": list(names)}

    def test_legacy_nvidia_never_gets_modern_driver_automatically(self):
        p, reason = recommend(self.hw("NVIDIA GP104 GTX 1080"), "linux")
        self.assertIn("xf86-video-nouveau", p)
        self.assertNotIn("nvidia-open-dkms", p)
        self.assertIn("legacy", reason)

    def test_unknown_nvidia_is_rejected_for_open_driver(self):
        for name in ("NVIDIA GP104", "NVIDIA RTX mystery", "NVIDIA GV100", "AMD Radeon"):
            with self.assertRaises(InstallError):
                recommend(self.hw(name), "linux", "nvidia-open")

    def test_supported_nvidia_headers_follow_kernel(self):
        for kernel in ("linux", "linux-lts", "linux-zen", "linux-hardened"):
            p, _ = recommend(self.hw("NVIDIA AD104 RTX 4070"), kernel, "nvidia-open")
            self.assertIn(f"{kernel}-headers", p)
            self.assertIn("nvidia-open-dkms", p)

    def test_hybrid_keeps_both_vendors(self):
        p, reason = recommend(self.hw("Intel Graphics", "NVIDIA TU106"), "linux", "nvidia-open")
        self.assertIn("vulkan-intel", p)
        self.assertIn("nvidia-open-dkms", p)
        self.assertIn("Hybrid", reason)

    def test_microcode_and_all_desktops(self):
        for desktop in DESKTOP_PACKAGES:
            p, _ = resolve(replace(demo_config(), desktop=desktop), demo_hardware())
            self.assertIn("amd-ucode", p)
            self.assertTrue(set(DESKTOP_PACKAGES[desktop]).issubset(p))

    def test_unknown_extra_rejected(self):
        with self.assertRaises(InstallError):
            resolve(replace(demo_config(), extras=["malicious;command"]), demo_hardware())

    def test_steam_multilib_has_vendor_runtime(self):
        p, _ = resolve(replace(demo_config(), extras=["steam"]), demo_hardware())
        self.assertIn("lib32-vulkan-radeon", p)
