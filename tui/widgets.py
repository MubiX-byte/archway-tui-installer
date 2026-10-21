from __future__ import annotations

import curses
import textwrap


class Cancelled(Exception):
    """Return to the previous menu without applying the current form."""


class UI:
    def __init__(self, screen):
        self.screen = screen
        curses.noecho()
        curses.raw()  # Ctrl+C must never interrupt a disk operation behind the UI.
        screen.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for number, color in enumerate((curses.COLOR_CYAN, curses.COLOR_WHITE, curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_GREEN), 1):
                curses.init_pair(number, color, -1)

    def put(self, y, x, text, style=0):
        h, w = self.screen.getmaxyx()
        if 0 <= y < h - 1 and 0 <= x < w - 1:
            clean = "".join(c if c.isprintable() else " " for c in str(text))
            try:
                self.screen.addnstr(y, x, clean, max(0, w - x - 2), style)
            except curses.error:
                pass

    def frame(self, title, subtitle="", footer="Arrows / Tab: move   Enter: select   Esc: back"):
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        self.put(0, 2, " A R C H W A Y  /  ARCH LINUX TUI INSTALLER", curses.color_pair(1) | curses.A_BOLD)
        self.put(1, 2, "─" * (w - 5), curses.color_pair(1))
        self.put(2, 2, title, curses.A_BOLD)
        self.put(3, 2, subtitle, curses.color_pair(3))
        self.put(h - 2, 2, footer, curses.color_pair(1))

    def menu(self, title, options, subtitle="", selected=0, info=()):
        if not options:
            self.view(title, "No entries available")
            raise Cancelled()
        while True:
            h, _ = self.screen.getmaxyx()
            top = 5 + len(info)
            height = max(1, h - top - 3)
            start = max(0, selected - height + 1)
            self.frame(title, subtitle)
            for row, line in enumerate(info, 5):
                self.put(row, 3, line, curses.color_pair(2))
            for row, item in enumerate(options[start:start + height], top):
                index = start + row - top
                active = index == selected
                self.put(row, 3, ("› " if active else "  ") + str(item), curses.A_REVERSE if active else 0)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (curses.KEY_DOWN, 9, ord("j")):
                selected = (selected + 1) % len(options)
            elif key in (curses.KEY_UP, curses.KEY_BTAB, ord("k")):
                selected = (selected - 1) % len(options)
            elif key == curses.KEY_NPAGE:
                selected = min(len(options) - 1, selected + height)
            elif key == curses.KEY_PPAGE:
                selected = max(0, selected - height)
            elif key in (10, 13, curses.KEY_ENTER):
                return selected
            elif key == 27:
                raise Cancelled()

    def view(self, title, content, subtitle=""):
        offset = 0
        while True:
            h, w = self.screen.getmaxyx()
            lines = []
            for line in (content.splitlines() if isinstance(content, str) else content):
                lines.extend(textwrap.wrap(str(line), max(12, w - 6), replace_whitespace=False) or [""])
            height = max(1, h - 8)
            offset = min(offset, max(0, len(lines) - height))
            self.frame(title, subtitle, "Up/Down/PgUp/PgDn: scroll   Enter/Esc: return")
            for row, line in enumerate(lines[offset:offset + height], 5):
                self.put(row, 2, line)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (10, 13, 27):
                return
            if key in (curses.KEY_DOWN, ord("j")):
                offset = min(max(0, len(lines) - height), offset + 1)
            if key in (curses.KEY_UP, ord("k")):
                offset = max(0, offset - 1)
            if key == curses.KEY_NPAGE:
                offset = min(max(0, len(lines) - height), offset + height)
            if key == curses.KEY_PPAGE:
                offset = max(0, offset - height)

    def input(self, title, default="", secret=False, hint=""):
        text = default
        while True:
            h, w = self.screen.getmaxyx()
            self.frame(title, hint, "Type a value   Backspace: delete   Ctrl+U: clear   Enter: save   Esc: cancel")
            visible = "*" * len(text) if secret else text
            self.put(6, 4, "> " + visible[-max(1, w - 12):], curses.A_REVERSE)
            self.screen.refresh()
            try:
                key = self.screen.get_wch()
            except curses.error:
                continue
            if key in ("\n", "\r", curses.KEY_ENTER):
                return text
            if key == "\x1b":
                raise Cancelled()
            if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                text = text[:-1]
            elif key == "\x15":
                text = ""
            elif isinstance(key, str) and key.isprintable():
                text += key

    def confirm(self, title, subtitle=""):
        return self.menu(title, ["No / return", "Yes / continue"], subtitle) == 1

    def checklist(self, title, options, chosen):
        selected = set(chosen)
        index = 0
        while True:
            labels = [("[x] " if option in selected else "[ ] ") + option for option in options] + ["Save selection"]
            index = self.menu(title, labels, "Enter toggles an item; select Save when finished", index)
            if index == len(options):
                return sorted(selected)
            item = options[index]
            if item in selected:
                selected.remove(item)
            else:
                selected.add(item)
