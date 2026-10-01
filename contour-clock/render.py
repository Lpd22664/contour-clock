#!/usr/bin/env python3
"""Contour's on-demand text renderer. Standard library + existing ImageMagick.

Reads wallpapers without changing them. Writes only plugin-owned cache/output.
No network, shell interpolation, continuous process, or generated mockup assets.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
from datetime import datetime

VERSION = 3
FONT = "Adwaita-Sans"
SAMPLE_W = 480


def magick(args, data=None):
    env = dict(os.environ, MAGICK_THREAD_LIMIT="1")
    return subprocess.run(["magick", "-limit", "memory", "128MiB", "-limit", "map", "256MiB", *args],
                          input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True, timeout=30, env=env).stdout


def luminance(rgb):
    def linear(v):
        v /= 255
        return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
    r, g, b = map(linear, rgb)
    return .2126 * r + .7152 * g + .0722 * b


def contrast(a, b):
    return (max(a, b) + .05) / (min(a, b) + .05)


def region(pixels, sw, sh, width, height, bounds):
    x0, y0, x1, y1 = bounds
    values = []
    for y in range(max(0, int(y0 / height * sh)), min(sh, math.ceil(y1 / height * sh))):
        for x in range(max(0, int(x0 / width * sw)), min(sw, math.ceil(x1 / width * sw))):
            i = (y * sw + x) * 3
            values.append(luminance(pixels[i:i + 3]))
    return values or [.5]


def rgb(hex_color):
    if not isinstance(hex_color, str) or len(hex_color) != 7 or hex_color[0] != "#":
        raise ValueError("Expected #RRGGBB palette colour")
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def hex_rgb(color):
    return "#%02x%02x%02x" % tuple(color)


def mix(color, neutral, amount):
    # A neutral tint/shade retains the accent's RGB hue without a second extractor.
    return tuple(round(c * (1 - amount) + neutral * amount) for c in color)


def treatment(values, palette=None, target=4.5):
    values = sorted(values)
    palette = palette or {}
    try:
        accent = rgb(palette.get("primary"))
        source = "noctalia.primary"
    except (ValueError, TypeError):
        accent = (128, 128, 128)
        source = "neutral-fallback"
    def quality(rgb):
        ratios = sorted(contrast(luminance(rgb), value) for value in values)
        return ratios[len(ratios) // 10], ratios[len(ratios) // 5]
    candidates = []
    for step in range(39):
        amount = step / 40
        for neutral in (0, 255):
            color = mix(accent, neutral, amount)
            p10, p20 = quality(color)
            candidates.append((amount, color, p10, p20))
    passing = [c for c in candidates if c[2] >= target]
    outlined = not passing or values[len(values) * 9 // 10] - values[len(values) // 10] > .55
    if passing:
        # Keep the native accent unchanged whenever it already reads clearly.
        amount, color, p10, p20 = min(passing, key=lambda c: (c[0], -c[2]))
    else:
        # Split light/dark scenery needs two-tone glyphs. Preserve some accent
        # chroma in the fill; an opposing tinted edge protects the other areas.
        strong = [c for c in candidates if c[0] <= .8]
        amount, color, p10, p20 = max(strong, key=lambda c: (c[2], -c[0]))
    bright = luminance(color) > .179
    edge = mix(accent, 0 if bright else 255, .85)
    return {"color": hex_rgb(color), "light": bright, "source": source,
            "tone_adjustment": amount, "contrast_target": target,
            "contrast_p10": round(p10, 3), "contrast_p20": round(p20, 3),
            "outline": outlined, "outline_color": hex_rgb(edge),
            "shadow_color": hex_rgb(mix(accent, 0, .8)),
            "variation": statistics.pstdev(values)}


def sample_wallpaper(wallpaper, width, height, cache, pinned=False):
    path = Path(wallpaper)
    stat = path.stat()
    signature = f"{VERSION}|{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{width}|{height}|{pinned}"
    key = hashlib.sha256(signature.encode()).hexdigest()
    cached = cache / ("analysis-" + key + ".json")
    if cached.exists():
        try:
            return json.loads(cached.read_text())
        except (ValueError, OSError):
            pass
    sh = round(SAMPLE_W * height / width)
    raw = magick([str(path.resolve()) + "[0]", "-auto-orient", "-resize", f"{SAMPLE_W}x{sh}^",
                  "-gravity", "center", "-extent", f"{SAMPLE_W}x{sh}", "-alpha", "off",
                  "-colorspace", "sRGB", "-depth", "8", "rgb:-"])
    if len(raw) != SAMPLE_W * sh * 3:
        raise ValueError("Unexpected wallpaper sample size")
    candidates = []
    # Stable, bounded positions inside the upper desktop; centre wins near ties.
    for offset in ([0] if pinned else [0, -.125, .125]):
        cx = width * (.5 + offset)
        time = region(raw, SAMPLE_W, sh, width, height, (cx - 185, 162, cx + 185, 267))
        date = region(raw, SAMPLE_W, sh, width, height, (cx - 135, 105, cx + 135, 132))
        candidates.append({"center_x": cx, "offset": offset, "time": time, "date": date})
    result = {"wallpaper": str(path), "analysis_key": key, "samples": candidates}
    atomic_json(cached, result)
    return result


def analyse(wallpaper, width, height, cache, pinned=False, palette=None):
    sampled = sample_wallpaper(wallpaper, width, height, cache, pinned)
    candidates = []
    for sample in sampled["samples"]:
        time = treatment(sample["time"], palette, target=3)
        date = treatment(sample["date"], palette, target=4.5)
        score = min(time["contrast_p20"] / 3, date["contrast_p20"] / 4.5)
        score -= (time["variation"] + date["variation"]) * .4
        score -= abs(sample["offset"]) * 3
        candidates.append((score, {"center_x": sample["center_x"], "time": time, "date": date}))
    result = max(candidates, key=lambda pair: pair[0])[1]
    result.update(wallpaper=sampled["wallpaper"], analysis_key=sampled["analysis_key"],
                  palette=palette or {})
    return result


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def wallpaper_palette(wallpaper, cache, scheme, mode):
    """Older running hosts lack getColor; use Noctalia's own offline generator.

    This does not change the shell theme or run template hooks. Cache its output
    independently of the clock minute, with file identity and theme inputs.
    """
    path = Path(wallpaper).resolve()
    stat = path.stat()
    signature = f"{path}|{stat.st_mtime_ns}|{stat.st_size}|{scheme}|{mode}"
    key = hashlib.sha256(signature.encode()).hexdigest()
    cached = cache / ("palette-" + key + ".json")
    if cached.exists():
        try:
            return json.loads(cached.read_text())
        except (OSError, ValueError):
            pass
    def generate(image):
        return subprocess.run(["noctalia", "theme", str(image), "--scheme", scheme, "--" + mode],
                              capture_output=True, text=True, check=True, timeout=30)
    try:
        result = generate(path)
    except subprocess.CalledProcessError:
        # Native decoder rejects some otherwise readable JPEGs in this collection.
        # A lossless thumbnail bridges decoders; the user's original stays intact.
        with tempfile.TemporaryDirectory(prefix="palette-", dir=cache) as temporary:
            normalized = Path(temporary) / "sample.png"
            magick([str(path) + "[0]", "-auto-orient", "-resize", "512x512>",
                    "-colorspace", "sRGB", "-alpha", "off", "-strip", str(normalized)])
            result = generate(normalized)
    palette = json.loads(result.stdout)
    rgb(palette.get("primary"))
    atomic_json(cached, palette)
    return palette


def text_image(text, size, style, destination, scale, is_time=False):
    stroke = style.get("outline_color", "#101a20" if style["light"] else "#f8fbfd")
    use_morph_outline = style["outline"]
    outline_radius = max(1, round(.85 * scale))
    padding = outline_radius + 2
    args = ["-background", "none", "-font", "Adwaita-Sans-Medium" if is_time or style["outline"] else FONT, "-pointsize", str(size * scale),
            "-kerning", str(1.5 * scale if is_time else 0),
            "-fill", style["color"], "-stroke", "none", "-strokewidth", "0", "label:" + text,
            "-trim", "+repage"]
    if use_morph_outline:
        # Build the border from a dilated copy of the glyph alpha. This follows
        # every contour evenly, including the large numerals, and cannot be
        # clipped by ImageMagick's label box.
        args += ["-bordercolor", "none", "-border", f"{padding}x{padding}"]
        args += ["(", "+clone", "-channel", "A", "-morphology", "Dilate",
                 f"Disk:{outline_radius}", "+channel", "-fill", stroke,
                 "-colorize", "100", ")", "+swap", "-composite"]
    if not use_morph_outline:
        # Font-shaped shadow creates restrained depth, not a translucent background.
        shadow = f"{38 if is_time else 28}x{4.5 * scale if is_time else .7 * scale}+0+{round(3 * scale) if is_time else round(scale)}"
        args += ["(", "+clone", "-background", style.get("shadow_color", "#171717"), "-shadow", shadow, ")",
                 "+swap", "-background", "none", "-layers", "merge", "+repage"]
    args.append(str(destination))
    magick(args)


def render(args):
    args.cache.mkdir(parents=True, exist_ok=True)
    when = datetime.fromisoformat(args.time) if args.time else datetime.now()
    # Noctalia outputs() reports logical dimensions (verified at runtime).
    width, height = args.width, args.height
    scale = min(3., max(1., args.scale))
    canvas_w, canvas_h = min(1100., width), 240
    palette = args.palette
    palette_source = "runtime-api"
    palette_warning = None
    if not palette:
        try:
            palette = wallpaper_palette(args.wallpaper, args.cache, args.scheme, args.theme_mode)
            palette_source = "noctalia-theme-cli"
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            palette_source = "neutral-fallback"
            palette_warning = str(error)
    try:
        analysis = analyse(args.wallpaper, width, height, args.cache, args.pinned, palette)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        analysis = {"center_x": width / 2, "wallpaper": args.wallpaper,
                    "warning": str(error), "time": treatment([.01, .9], palette),
                    "date": treatment([.01, .9], palette)}
    analysis["palette_source"] = palette_source
    analysis["palette_scheme"] = args.scheme
    analysis["palette_mode"] = args.theme_mode
    if palette_warning:
        analysis["palette_warning"] = palette_warning
    local_cx = analysis["center_x"] - (width - canvas_w) / 2
    with tempfile.TemporaryDirectory(prefix="contour-", dir=args.cache) as temporary:
        temp = Path(temporary)
        date_text = when.strftime("%A, ") + str(when.day) + when.strftime(" %B")
        text_image(when.strftime("%H:%M"), 135, analysis["time"], temp / "time.png", scale, True)
        text_image(date_text, 22, analysis["date"], temp / "date.png", scale)
        command = ["-size", f"{round(canvas_w * scale)}x{round(canvas_h * scale)}", "canvas:none"]
        for name, top in [("date", 26), ("time", 79)]:
            shape = subprocess.check_output(["magick", "identify", "-format", "%w %h", str(temp / (name + ".png"))], text=True)
            text_w, _ = map(int, shape.split())
            left = round(local_cx * scale - text_w / 2)
            command += [str(temp / (name + ".png")), "-geometry", f"{left:+d}+{round(top * scale)}", "-composite"]
        pending = temp / "face.png"
        magick([*command, str(pending)])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        pending.replace(args.output)
    analysis.update(canvas_width=canvas_w, canvas_height=canvas_h, pinned=args.pinned, time=analysis["time"],
                    display_time=when.strftime("%H:%M"), display_date=date_text, output=str(args.output))
    # Bound disk use while giving each frame a fresh native image-cache key.
    frames = sorted(args.cache.glob("face-*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in frames[6:]:
        if old != args.output:
            old.unlink(missing_ok=True)
    return analysis


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--wallpaper", required=True)
    p.add_argument("--width", type=float, default=1920)
    p.add_argument("--height", type=float, default=1080)
    p.add_argument("--scale", type=float, default=2)
    p.add_argument("--time")
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--pinned", action="store_true")
    p.add_argument("--palette", type=json.loads, default={})
    p.add_argument("--scheme", default="m3-tonal-spot")
    p.add_argument("--theme-mode", choices=("light", "dark"), default="dark")
    return p


if __name__ == "__main__":
    print(json.dumps(render(parser().parse_args())))
