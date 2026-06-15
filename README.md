# snapcraft

**macOS screenshot tool** — global hotkey, region selection, annotation.

Press `Ctrl + Shift + X` to show the floating toolbar, capture fullscreen or a selection, then annotate with rectangles, arrows, text, or freehand.

## Features

- Global hotkey via Core Graphics event tap
- Fullscreen capture
- Region selection with on-screen overlay
- Annotation canvas (rectangles, arrows, text, pencil)
- High-DPI / Retina support
- Dark theme

## Setup

```bash
pip install -r requirements.txt
```

Requires **Accessibility permission** (System Settings → Privacy → Accessibility).

## Usage

```bash
python3 main.py
```

## Requirements

- macOS 12+
- Python 3.9+
- PyQt6 ≥ 6.4.0
- PyObjC (Quartz, ApplicationServices)

## Project status

Early development — contributions welcome.
