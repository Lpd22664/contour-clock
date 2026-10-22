# Contour Clock

A custom desktop clock for **Noctalia v5 on Linux**. Large rounded time lettering,
a small freestanding date, and a shared wallpaper-aware colour with soft shadows.
The clock stays at the top centre while its colour adapts to your wallpaper.

## Requirements

- Noctalia with support for **plugin API 26** and native Luau desktop widgets.
  If Noctalia marks the plugin incompatible, use a build supporting this API.
  This plugin does not target the older QML plugin system.
- Python 3 and **ImageMagick 7** (`magick` must be on PATH).
- **Adwaita Sans**, including its Medium weight, installed through your distribution
  or the upstream Adwaita fonts project. Fonts are not bundled.

Check ImageMagick can find both font names:

```sh
magick -list font | grep -E 'Font: Adwaita-Sans$|Font: Adwaita-Sans-Medium$'
```

The published renderer resolves the regular font by its ImageMagick name rather
than this laptop's absolute font path. The appearance otherwise follows the
installed clock.

## Install on your other PC

With Noctalia running and the dependencies installed:

```sh
noctalia msg plugins source add contour-clock git https://github.com/Lpd22664/contour-clock
noctalia msg plugins enable acm/contour-clock
```

You can also use **Settings → Plugins → Add source**, add the GitHub URL as a git
source, then enable **Contour Clock**.

1. In **Settings → Plugins**, open Contour Clock's gear and set **Monitor connector**
   to your PC's output name (for example `DP-1` or `HDMI-A-1`). The default `eDP-1`
   is for a laptop and must be changed if your PC has no such output.
   Find connector names using your compositor's monitor listing, such as
   `niri msg outputs` or `hyprctl monitors`.
2. Enable desktop widgets, open **Settings → Desktop → Toggle Editor**, and add
   **Contour Clock** (`acm/contour-clock:clock`) on that same monitor.
3. Turn off the widget background. Set its box to **1100 × 240 logical pixels**
   (use your screen width if it is narrower than 1100). Centre it horizontally,
   with its centre **200 logical pixels from the top**. Leave rotation at zero.

For a 1920 × 1080 logical screen, the centre is `(960, 200)`.
For 2560 × 1440 it is `(1280, 200)`. Use logical resolution after display scaling,
not the physical panel resolution. Rendering uses the selected monitor's scale.

For a declarative layout, merge [examples/desktop-clock.toml](examples/desktop-clock.toml)
into your Noctalia configuration, adjusting connector, screen dimensions and `cx`.
Append `contour-clock` to an existing `widget_order` list so your existing widgets
stay listed. Set the plugin's monitor setting through its gear as above.
The renderer assumes this placement and a **centred crop/fill wallpaper**; moving
or resizing the clock arbitrarily makes wallpaper contrast sampling inaccurate.

### Download instead

Use GitHub's **Code → Download ZIP**, extract it, then copy the inner `contour-clock`
folder into `${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins/` and enable
`acm/contour-clock`. Complete the same monitor and widget setup above.

Alternatively:

```sh
git clone https://github.com/Lpd22664/contour-clock.git
mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins"
cp -r contour-clock/contour-clock "${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins/"
noctalia msg plugins enable acm/contour-clock
```

Choose either the git source or the manual copy to avoid duplicate plugin IDs.

## Updates and troubleshooting

For an installation through the git source:

```sh
noctalia msg plugins update contour-clock
```

If no clock appears, check that the plugin is enabled, a desktop widget instance
has been added, and the plugin and widget both target an existing monitor.
If rendering fails, check `python3`, `magick` and both font names are available
in Noctalia's environment. After fixing dependencies:

```sh
noctalia msg plugin acm/contour-clock:clock all refresh
```

Disable it with `noctalia msg plugins disable acm/contour-clock` and remove its
widget through the editor if you no longer want it.

## Behaviour and limits

The time uses a 24-hour format and follows the machine's local time zone. Date
language follows the Python process locale. No panel or date capsule is drawn.
The widget checks inputs once a second and renders when time, wallpaper, display
geometry or theme changes. Wallpaper analysis and palette extraction are cached;
only six generated clock frames are retained.

Newer Noctalia hosts supply their active palette directly. On older hosts the
helper uses `noctalia theme` for wallpaper-based palettes; custom palette matching
requires the newer colour API. Date and time choose one accent tone together,
keeping the native palette colour whenever it is readable in both regions.
Mixed backgrounds use the best shared tone within the accent family and retain
soft shadows; no glyph borders are drawn. Sampled contrast targets may remain
unmet on mixed scenery. Invalid wallpapers also use one shared, shadowed fill.
All runtime caches stay in Noctalia's plugin data directory.

No wallpapers, private configuration, generated desktop screenshots, or fonts are
included. Wallpaper depth is optional and requires a separately configured depth
plugin; this clock does not install depth models or protect individual glyphs
against foreground masking. One configured monitor is supported per plugin setup.

## Development

Source is in `contour-clock/`. Existing renderer unit tests can be run there with:

```sh
python3 -m unittest -v test_render.py
```

MIT licensed. Noctalia and separately installed fonts retain their own licences.
