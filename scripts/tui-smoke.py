#!/usr/bin/env python3
"""Exercise the real curses demo inside a Linux PTY; never touches host disks."""
import fcntl
import os
import pty
from pathlib import Path
import select
import struct
import subprocess
import sys
import termios
import time


def main():
    root = Path(__file__).resolve().parents[1]
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
    child = subprocess.Popen([sys.executable, "main.py", "--demo"], cwd=root, stdin=slave, stdout=slave,
                             stderr=slave, env={**os.environ, "TERM": "xterm-256color"})
    os.close(slave)
    transcript = bytearray()

    def expect(text, timeout=10):
        deadline = time.monotonic() + timeout
        start = len(transcript)
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    transcript.extend(os.read(master, 65536))
                except OSError:
                    break
            if text.encode() in transcript[start:]:
                return
        raise AssertionError(f"Missing TUI text: {text}\n{transcript[-4000:]!r}")

    try:
        expect("Welcome")
        os.write(master, b"\n")
        expect("Installation configuration")
        # Return to welcome, open network demo, return, exit with arrows/j.
        os.write(master, b"\x1b")
        expect("Welcome")
        os.write(master, b"j\n")
        expect("Network")
        os.write(master, b"\n")
        expect("Welcome")
        os.write(master, b"jjjjj\n")
        child.wait(timeout=10)
        assert child.returncode == 0, f"Exit code: {child.returncode}"
        print("PASS: curses demo welcome, install, network, navigation and clean exit")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)


if __name__ == "__main__":
    main()
