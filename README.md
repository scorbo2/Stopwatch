# Stopwatch

The official noplacelikelocalhost Stopwatch, as seen on YouTube!

A simple pygame-ce stopwatch: one resizable window, a stopwatch logo, and a
big green `HH:MM:SS` readout. No buttons, no mouse — keyboard only.

## How to run

```
# Set up a venv:
python3 -m venv .venv
source .venv/bin/activate

# Install requirements into this venv:
pip install -r requirements.txt

# Now run it:
python stopwatch.py

# Deactivate the venv when finished:
deactivate
```

Once the venv is set up, the `stopwatch` wrapper in this directory does the
activate/run/deactivate dance for you, and forwards every argument you give
it straight to `stopwatch.py`:

```bash
# Use the official No Place Like Localhost logo:
./stopwatch

# Or use a sponsor's logo:
./stopwatch --logo ~/pictures/sponsor.png
```

## Choosing your own logo

Point `--logo` at any image file and it replaces the bundled logo, at any
size and any proportion. Square works best. The image will be scaled (not stretched)
to fit beside the time readout.

What the app does with your image:

- **Proportions are always preserved.** A 1600x300 banner stays a banner and
  a 200x800 portrait stays a portrait; nothing is ever stretched into a
  funhouse mirror.
- **It is never cropped.** The logo is scaled to fit the space left for it on
  the left of the readout, and is vertically centred in the window when it
  doesn't fill the height.
- **Space is shared.** The logo may claim up to 75% of the window width
  (`LOGO_MAX_WIDTH_FRACTION` in `stopwatch.py`), and the `HH:MM:SS` readout
  always keeps the rest, so a wide banner shrinks itself rather than reducing
  the timer to eight unreadable pixels.
- **Huge images are capped.** Anything larger than 2048px on its longest edge
  is downsampled once at load time (`MAX_LOGO_SOURCE_DIM`), because the logo
  is re-rescaled on every single resize event and a 12-megapixel "logo" makes
  window-dragging stutter.

Gotchas worth knowing about:

- **A bad `--logo` is fatal, on purpose.** A missing file, a directory, or a
  text file wearing a `.png` extension exits with a message and status `1`
  rather than quietly showing something else:

  ```
  $ ./stopwatch --logo nope.png
  Stopwatch: could not load logo: no such file 'nope.png'
  $
  ```

  By contrast, if the *bundled* `logo.png` is missing the app just warns on
  stderr and shows the timer on its own.
- **Animated GIFs show their first frame only.** `pygame.image.load()` hands
  back a single frame; multi-frame GIF playback would need `load_gif()` and
  an animation clock.
- **Relative paths are resolved against your current directory**, not the
  project directory. `./stopwatch --logo ./emblem.png` works from anywhere —
  the wrapper deliberately does not `cd` out from under you.

## Controls

| Key    | Action                                                         |
|--------|----------------------------------------------------------------|
| Space  | Start the timer. While running, press again to pause; again to resume. |
| Escape | Reset to `00:00:00`. If the timer was running, it restarts immediately; otherwise it just resets. |

Resize the window any which way and the logo and the readout rescale to
fit, keeping a uniform margin around all edges.

## Tests

Standard library only, so there is nothing extra to install:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## License

This project is licensed under the [MIT License](LICENSE).
