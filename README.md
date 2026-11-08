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

## Controls

| Key    | Action                                                         |
|--------|----------------------------------------------------------------|
| Space  | Start the timer. While running, press again to pause; again to resume. |
| Escape | Reset to `00:00:00`. If the timer was running, it restarts immediately; otherwise it just resets. |

Resize the window any which way and the logo and the readout rescale to
fit, keeping a uniform margin around all edges.

## License

This project is licensed under the [MIT License](LICENSE).
