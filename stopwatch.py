#!/usr/bin/env python3
"""Stopwatch — a minimalist pygame-ce stopwatch.

Usage:
  stopwatch [--logo IMAGE]

  --logo IMAGE   any readable image file (PNG, JPG, GIF, BMP, WEBP ...).
                 Omit it to fall back to the bundled logo.png. The image's
                 aspect ratio is always preserved.

Keyboard-only controls:
  Space   start the timer; while running, pause; while paused, resume.
  Escape  reset to 00:00:00; if the timer was running, restart immediately.

The window is resizable. On every resize the logo and the HH:MM:SS readout
are rescaled so the display always fits, keeping a uniform margin around
all edges.
"""

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pygame

# ---------------------------------------------------------------- Tunables
LOGO_FILENAME = "logo.png"

# Resolution ceiling for the pristine logo. smoothscale() reads every source
# pixel, and it does so on every single resize event — a 12-megapixel "logo"
# handed to us via --logo would turn window-dragging into a slideshow. 2048px
# is far beyond any size the window will ever ask for.
MAX_LOGO_SOURCE_DIM = 2048

# Share of the usable width the logo is allowed to claim. Without a ceiling, a
# banner-shaped --logo (say 1600x300) would eat almost the whole window and
# leave the readout at its 8px minimum — a very crisp, very useless stopwatch.
# 0.75 is high enough that the bundled square logo is never affected at sane
# window sizes; only extreme proportions get reined in.
LOGO_MAX_WIDTH_FRACTION = 0.75

DEFAULT_WIDTH = 624
DEFAULT_HEIGHT = 262
MARGIN = 12            # uniform margin between content and the window edges
ICON_SIZE = 64         # downsampled size used for the window/taskbar icon
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 1000
FPS = 60

BACKGROUND_COLOR = (0, 0, 0)
TEXT_COLOR = (0, 255, 65)  # terminal green

# The displayed time is always exactly these 8 characters (while hours < 100)
# and a monospace font gives every glyph the same width, so this string
# doubles as the worst-case width. Past 100 hours the string grows to 9
# characters and simply extends a little into the margins before it could
# ever clip at the window edge.
WORST_CASE_TEXT = "00:00:00"

# Monospace families in order of preference. match_font() returns "" when a
# family is absent, so the list degrades gracefully down to pygame's
# (proportional) default font as a last resort.
MONO_FONT_CANDIDATES = (
    "Consolas",
    "Noto Sans Mono",
    "Menlo",
    "Courier New",
    "Ubuntu Mono",
    "Liberation Mono",
    "DejaVu Sans Mono",
)

# Older pygame 2.1.x builds predate these event constants; without them the
# app still works, it just can't clear a stuck "space held" flag after focus
# loss (a very rare edge case).
FOCUS_LOST_EVENT = getattr(pygame, "WINDOWFOCUSLOST", None)

BUNDLED_LOGO_PATH = Path(__file__).resolve().with_name(LOGO_FILENAME)


class LogoLoadError(Exception):
    """The requested logo file could not be found or decoded."""


def fit_within(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Largest aspect-preserving size for a src_w x src_h image in max_w x max_h.

    Returns (0, 0) when the box is degenerate (negative or zero, or an empty
    source), which callers read as "there is no room for the logo".
    """
    if src_w <= 0 or src_h <= 0 or max_w <= 0 or max_h <= 0:
        return (0, 0)
    scale = min(max_w / src_w, max_h / src_h)
    # Floor rather than round: rounding up could push a pixel past the box and
    # eat into the uniform margin.
    width = min(max_w, int(src_w * scale))
    height = min(max_h, int(src_h * scale))
    # A logo one pixel wide is still a logo; nothing here may collapse to zero
    # once the box itself has real size.
    return (max(width, 1), max(height, 1))


def format_time(elapsed_seconds: float) -> str:
    """Format elapsed seconds as zero-padded HH:MM:SS.

    Truncates to whole seconds, the way a physical stopwatch reads.
    """
    total = int(elapsed_seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class Timer:
    """Elapsed-time bookkeeping on a monotonic clock.

    Completed start/pause segments are frozen into _accumulated; the live
    segment is measured against time.monotonic(), which is immune to system
    clock changes, so pauses cost nothing and wall-clock jumps (NTP steps,
    timezone changes) never affect the reading.
    """

    def __init__(self) -> None:
        self._accumulated = 0.0
        self._segment_start: float | None = None
        self.running = False

    @property
    def elapsed(self) -> float:
        total = self._accumulated
        if self.running and self._segment_start is not None:
            total += time.monotonic() - self._segment_start
        return total

    def toggle(self) -> None:
        if self.running:
            self.pause()
        else:
            self.resume()

    def pause(self) -> None:
        if self.running and self._segment_start is not None:
            self._accumulated += time.monotonic() - self._segment_start
            self._segment_start = None
            self.running = False

    def resume(self) -> None:
        if not self.running:
            self._segment_start = time.monotonic()
            self.running = True

    def reset(self) -> None:
        self.pause()
        self._accumulated = 0.0


@dataclass
class _Layout:
    """Everything that depends only on the current window size."""

    logo: pygame.Surface | None
    logo_rect: pygame.Rect | None
    font: pygame.font.Font
    text_area: pygame.Rect


class Stopwatch:
    """The single-window stopwatch application."""

    def __init__(self, logo_path: Path | None = None) -> None:
        """Build the app.

        logo_path names the image to display; None means "use the bundled
        logo.png". An explicitly requested logo that cannot be read is fatal
        (LogoLoadError), because silently showing something else would just
        be confusing. The bundled fallback stays cosmetic: a missing logo has
        never been a reason to deny someone a stopwatch.
        """
        pygame.init()
        pygame.display.set_mode((DEFAULT_WIDTH, DEFAULT_HEIGHT), pygame.RESIZABLE)
        pygame.display.set_caption("Stopwatch")

        self._timer = Timer()
        self._clock = pygame.time.Clock()
        self._running = True
        self._space_down = False
        self._font_name = self._find_monospace_font()
        self._font_cache: dict[int, pygame.font.Font] = {}
        self._logo_source = self._load_logo(logo_path)
        if self._logo_source is not None:
            pygame.display.set_icon(self._window_icon())
        self._text_cache: tuple[str, pygame.Surface] | None = None
        self._window_size = pygame.display.get_window_size()
        self._layout: _Layout | None = self._build_layout(self._window_size)

    # -------------------------------------------------------------- Main loop
    def run(self) -> None:
        while self._running:
            self._handle_events()
            self._sync_window_size()
            self._draw()
            pygame.display.flip()
            self._clock.tick(FPS)
        pygame.quit()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
            elif event.type == pygame.KEYDOWN:
                self._on_key_down(event)
            elif event.type == pygame.KEYUP:
                self._on_key_up(event)
            elif FOCUS_LOST_EVENT is not None and event.type == FOCUS_LOST_EVENT:
                # Losing focus can swallow the KEYUP, which would leave the
                # "space is held" flag stuck and eat the next press.
                self._space_down = False

    # ------------------------------------------------------------------ Input
    def _on_key_down(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_SPACE:
            # pygame exposes no autorepeat flag on KEYDOWN, so "held" is
            # tracked manually: only the first KEYDOWN of a press toggles.
            if self._space_down:
                return
            self._space_down = True
            self._timer.toggle()
        elif event.key == pygame.K_ESCAPE:
            was_running = self._timer.running
            self._timer.reset()
            if was_running:
                self._timer.resume()

    def _on_key_up(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_SPACE:
            self._space_down = False

    # ----------------------------------------------------------------- Layout
    def _sync_window_size(self) -> None:
        # Polling instead of relying on VIDEORESIZE events keeps resize
        # handling identical across X11, Windows and macOS.
        size = pygame.display.get_window_size()
        if size != self._window_size:
            self._window_size = size
            self._layout = self._build_layout(size)
            self._text_cache = None

    def _build_layout(self, size: tuple[int, int]) -> _Layout | None:
        usable_w = size[0] - 2 * MARGIN
        usable_h = size[1] - 2 * MARGIN
        # Absurdly small window: nothing meaningful fits, so draw a plain
        # black screen and let the next resize sort it out.
        if usable_w < MIN_FONT_SIZE or usable_h < MIN_FONT_SIZE:
            return None

        # The logo may claim up to LOGO_MAX_WIDTH_FRACTION of the usable width,
        # never so much that the readout can no longer render at MIN_FONT_SIZE,
        # and it shrinks into that box without distorting its aspect ratio. At
        # ordinary window sizes the bundled square logo is unconstrained by both
        # caps, so it simply fills the usable height as it always has.
        min_text_width = self._get_font(MIN_FONT_SIZE).size(WORST_CASE_TEXT)[0]
        logo_budget = min(usable_w - min_text_width,
                          int(usable_w * LOGO_MAX_WIDTH_FRACTION))
        logo_rect = self._logo_box(logo_budget, usable_h)
        logo_w = logo_rect.w if logo_rect is not None else 0

        text_area = pygame.Rect(MARGIN + logo_w, MARGIN, usable_w - logo_w, usable_h)

        return _Layout(
            logo=self._scaled_logo(logo_rect),
            logo_rect=logo_rect,
            font=self._get_font(self._fit_font_size(text_area.w, usable_h)),
            text_area=text_area,
        )

    def _logo_box(self, max_width: int, max_height: int) -> pygame.Rect | None:
        """Where the logo goes: left-aligned, vertically centred, undistorted."""
        if self._logo_source is None:
            return None
        width, height = fit_within(
            *self._logo_source.get_size(), max_width, max_height
        )
        if width == 0 or height == 0:
            return None
        return pygame.Rect(
            MARGIN,
            MARGIN + (max_height - height) // 2,
            width,
            height,
        )

    def _fit_font_size(self, max_width: int, max_height: int) -> int:
        """Largest font size whose worst-case text fits the given box."""

        def fits(font_size: int) -> bool:
            width, height = self._get_font(font_size).size(WORST_CASE_TEXT)
            return width <= max_width and height <= max_height

        # Exponential search for an upper bound, then bisection down to the
        # largest size that still fits. Only a handful of font.size() calls
        # per resize, so dragging the window edge feels instant.
        if not fits(MIN_FONT_SIZE):
            return MIN_FONT_SIZE
        lo = hi = MIN_FONT_SIZE
        while hi < MAX_FONT_SIZE and fits(hi):
            lo = hi
            hi = min(hi * 2, MAX_FONT_SIZE)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fits(mid):
                lo = mid
            else:
                hi = mid - 1
        return lo

    # ------------------------------------------------------------- Rendering
    def _draw(self) -> None:
        screen = pygame.display.get_surface()
        screen.fill(BACKGROUND_COLOR)
        layout = self._layout
        if layout is None:
            return
        if layout.logo is not None and layout.logo_rect is not None:
            screen.blit(layout.logo, layout.logo_rect)
        text_surface = self._rendered_text(layout.font)
        center_x, center_y = layout.text_area.center
        screen.blit(
            text_surface,
            (center_x - text_surface.get_width() // 2,
             center_y - text_surface.get_height() // 2),
        )

    def _rendered_text(self, font: pygame.font.Font) -> pygame.Surface:
        # The displayed string only changes when the whole second changes,
        # so rendering it 60 times a second would be pure waste.
        text = format_time(self._timer.elapsed)
        if self._text_cache is None or self._text_cache[0] != text:
            self._text_cache = (text, font.render(text, True, TEXT_COLOR))
        return self._text_cache[1]

    # ---------------------------------------------------------------- Assets
    def _get_font(self, font_size: int) -> pygame.font.Font:
        font = self._font_cache.get(font_size)
        if font is None:
            # SysFont(None, ...) selects pygame's default font when no
            # monospace family was found on this system.
            font = pygame.font.SysFont(self._font_name, font_size)
            self._font_cache[font_size] = font
        return font

    @staticmethod
    def _find_monospace_font() -> str | None:
        for name in MONO_FONT_CANDIDATES:
            if pygame.font.match_font(name):
                return name
        print("Stopwatch: no monospace font found; using pygame's default font.",
              file=sys.stderr)
        return None

    @staticmethod
    def _load_logo(logo_path: Path | None) -> pygame.Surface | None:
        path = logo_path or BUNDLED_LOGO_PATH
        try:
            return load_image(path)
        except LogoLoadError as exc:
            if logo_path is not None:
                raise
            # A missing bundled logo is cosmetic; the timer is the whole point.
            # stderr, because stdout is block-buffered when redirected and a
            # killed process would otherwise take this warning down with it.
            print(f"Stopwatch: {exc}; continuing without a logo.",
                  file=sys.stderr)
            return None

    def _scaled_logo(self, logo_rect: pygame.Rect | None) -> pygame.Surface | None:
        if self._logo_source is None or logo_rect is None:
            return None
        # Always rescale from the pristine source: scaling an already-scaled
        # surface compounds resampling loss on every resize.
        return pygame.transform.smoothscale(self._logo_source, logo_rect.size)

    def _window_icon(self) -> pygame.Surface:
        # Window managers rescale the icon to 16px themselves, and from a
        # 400px+ source that leaves a rough nearest-neighbour mess; 64px
        # downsamples cleanly at every size they might ask for. Taskbar icons
        # are square, so an off-square logo is centred on a transparent
        # square canvas rather than stretched into a funhouse mirror.
        icon = pygame.Surface((ICON_SIZE, ICON_SIZE), pygame.SRCALPHA)
        width, height = fit_within(
            *self._logo_source.get_size(), ICON_SIZE, ICON_SIZE
        )
        icon.blit(
            pygame.transform.smoothscale(self._logo_source, (width, height)),
            ((ICON_SIZE - width) // 2, (ICON_SIZE - height) // 2),
        )
        return icon


def load_image(path: Path) -> pygame.Surface:
    """Read an image file into a blit-ready surface, capped for resize speed.

    Requires pygame.init() to have run, hence the module-level function
    rather than anything importable before display initialisation.
    """
    if not path.exists():
        raise LogoLoadError(f"could not load logo: no such file '{path}'")
    if not path.is_file():
        raise LogoLoadError(f"could not load logo: '{path}' is not a file")
    try:
        # convert_alpha() bakes in per-pixel alpha for cheap blits, and also
        # promotes palette/8-bit files to a format smoothscale() will accept.
        source = pygame.image.load(str(path)).convert_alpha()
    except (pygame.error, OSError) as exc:
        raise LogoLoadError(
            f"could not load logo '{path}': {exc}. Supported formats include "
            "PNG, JPG, GIF, BMP, WEBP and TIF."
        ) from exc

    width, height = source.get_size()
    if max(width, height) > MAX_LOGO_SOURCE_DIM:
        source = pygame.transform.smoothscale(
            source,
            fit_within(width, height, MAX_LOGO_SOURCE_DIM, MAX_LOGO_SOURCE_DIM),
        )
    return source


def as_image_path(raw: str) -> Path:
    """Turn a command line argument into a usable path.

    expanduser() covers the quoted-tilde case ('--logo "~/emblem.png"'),
    which the shell politely refuses to expand on our behalf.
    """
    return Path(raw).expanduser()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="stopwatch",
        description="A minimalist keyboard-only stopwatch.",
    )
    parser.add_argument(
        "--logo",
        metavar="IMAGE",
        type=as_image_path,
        help=f"image file to display beside the readout, aspect ratio "
             f"preserved (PNG, JPG, GIF, BMP, WEBP). Default: "
             f"{LOGO_FILENAME} next to stopwatch.py",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        Stopwatch(logo_path=args.logo).run()
    except LogoLoadError as exc:
        print(f"Stopwatch: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
