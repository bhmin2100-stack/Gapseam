from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple, Optional

from PIL import Image, ImageChops, ImageDraw

Point = Tuple[float, float]  # (x, y_user), y_user is negative for depth


def _nice_step(raw: float) -> float:
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    base = raw / (10 ** exp)
    if base <= 1:
        nice = 1
    elif base <= 2:
        nice = 2
    elif base <= 5:
        nice = 5
    else:
        nice = 10
    return nice * (10 ** exp)


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _film_color(idx: int, total: int) -> Tuple[int, int, int]:
    if total <= 1:
        t = 1.0
    else:
        t = idx / float(total - 1)
    t = max(0.0, min(1.0, float(t)))
    # light sky-blue -> deeper blue
    c0 = (205, 236, 255)
    c1 = (42, 117, 196)
    return (_lerp(c0[0], c1[0], t), _lerp(c0[1], c1[1], t), _lerp(c0[2], c1[2], t))


def _fmt_tick(v: float, step: float) -> str:
    s = abs(step)
    if s >= 100:
        return f"{v:.0f}"
    if s >= 1:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _fill_below_profile(
    draw: ImageDraw.ImageDraw,
    profile: List[Point],
    floor_y: float,
    color: Tuple[int, int, int],
    to_px,
) -> None:
    if len(profile) < 2:
        return
    poly_pts = profile + [(profile[-1][0], floor_y), (profile[0][0], floor_y)]
    draw.polygon([to_px(p) for p in poly_pts], fill=color)


def _fill_polygon_hatched(
    img: Image.Image,
    px_poly: List[Tuple[int, int]],
    *,
    fill_color: Tuple[int, int, int] = (255, 255, 255),
    hatch_color: Tuple[int, int, int] = (228, 228, 228),
    spacing_px: int = 8,
) -> None:
    if len(px_poly) < 3:
        return

    draw = ImageDraw.Draw(img)
    draw.polygon(px_poly, fill=fill_color)

    mask = Image.new("L", img.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.polygon(px_poly, fill=255)

    hatch = Image.new("RGB", img.size, fill_color)
    hatch_draw = ImageDraw.Draw(hatch)
    w, h = img.size
    step = max(4, int(spacing_px))
    for x in range(-h, w + h, step):
        hatch_draw.line([(x, 0), (x + h, h)], fill=hatch_color, width=1)

    img.paste(hatch, (0, 0), mask)


def render_snapshot(
    pts: List[Point],
    out_png: Path,
    *,
    show_si_fill: bool = True,
    title: str = "",
    width: int = 1200,
    height: int = 800,
    margin: int = 60,
    draw_points: bool = False,
    base_profile: Optional[List[Point]] = None,
    layer_profiles: Optional[List[List[Point]]] = None,
    layer_color_total: Optional[int] = None,
    bounds_profiles: Optional[List[List[Point]]] = None,
    void_polygons: Optional[List[List[Point]]] = None,
    x_window: Optional[Tuple[float, float]] = None,
    draw_walls: bool = False,
    show_axes: bool = True,
    crop_to_content: bool = False,
    crop_padding: int = 20,
    tight_bounds: bool = False,
    info_text: str = "",
) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    if len(pts) < 2:
        draw.text((margin, margin), "No geometry", fill=(0, 0, 0))
        img.save(out_png)
        return

    base = list(base_profile) if base_profile else list(pts)
    layers = list(layer_profiles) if layer_profiles else []

    profiles_for_bounds: List[List[Point]] = [base, pts] + layers
    if bounds_profiles:
        profiles_for_bounds = [list(prof) for prof in bounds_profiles if len(prof) >= 1]
        if not profiles_for_bounds:
            profiles_for_bounds = [base, pts] + layers
    xs: List[float] = []
    ys: List[float] = []
    for prof in profiles_for_bounds:
        for x, y in prof:
            xs.append(x)
            ys.append(y)
    if not xs:
        xs = [0.0]
    if not ys:
        ys = [0.0]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    x_span = max(x_max - x_min, 1e-9)
    y_span = max(y_max - y_min, 1e-9)
    if tight_bounds:
        x_pad = max(x_span * 0.06, 10.0)
        y_pad = max(y_span * 0.06, 10.0)
    else:
        x_pad = max(x_span * 0.15, 50.0)
        y_pad = max(y_span * 0.15, 50.0)

    if x_window is not None:
        x0, x1 = sorted((float(x_window[0]), float(x_window[1])))
        if abs(x1 - x0) < 1e-9:
            x0 -= 1.0
            x1 += 1.0
    else:
        x0 = x_min - x_pad
        x1 = x_max + x_pad
    y0 = y_min - y_pad
    y1 = y_max + y_pad

    avail_w = max(width - 2 * margin, 10)
    avail_h = max(height - 2 * margin, 10)
    sx = avail_w / max(x1 - x0, 1e-9)
    sy = avail_h / max(y1 - y0, 1e-9)
    s = min(sx, sy)

    def to_px(p: Point) -> Tuple[int, int]:
        x, y = p
        u = margin + int(round((x - x0) * s))
        v = margin + int(round((y1 - y) * s))  # image y down
        return u, v

    if show_axes:
        # background grid + axes
        major = _nice_step((x1 - x0) / 10.0)
        minor = max(major / 2.0, 1e-9)

        gx = math.floor(x0 / minor) * minor
        for _ in range(2000):
            if gx > x1 + minor:
                break
            u, _ = to_px((gx, y0))
            color = (220, 220, 220) if abs((gx / major) - round(gx / major)) < 1e-6 else (238, 238, 238)
            draw.line([(u, margin), (u, height - margin)], fill=color, width=1)
            gx += minor

        gy = math.floor(y0 / minor) * minor
        for _ in range(2000):
            if gy > y1 + minor:
                break
            _, v = to_px((x0, gy))
            color = (220, 220, 220) if abs((gy / major) - round(gy / major)) < 1e-6 else (238, 238, 238)
            draw.line([(margin, v), (width - margin, v)], fill=color, width=1)
            gy += minor

        if x0 <= 0.0 <= x1:
            u0, _ = to_px((0.0, y0))
            draw.line([(u0, margin), (u0, height - margin)], fill=(130, 130, 130), width=2)
        if y0 <= 0.0 <= y1:
            _, v0 = to_px((x0, 0.0))
            draw.line([(margin, v0), (width - margin, v0)], fill=(130, 130, 130), width=2)

        # axis labels
        tx = math.floor(x0 / major) * major
        for _ in range(1000):
            if tx > x1 + major:
                break
            u, _ = to_px((tx, y0))
            draw.text((u + 2, height - margin + 4), _fmt_tick(tx, major), fill=(70, 70, 70))
            tx += major

        ty = math.floor(y0 / major) * major
        for _ in range(1000):
            if ty > y1 + major:
                break
            _, v = to_px((x0, ty))
            draw.text((4, v - 8), _fmt_tick(ty, major), fill=(70, 70, 70))
            ty += major

    floor_y = y0 - (y_pad * 2.0)

    # Si substrate fill
    if show_si_fill:
        _fill_below_profile(draw, base, floor_y, (220, 220, 220), to_px)

    # deposited film layers (ring-like accumulation)
    prev = list(base)
    total_layers = max(1, int(layer_color_total) if layer_color_total is not None else len(layers))
    for idx, cur in enumerate(layers):
        if len(prev) < 2 or len(cur) < 2:
            prev = list(cur)
            continue
        poly = prev + list(reversed(cur))
        draw.polygon([to_px(p) for p in poly], fill=_film_color(idx, total_layers))
        prev = list(cur)

    # trapped voids should remain air (white) after pinch-off
    if void_polygons:
        for poly in void_polygons:
            if len(poly) < 3:
                continue
            px_poly = [to_px(p) for p in poly]
            draw.polygon(px_poly, fill=(255, 255, 255))
            draw.line(px_poly + [px_poly[0]], fill=(190, 190, 190), width=1)

    # current boundary line
    line_px = [to_px(p) for p in pts]
    draw.line(line_px, fill=(0, 0, 0), width=2)

    if draw_points:
        for u, v in line_px:
            r = 2
            draw.ellipse((u - r, v - r, u + r, v + r), fill=(0, 0, 255))

    if draw_walls and x_window is not None:
        for xw in x_window:
            u, _ = to_px((xw, 0.0))
            draw.line([(u, margin), (u, height - margin)], fill=(120, 120, 120), width=2)

    if title:
        draw.text((margin, 10), title, fill=(0, 0, 0))

    if info_text:
        lines = [ln.rstrip() for ln in str(info_text).splitlines() if ln.strip()]
        if lines:
            x_txt = 12
            y_txt = 10
            line_boxes = [draw.textbbox((0, 0), line) for line in lines]
            text_w = max((box[2] - box[0]) for box in line_boxes)
            text_h = sum((box[3] - box[1]) for box in line_boxes) + (max(0, len(lines) - 1) * 4)
            draw.rectangle(
                [(x_txt - 6, y_txt - 4), (x_txt + text_w + 6, y_txt + text_h + 4)],
                fill=(255, 255, 255),
            )
            cy = y_txt
            for line, box in zip(lines, line_boxes):
                draw.text((x_txt, cy), line, fill=(0, 0, 0))
                cy += (box[3] - box[1]) + 4

    if crop_to_content:
        bg = Image.new("RGB", img.size, "white")
        bbox = ImageChops.difference(img, bg).getbbox()
        if bbox is not None:
            pad = max(0, int(crop_padding))
            left = max(0, int(bbox[0]) - pad)
            top = max(0, int(bbox[1]) - pad)
            right = min(img.width, int(bbox[2]) + pad)
            bottom = min(img.height, int(bbox[3]) + pad)
            img = img.crop((left, top, right, bottom))

    img.save(out_png)
