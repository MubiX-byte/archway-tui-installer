"""One audited subprocess boundary. Never invoke a shell or log secret input."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Callable


class InstallError(RuntimeError):
    """An actionable error safe to show in the TUI."""


class Runner:
    def __init__(self, log: Path | None = None, emit: Callable[[str], None] | None = None):
        self.log = log
        self.emit = emit or (lambda line: None)
        if log:
            log.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            os.close(fd)
            os.chmod(log, 0o600)

    def note(self, message: str):
        self.emit(message)
        if self.log:
            with self.log.open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")

    def run(self, argv: list[str], *, input: str | None = None, secret=False,
            timeout=1800, check=True) -> str:
        self.note("$ " + shlex.join(argv))
        try:
            result = subprocess.run(argv, input=input, text=True, capture_output=True,
                                    timeout=timeout, env={**os.environ, "LC_ALL": "C"})
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstallError(f"Cannot complete {argv[0]}: {type(exc).__name__}") from None
        # Never record output from a process handling credentials, even on failure.
        output = (result.stdout + result.stderr).strip()
        if output and not secret:
            self.note(output[-24000:])
        if check and result.returncode:
            detail = "Credential operation failed" if secret else output[-2500:]
            raise InstallError(f"{argv[0]} exited {result.returncode}: {detail}")
        return result.stdout

    def chroot(self, argv: list[str], **kwargs) -> str:
        return self.run(["arch-chroot", "/mnt", *argv], **kwargs)


def write_target(relative: str, content: str, mode=0o644, root=Path("/mnt")):
    """Refuse target escape, including symlinks from a retained filesystem."""
    dest = root / relative.lstrip("/")
    if not dest.resolve().is_relative_to(root.resolve()):
        raise InstallError(f"Target path escapes installation root: {relative}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        raise InstallError(f"Refusing symlink: {relative}")
    dest.write_text(content, encoding="utf-8")
    dest.chmod(mode)
