"""Unit tests for stopwatch's pure logic and image loading.

Standard library only (unittest) — no test runner to install. From the
project root:

    .venv/bin/python -m unittest discover -s tests -v

The SDL dummy video driver is forced before pygame is imported so the suite
runs headless on a build server with no display.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402  (import after the dummy drivers are pinned)

import stopwatch  # noqa: E402


def setUpModule() -> None:
    # load_image() ends in convert_alpha(), which needs the video subsystem.
    pygame.init()
    pygame.display.set_mode((64, 64))


def tearDownModule() -> None:
    pygame.quit()


class FitWithinTest(unittest.TestCase):
    """Geometry of aspect-preserving logo scaling."""

    def test_fit_within_withSquareSourceInWideBox_shouldFillHeightOnly(self):
        # GIVEN a square source and a box far wider than it is tall,
        # THEN the height is the constraint and the shape stays square:
        self.assertEqual(stopwatch.fit_within(400, 400, 600, 238), (238, 238))

    def test_fit_within_withSquareSourceInTallBox_shouldFillWidthOnly(self):
        # GIVEN a square source and a narrow, tall box,
        # THEN the width is the constraint:
        self.assertEqual(stopwatch.fit_within(400, 400, 100, 800), (100, 100))

    def test_fit_within_withWideBannerInSmallBox_shouldPreserveAspectRatio(self):
        # GIVEN a 16:3 banner,
        width, height = stopwatch.fit_within(1600, 300, 450, 238)

        # THEN it fits the box,
        self.assertLessEqual(width, 450)
        self.assertLessEqual(height, 238)

        # AND it is limited by width, not shrunk to something stubby:
        self.assertEqual((width, height), (450, 84))

    def test_fit_within_withTallPortraitSource_shouldPreserveAspectRatio(self):
        # GIVEN a very tall, thin source,
        width, height = stopwatch.fit_within(160, 900, 600, 238)

        # THEN height is the binding constraint and the sliver stays a sliver:
        self.assertEqual((width, height), (42, 237))

    def test_fit_within_withSourceSmallerThanBox_shouldStillGrowToFit(self):
        # GIVEN a logo smaller than the window (upscaling is fine here — the
        # window is what it is),
        width, height = stopwatch.fit_within(24, 18, 600, 238)

        # THEN it is scaled up to fill the box:
        self.assertEqual((width, height), (317, 238))

    def test_fit_within_withDegenerateBox_shouldReturnZeroSize(self):
        # GIVEN boxes with no room at all,
        for max_w, max_h in [(0, 100), (100, 0), (-5, 100), (100, -5)]:
            # THEN the caller is told "no logo fits":
            self.assertEqual(stopwatch.fit_within(400, 400, max_w, max_h), (0, 0),
                             msg=f"box {max_w}x{max_h}")

    def test_fit_within_withEmptySource_shouldReturnZeroSize(self):
        # GIVEN a source with no pixels (defensive: never divide by zero),
        # THEN there is nothing to draw:
        self.assertEqual(stopwatch.fit_within(0, 100, 500, 500), (0, 0))
        self.assertEqual(stopwatch.fit_within(100, 0, 500, 500), (0, 0))

    def test_fit_within_withOddsizes_shouldNeverExceedBoxOrCollapseToZero(self):
        # GIVEN a sweep of awkward source and box dimensions,
        for src in [(1, 1), (3, 7), (999, 1), (1, 999), (640, 480)]:
            for box in [(1, 1), (2, 9), (37, 11), (500, 500), (1024, 768)]:
                width, height = stopwatch.fit_within(*src, *box)

                # THEN nothing ever spills out of the box,
                self.assertLessEqual(width, box[0])
                self.assertLessEqual(height, box[1])

                # AND a box with real room never collapses to invisible,
                if box[0] > 0 and box[1] > 0:
                    self.assertGreaterEqual(width, 1)
                    self.assertGreaterEqual(height, 1)


class FormatTimeTest(unittest.TestCase):
    def test_format_time_withPartialSeconds_shouldTruncateToWholeSeconds(self):
        self.assertEqual(stopwatch.format_time(9.99), "00:00:09")

    def test_format_time_withOneHourOneMinuteOneSecond_shouldRenderPaddedHhMmSs(self):
        self.assertEqual(stopwatch.format_time(3661), "01:01:01")

    def test_format_time_withOverAHundredHours_shouldNotTruncateColumns(self):
        self.assertEqual(stopwatch.format_time(360000), "100:00:00")


class ParseArgsTest(unittest.TestCase):
    def test_parse_args_withNoArguments_shouldLeaveLogoUnset(self):
        # GIVEN a bare command line,
        # THEN the bundled logo is used:
        self.assertIsNone(stopwatch.parse_args([]).logo)

    def test_parse_args_withLogoOption_shouldConvertToPath(self):
        # GIVEN --logo with a string argument,
        args = stopwatch.parse_args(["--logo", "/tmp/some.png"])

        # THEN it arrives as a Path, ready for the filesystem layer:
        self.assertEqual(args.logo, Path("/tmp/some.png"))

    def test_parse_args_withQuotedHomeRelativeLogo_shouldExpandUserDirectory(self):
        # GIVEN a tilde path the shell left alone because it was quoted,
        args = stopwatch.parse_args(["--logo", "~/emblem.png"])

        # THEN it is resolved against the caller's home directory:
        self.assertEqual(args.logo,
                         Path.home() / "emblem.png")

    def test_asImagePath_withRelativePath_shouldStayRelativeToFilesystemLayer(self):
        # GIVEN a plain relative path (no tilde to expand),
        # THEN it is untouched, so it resolves against the current directory:
        self.assertEqual(stopwatch.as_image_path("./emblem.png"),
                         Path("./emblem.png"))

    def test_parse_args_withUnknownOption_shouldExitNonZero(self):
        # THEN argparse refuses the argument before we ever touch pygame,
        with self.assertRaises(SystemExit) as exit_info:
            stopwatch.parse_args(["--no-such-flag"])
        self.assertNotEqual(exit_info.exception.code, 0)


class LoadImageTest(unittest.TestCase):
    """Filesystem boundary of image loading."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)

    def write_png(self, name: str, width: int, height: int) -> Path:
        path = self.tmp_dir / name
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        surface.fill((10, 200, 30, 255))
        pygame.image.save(surface, str(path))
        return path

    def test_loadImage_withPngFile_shouldReturnSurfaceOfSameSize(self):
        # GIVEN a plain PNG,
        path = self.write_png("plain.png", 120, 40)

        # THEN it loads at full size,
        self.assertEqual(stopwatch.load_image(path).get_size(), (120, 40))

    def test_loadImage_withOversizedSource_shouldDownscaleToConfiguredCap(self):
        # GIVEN a source well past the resolution ceiling,
        path = self.write_png("big.png", stopwatch.MAX_LOGO_SOURCE_DIM * 2,
                              stopwatch.MAX_LOGO_SOURCE_DIM)

        surface = stopwatch.load_image(path)

        # THEN the longest edge is capped and the aspect ratio survives,
        self.assertEqual(max(surface.get_size()), stopwatch.MAX_LOGO_SOURCE_DIM)
        self.assertEqual(surface.get_size(),
                         (stopwatch.MAX_LOGO_SOURCE_DIM,
                          stopwatch.MAX_LOGO_SOURCE_DIM // 2))

    def test_loadImage_withMissingFile_shouldRaiseLogoLoadError(self):
        # GIVEN a path that does not exist,
        missing = self.tmp_dir / "nope.png"

        # THEN the caller gets an actionable, typed error rather than a
        # half-initialized window:
        with self.assertRaises(stopwatch.LogoLoadError):
            stopwatch.load_image(missing)

    def test_loadImage_withDirectoryPath_shouldRaiseLogoLoadError(self):
        # GIVEN a directory where a file was expected,
        with self.assertRaises(stopwatch.LogoLoadError):
            stopwatch.load_image(self.tmp_dir)

    def test_loadImage_withNonImageFile_shouldRaiseLogoLoadError(self):
        # GIVEN a text file wearing a .png extension,
        impostor = self.tmp_dir / "impostor.png"
        impostor.write_text("this is not an image")

        # THEN decoding is refused with our own exception,
        with self.assertRaises(stopwatch.LogoLoadError):
            stopwatch.load_image(impostor)


if __name__ == "__main__":
    unittest.main()
