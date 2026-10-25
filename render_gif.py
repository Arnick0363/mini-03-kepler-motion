# -*- coding: utf-8 -*-
"""
把 Kepler 点表渲染成暗色底图上的轨迹动画，供 README 首屏嵌入。

底图是 Esri World Dark Gray（深色画布，带路名）。CARTO 栅格瓦片现已要求 API Key，
所以动图不再用它；交互地图仍由 Kepler.gl 加载 dark-matter 矢量样式。
镜头跟着当前位置走，已走路径按速度着色，最近约 90 秒加粗，作为拖尾。
"""

import csv
import io
import math
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
TILE_CACHE = ROOT / ".tilecache" / "esri"
BASE_URL = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
)
LABEL_URL = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
)
ZOOM = 15
FRAME_W, FRAME_H = 960, 540
N_FRAMES = 42
FRAME_MS = 110
HOLD_FRAMES = 6
TRAIL_SECONDS = 240
TILE_PX = 256

SPEED_STOPS = (
    (10.0, (27, 154, 170)),
    (16.0, (95, 203, 116)),
    (20.0, (244, 228, 9)),
    (24.0, (244, 162, 97)),
    (30.0, (230, 57, 70)),
)


def world_px(lon, lat, zoom):
    n = (2 ** zoom) * TILE_PX
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def speed_color(speed):
    if speed <= SPEED_STOPS[0][0]:
        return SPEED_STOPS[0][1]
    if speed >= SPEED_STOPS[-1][0]:
        return SPEED_STOPS[-1][1]
    for (v0, c0), (v1, c1) in zip(SPEED_STOPS, SPEED_STOPS[1:]):
        if v0 <= speed <= v1:
            t = (speed - v0) / (v1 - v0)
            return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))
    return SPEED_STOPS[-1][1]


def load_font(size, bold=False):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def fetch_bytes(url, dest):
    if dest.exists() and dest.stat().st_size > 200:
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "mini-03-kepler-motion/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return data


def fetch_tile(z, x, y):
    """Esri 瓦片顺序是 z/y/x。底图是 JPEG，注记是带透明通道的 PNG。"""
    try:
        base_bytes = fetch_bytes(BASE_URL.format(z=z, y=y, x=x), TILE_CACHE / str(z) / str(x) / f"{y}-base")
        image = Image.open(io.BytesIO(base_bytes)).convert("RGBA")
    except Exception:
        return Image.new("RGB", (TILE_PX, TILE_PX), (28, 28, 28))
    try:
        label_bytes = fetch_bytes(LABEL_URL.format(z=z, y=y, x=x), TILE_CACHE / str(z) / str(x) / f"{y}-label")
        labels = Image.open(io.BytesIO(label_bytes)).convert("RGBA")
        image.alpha_composite(labels)
    except Exception:
        pass
    return image.convert("RGB")


def stitch_basemap(points):
    xs, ys = zip(*(world_px(p["lon"], p["lat"], ZOOM) for p in points))
    pad_x, pad_y = FRAME_W * 0.55, FRAME_H * 0.55
    min_x, max_x = min(xs) - pad_x, max(xs) + pad_x
    min_y, max_y = min(ys) - pad_y, max(ys) + pad_y
    tile_x0, tile_x1 = int(min_x // TILE_PX), int(max_x // TILE_PX)
    tile_y0, tile_y1 = int(min_y // TILE_PX), int(max_y // TILE_PX)
    width = (tile_x1 - tile_x0 + 1) * TILE_PX
    height = (tile_y1 - tile_y0 + 1) * TILE_PX
    canvas = Image.new("RGB", (width, height), (14, 17, 22))
    count = (tile_x1 - tile_x0 + 1) * (tile_y1 - tile_y0 + 1)
    print(f"  底图瓦片：z{ZOOM}，{count} 张")
    for tx in range(tile_x0, tile_x1 + 1):
        for ty in range(tile_y0, tile_y1 + 1):
            tile = fetch_tile(ZOOM, tx, ty)
            canvas.paste(tile, ((tx - tile_x0) * TILE_PX, (ty - tile_y0) * TILE_PX))
    origin = (tile_x0 * TILE_PX, tile_y0 * TILE_PX)
    return canvas, origin


def load_points(csv_path):
    points = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            points.append(
                {
                    "lon": float(row["lon"]),
                    "lat": float(row["lat"]),
                    "speed": float(row["speed_kmh"]),
                    "time": row["timestamp"],
                }
            )
    if len(points) < 2:
        raise SystemExit("点数不足，无法做动画")
    return points


def clock_label(iso_text):
    # 2024-11-16T07:32:00+08:00 -> 07:32:00
    clock = iso_text.split("T", 1)[-1]
    return clock[:8]


def crop_frame(basemap, origin, center_xy):
    cx = center_xy[0] - origin[0]
    cy = center_xy[1] - origin[1]
    left = int(round(cx - FRAME_W / 2))
    top = int(round(cy - FRAME_H / 2))
    left = max(0, min(left, basemap.width - FRAME_W))
    top = max(0, min(top, basemap.height - FRAME_H))
    return basemap.crop((left, top, left + FRAME_W, top + FRAME_H)), (origin[0] + left, origin[1] + top)


def project(points, origin):
    out = []
    for p in points:
        x, y = world_px(p["lon"], p["lat"], ZOOM)
        out.append((x - origin[0], y - origin[1], p["speed"]))
    return out


def draw_plain(draw, pts, color, width):
    for i in range(1, len(pts)):
        draw.line((pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]), fill=color, width=width)


def draw_segments(draw, pts, width, alpha_scale=1.0):
    for i in range(1, len(pts)):
        color = speed_color(pts[i][2])
        if alpha_scale < 1:
            color = tuple(int(c * alpha_scale + 28 * (1 - alpha_scale)) for c in color)
        draw.line((pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]), fill=color, width=width)


def draw_hud(frame, index, total, clock, speed, progress):
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((16, 14, 360, 118), radius=12, fill=(8, 12, 18, 186))
    title_font = load_font(20, bold=True)
    body_font = load_font(16, bold=False)
    small_font = load_font(13, bold=False)
    draw.text((30, 22), "珠海情侣路 · 教学样本", font=title_font, fill=(244, 247, 251, 255))
    draw.text((30, 52), f"{clock}    {speed:4.1f} km/h", font=body_font, fill=(255, 206, 92, 255))
    draw.text((30, 80), "已走路径按速度着色 · 青慢橙快", font=small_font, fill=(186, 196, 208, 255))

    bar_x, bar_y, bar_w, bar_h = 16, FRAME_H - 28, FRAME_W - 32, 8
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=4, fill=(255, 255, 255, 40))
    fill_w = max(8, int(bar_w * progress))
    draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=4, fill=(255, 196, 64, 230))

    note = "© Esri © OpenStreetMap"
    draw.text((FRAME_W - 210, FRAME_H - 48), note, font=small_font, fill=(186, 194, 204, 220))
    composed = Image.alpha_composite(frame.convert("RGBA"), overlay)
    return composed.convert("RGB")


def render(csv_path, gif_path):
    points = load_points(csv_path)
    print("渲染动图…")
    basemap, origin = stitch_basemap(points)
    frames = []
    indexes = [round(i * (len(points) - 1) / (N_FRAMES - 1)) for i in range(N_FRAMES)]

    for nth, idx in enumerate(indexes, start=1):
        head = points[idx]
        hx, hy = world_px(head["lon"], head["lat"], ZOOM)
        frame, frame_origin = crop_frame(basemap, origin, (hx, hy))
        ahead = project(points[idx:], frame_origin)
        traveled = project(points[: idx + 1], frame_origin)
        draw = ImageDraw.Draw(frame)
        if len(ahead) >= 2:
            draw_plain(draw, ahead, (88, 96, 108), 3)
        if len(traveled) >= 2:
            draw_segments(draw, traveled, width=4, alpha_scale=0.55)
            trail_n = max(2, TRAIL_SECONDS // 2)
            draw_segments(draw, traveled[-trail_n:], width=7, alpha_scale=1.0)
        px, py, _ = traveled[-1]
        glow = speed_color(head["speed"])
        draw.ellipse((px - 8, py - 8, px + 8, py + 8), fill=glow)
        draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=(255, 255, 255))
        progress = idx / (len(points) - 1)
        frame = draw_hud(frame, nth, N_FRAMES, clock_label(head["time"]), head["speed"], progress)
        frames.append(frame)
        if nth % 10 == 0 or nth == len(indexes):
            print(f"  帧 {nth}/{len(indexes)}")

    frames.extend([frames[-1]] * HOLD_FRAMES)
    palette = frames[0].quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    quantized = [palette]
    for frame in frames[1:]:
        quantized.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))

    gif_path.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        gif_path,
        save_all=True,
        append_images=quantized[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    size_mb = gif_path.stat().st_size / (1024 * 1024)
    print(f"动图已写入 {gif_path}（{size_mb:.2f} MB）")
    if size_mb > 10:
        raise SystemExit("动图超过 10MB，需要减少帧数或尺寸")
    return gif_path


if __name__ == "__main__":
    render(ROOT / "data" / "kepler_track.csv", ROOT / "docs" / "animation.gif")
