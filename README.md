# snapcraft

**macOS screenshot tool** — global hotkey, region selection, annotation editor.

Press `Ctrl + Shift + X` to summon the floating toolbar, capture the full screen or a custom region, then annotate with rectangles, arrows, text, or freehand drawing. Dark theme, Retina-ready.

> ⚠️ **Early development** — this project is a work in progress. APIs and behavior may change.

---

## Features

- Global hotkey via Core Graphics event tap (`Ctrl + Shift + X`)
- Full-screen capture
- Interactive region selection with on-screen overlay
- Annotation canvas (rectangles, arrows, text, pencil)
- High-DPI / Retina support
- Dark-themed flat UI
- Clipboard copy and/or save to Desktop

## Requirements

| Dependency | Version |
|---|---|
| macOS | 12+ |
| Python | 3.9+ |
| PyQt6 | ≥ 6.4.0 |
| PyObjC (Quartz, ApplicationServices) | — |

## Setup

```bash
pip install -r requirements.txt
```

### Accessibility permission

The global hotkey requires Accessibility access:

1. Open **System Settings → Privacy & Security → Accessibility**
2. Add the Python interpreter that runs the script (`/usr/bin/python3` or your virtualenv's python)
3. Restart the app

## Usage

```bash
python3 main.py
```

A log file is written to `/tmp/screenshot_tool.log`.

### Controls

| Action | Input |
|---|---|
| Show / hide toolbar | `Ctrl + Shift + X` |
| Full-screen capture | Click **Plein écran** |
| Region capture | Click **Sélection**, then drag on screen |
| Cancel region selection | `Escape` |

### Annotation tools

| Tool | Shortcut |
|---|---|
| Rectangle | `R` |
| Arrow | `A` |
| Text | `T` |
| Pencil | `P` |
| Undo | `Cmd + Z` |

### Export

| Button | Action |
|---|---|
| Copier & Fermer | Copy annotated image to clipboard, close editor |
| Copier & Enregistrer | Copy to clipboard + save PNG to Desktop |
| Enregistrer | Save PNG to Desktop |

## Troubleshooting

- **Hotkey doesn't work** → check Accessibility permission and `/tmp/screenshot_tool.log`
- **"CGEventTapCreate → None"** → the process doesn't have Accessibility permission
- **Annotations look wrong on Retina** → ensure `PyQt6 ≥ 6.4.0`

## Project structure

```
snapcraft/
├── main.py          # App entry point, event tap, Qt loop
├── capture.py       # Full-screen & region capture
├── editor.py        # Annotation canvas & editor window
├── toolbar.py       # Floating toolbar widget
└── test_hotkey.py   # Standalone key event logger (debugging)
```

## License

MIT
