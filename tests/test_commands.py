import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from installer.command import InstallError, Runner, write_target


class CommandTests(unittest.TestCase):
    def test_credentials_never_logged_on_failure_or_success(self):
        for code in (0, 1):
            messages = []
            r = Runner(emit=messages.append)
            with patch("subprocess.run", return_value=subprocess.CompletedProcess([], code, "secret-output", "secret-output")) as call:
                if code:
                    with self.assertRaises(InstallError) as error:
                        r.chroot(["chpasswd"], input="alice:secret-password\n", secret=True)
                    self.assertNotIn("secret-output", str(error.exception))
                else:
                    r.chroot(["chpasswd"], input="alice:secret-password\n", secret=True)
                argv = call.call_args.args[0]
                self.assertEqual(argv[:3], ["arch-chroot", "/mnt", "chpasswd"])
                self.assertNotIn("secret-password", str(argv))
                self.assertNotIn("shell", call.call_args.kwargs)
            self.assertNotIn("secret-password", " ".join(messages))
            self.assertNotIn("secret-output", " ".join(messages))

    def test_timeout_is_actionable(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pacman", 3)):
            with self.assertRaisesRegex(InstallError, "TimeoutExpired"):
                Runner().run(["pacman", "-S", "base"])

    def test_target_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "target"
            root.mkdir()
            with self.assertRaises(InstallError):
                write_target("../outside", "bad", root=root)
            write_target("etc/hostname", "arch", root=root)
            self.assertEqual((root / "etc/hostname").read_text(), "arch")

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "target"
            outside = Path(temp) / "outside"
            root.mkdir()
            outside.mkdir()
            try:
                (root / "etc").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation needs Windows developer mode")
            with self.assertRaises(InstallError):
                write_target("etc/hostname", "bad", root=root)
