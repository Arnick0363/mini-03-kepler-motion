# -*- coding: utf-8 -*-
"""
由公开路网几何生成教学用轨迹样本（不是个人定位，也不是 Q2 的真实导出）。

路线：data/route_lovers_road.json
    OSRM 自行车路径，途经珠海情侣南路 / 情侣中路，南起拱北一侧，北至渔女。
时间、速度、高程是按骑行节奏合成的，用来演示 Kepler 的时间轴和速度着色。

用法：
    python make_sample.py
输出：
    data/sample_track.csv   列与 Q2 清洗结果对齐：time, lat, lon, ele, speed_kmh
"""

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROUTE_FILE = ROOT / "data" / "route_lovers_road.json"
OUT_FILE = ROOT / "data" / "sample_track.csv"

START = datetime(2024, 11, 16, 7, 32, 0, tzinfo=timezone(timedelta(hours=8)))
DT_SECONDS = 2
RIGHT_OFFSET_M = 4.0
EARTH_M = 6_371_000


def haversine_m(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(min(1.0, a)))


def bearing_deg(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def offset_m(lon, lat, bearing, meters):
    br = math.radians(bearing)
    dlat = meters * math.cos(br) / 111_320
    dlon = meters * math.sin(br) / (111_320 * math.cos(math.radians(lat)))
    return lon + dlon, lat + dlat


def turn_deg(b1, b2):
    return abs((b2 - b1 + 180) % 360 - 180)


def build_profile(coords):
    """沿折线累计里程，并按转角给出目标速度（km/h）。"""
    cum = [0.0]
    bearings = []
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        cum.append(cum[-1] + haversine_m(lon1, lat1, lon2, lat2))
        bearings.append(bearing_deg(lon1, lat1, lon2, lat2))
    bearings.append(bearings[-1])

    speeds = []
    for i in range(len(coords)):
        if 0 < i < len(coords) - 1:
            angle = turn_deg(bearings[i - 1], bearings[i])
        else:
            angle = 0
        cruise = 21.5 + 1.8 * math.sin(cum[i] / 850)
        slow = 11.0
        blend = min(angle / 75.0, 1.0)
        speeds.append(cruise * (1 - blend) + slow * blend)

    # 约 80 米窗口平滑，避免速度在单个顶点上跳变
    smoothed = []
    for i, dist in enumerate(cum):
        window = [speeds[j] for j, d in enumerate(cum) if abs(d - dist) <= 40]
        smoothed.append(sum(window) / len(window))
    return cum, bearings, smoothed


def interp(cum, values, dist):
    if dist <= 0:
        return values[0], 0
    if dist >= cum[-1]:
        return values[-1], len(cum) - 2
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= dist:
            lo = mid
        else:
            hi = mid
    span = cum[hi] - cum[lo]
    t = 0 if span == 0 else (dist - cum[lo]) / span
    if isinstance(values[0], tuple):
        mixed = tuple(values[lo][k] * (1 - t) + values[hi][k] * t for k in range(len(values[0])))
        return mixed, lo
    return values[lo] * (1 - t) + values[hi] * t, lo


def altitude_m(dist_m):
    """示意高程：海滨路整体很平，中段加一个缓坡，便于图层里看到第三维。"""
    rise = 7.5 * math.exp(-((dist_m - 6200) / 700) ** 2)
    wave = 2.2 * math.sin(dist_m / 1600)
    return 4.5 + rise + wave


def synthesize(coords):
    cum, bearings, speeds = build_profile(coords)
    total = cum[-1]
    rng = random.Random(20241116)
    wander = 0.0
    rows = []
    dist = 0.0
    elapsed = 0

    while True:
        at_end = dist >= total - 0.4
        sample_dist = total if at_end else dist
        (lon, lat), idx = interp(cum, coords, sample_dist)
        speed, _ = interp(cum, speeds, sample_dist)
        heading = bearings[min(idx, len(bearings) - 1)]
        if not at_end:
            wander = max(-2.2, min(2.2, 0.86 * wander + rng.uniform(-0.35, 0.35)))
        lon, lat = offset_m(lon, lat, heading + 90, RIGHT_OFFSET_M + wander)
        moment = START + timedelta(seconds=elapsed)
        rows.append(
            {
                "time": moment.isoformat(timespec="seconds"),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "ele": round(altitude_m(sample_dist), 1),
                "speed_kmh": round(speed, 1),
            }
        )
        if at_end:
            break
        step = speed / 3.6 * DT_SECONDS
        if dist + step >= total:
            # 最后一步落在终点，时间按剩余距离折算，保证速度自洽
            remain = total - dist
            elapsed += max(1, int(round(remain / (speed / 3.6))))
            dist = total
        else:
            dist += step
            elapsed += DT_SECONDS
    return rows, total


def main():
    payload = json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    coords = [tuple(p) for p in payload["coordinates"]]
    if len(coords) < 2:
        raise SystemExit(f"路线点太少：{ROUTE_FILE}")

    rows, total_m = synthesize(coords)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", encoding="utf-8", newline="\n") as f:
        f.write("time,lat,lon,ele,speed_kmh\n")
        for row in rows:
            f.write(
                f"{row['time']},{row['lat']:.6f},{row['lon']:.6f},"
                f"{row['ele']:.1f},{row['speed_kmh']:.1f}\n"
            )

    minutes = (len(rows) - 1) * DT_SECONDS / 60
    print(f"样本已写入 {OUT_FILE.relative_to(ROOT)}")
    print(f"  点数：{len(rows)}")
    print(f"  里程：{total_m / 1000:.2f} km")
    print(f"  时长：约 {minutes:.0f} 分钟（每 {DT_SECONDS} 秒一点）")
    print(f"  起点：{rows[0]['time']}  ({rows[0]['lat']}, {rows[0]['lon']})")
    print(f"  终点：{rows[-1]['time']}  ({rows[-1]['lat']}, {rows[-1]['lon']})")


if __name__ == "__main__":
    main()
