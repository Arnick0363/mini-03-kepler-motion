# -*- coding: utf-8 -*-
"""
convert.py — 把清洗后的 GPS 轨迹转成 Kepler.gl Trip 动画。

默认读教学样本 data/sample_track.csv（与 Q2 清洗结果同一套列：time / lat / lon）。
个人轨迹请显式传入路径，并且不要把输出提交到公开仓库。

    python convert.py
    python convert.py path/to/track_cleaned.csv
    python convert.py ride.gpx --no-gif

产出（都在项目目录内，与当前工作目录无关）：
    data/kepler_track.csv        点表：id, trip_id, timestamp, lat, lon, altitude, speed_kmh
    data/kepler_trip.geojson     Trip 图层：LineString 坐标为 [lon, lat, altitude, unix 秒]
    docs/kepler_config.json      数据集 + 图层 / 底图 / 时间轴配置
    docs/kepler_map.html         已绑好 Trip 与暗色底图的交互地图
    docs/animation.gif           README 动图（--no-gif 可跳过）
"""

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from kepler_page import write_html

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "data" / "sample_track.csv"
DATA_ID = "kepler-track"
SEGMENT_SECONDS = 20
EARTH_M = 6_371_000
SPEED_COLORS = ["#1B9AAA", "#5FCB74", "#F4E409", "#F4A261", "#E63946"]


def find_col(columns, names):
    lookup = {str(c).lower(): c for c in columns}
    for name in names:
        if name in lookup:
            return lookup[name]
    return None


def local_tag(tag):
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def haversine_m(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(min(1.0, a)))


def read_gpx(path):
    root = ET.parse(path).getroot()
    records = []
    tracks = [el for el in root.iter() if local_tag(el.tag) == "trk"] or [root]
    for index, trk in enumerate(tracks, start=1):
        name = None
        for child in list(trk):
            if local_tag(child.tag) == "name" and child.text:
                name = child.text.strip()
        points = [el for el in trk.iter() if local_tag(el.tag) == "trkpt"]
        for pt in points:
            time_text = None
            ele = None
            for child in list(pt):
                tag = local_tag(child.tag)
                if tag == "time":
                    time_text = child.text
                elif tag == "ele" and child.text:
                    ele = float(child.text)
            records.append(
                {
                    "time": time_text,
                    "lat": float(pt.attrib["lat"]),
                    "lon": float(pt.attrib["lon"]),
                    "ele": ele,
                    "trip_id": name or f"trip-{index}",
                }
            )
    if not records:
        raise SystemExit(f"GPX 里没有轨迹点：{path}")
    return pd.DataFrame(records)


def read_table(path):
    if path.suffix.lower() == ".gpx":
        return read_gpx(path)
    frame = pd.read_csv(path)
    if frame.empty:
        raise SystemExit(f"输入是空表：{path}")
    return frame


def epoch_seconds(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.timestamp())


def format_timestamp(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.strftime("%Y-%m-%dT%H:%M:%S")
    return ts.isoformat(timespec="seconds")


def load_points(frame):
    col_time = find_col(frame.columns, ("time", "timestamp", "datetime"))
    col_lat = find_col(frame.columns, ("lat", "latitude"))
    col_lon = find_col(frame.columns, ("lon", "lng", "longitude"))
    col_ele = find_col(frame.columns, ("ele", "elevation", "altitude", "alt"))
    col_speed = find_col(frame.columns, ("speed_kmh", "speed"))
    col_trip = find_col(frame.columns, ("trip_id",))
    missing = [name for name, col in (("time", col_time), ("lat", col_lat), ("lon", col_lon)) if col is None]
    if missing:
        raise SystemExit(f"缺少列 {missing}，实际列：{list(frame.columns)}")

    work = pd.DataFrame(
        {
            "time": pd.to_datetime(frame[col_time], format="mixed", utc=False),
            "lat": pd.to_numeric(frame[col_lat], errors="coerce"),
            "lon": pd.to_numeric(frame[col_lon], errors="coerce"),
            "ele": pd.to_numeric(frame[col_ele], errors="coerce") if col_ele else 0.0,
            "speed_kmh": pd.to_numeric(frame[col_speed], errors="coerce") if col_speed else math.nan,
            "trip_id": frame[col_trip].astype(str) if col_trip else "trip-1",
        }
    )
    before = len(work)
    work = work.dropna(subset=["time", "lat", "lon"]).sort_values(["trip_id", "time"])
    work = work.drop_duplicates(subset=["trip_id", "time"], keep="first")
    if len(work) < 2:
        raise SystemExit("有效点少于 2 个，无法构成轨迹")

    rows = []
    for record in work.to_dict(orient="records"):
        rows.append(
            {
                "time": record["time"],
                "lat": float(record["lat"]),
                "lon": float(record["lon"]),
                "ele": 0.0 if pd.isna(record["ele"]) else float(record["ele"]),
                "speed_kmh": None if pd.isna(record["speed_kmh"]) else float(record["speed_kmh"]),
                "trip_id": record["trip_id"],
                "epoch": epoch_seconds(record["time"]),
            }
        )
    fill_speed(rows)
    return rows, before - len(work)


def fill_speed(rows):
    grouped = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[row["trip_id"]].append(index)
    for indexes in grouped.values():
        for pos in range(len(indexes) - 1):
            current, nxt = rows[indexes[pos]], rows[indexes[pos + 1]]
            if current["speed_kmh"] is not None:
                continue
            dt = nxt["epoch"] - current["epoch"]
            if dt <= 0:
                continue
            dist = haversine_m(current["lon"], current["lat"], nxt["lon"], nxt["lat"])
            current["speed_kmh"] = dist / dt * 3.6
        if rows[indexes[-1]]["speed_kmh"] is None and len(indexes) > 1:
            rows[indexes[-1]]["speed_kmh"] = rows[indexes[-2]]["speed_kmh"]
        for index in indexes:
            if rows[index]["speed_kmh"] is None:
                rows[index]["speed_kmh"] = 0.0


def segment_rows(rows, segment_seconds):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["trip_id"]].append(row)
    segments = []
    multiple = len(grouped) > 1
    for trip_id in sorted(grouped):
        trip_rows = grouped[trip_id]
        t0 = trip_rows[0]["epoch"]
        buckets = defaultdict(list)
        for row in trip_rows:
            buckets[(row["epoch"] - t0) // segment_seconds].append(row)
        for seg_index in sorted(buckets):
            bucket = buckets[seg_index]
            seg_id = f"{trip_id}-s{seg_index:03d}" if multiple else f"s{seg_index:03d}"
            mean_speed = sum(row["speed_kmh"] for row in bucket) / len(bucket)
            for row in bucket:
                row["id"] = seg_id
            segments.append(
                {"id": seg_id, "trip_id": trip_id, "rows": bucket, "speed": mean_speed}
            )
    return segments


def line_coordinates(segment, previous_tail):
    coords = [previous_tail] if previous_tail is not None else []
    for row in segment["rows"]:
        coords.append(
            [round(row["lon"], 6), round(row["lat"], 6), round(row["ele"], 1), int(row["epoch"])]
        )
    if len(coords) == 1:
        coords.append(list(coords[0]))
    return coords


def build_features(segments):
    features = []
    tails = {}
    for segment in segments:
        coords = line_coordinates(segment, tails.get(segment["trip_id"]))
        tails[segment["trip_id"]] = coords[-1]
        mean_ele = sum(row["ele"] for row in segment["rows"]) / len(segment["rows"])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": segment["id"],
                    "trip_id": segment["trip_id"],
                    "speed_kmh": round(segment["speed"], 1),
                    "altitude": round(mean_ele, 1),
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )
    return features


def summarize(rows):
    distance = 0.0
    fastest = max(row["speed_kmh"] for row in rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["trip_id"]].append(row)
    for trip_rows in grouped.values():
        for left, right in zip(trip_rows, trip_rows[1:]):
            distance += haversine_m(left["lon"], left["lat"], right["lon"], right["lat"])
    duration = max(row["epoch"] for row in rows) - min(row["epoch"] for row in rows)
    return {
        "points": len(rows),
        "distance_km": distance / 1000,
        "duration_min": duration / 60,
        "mean_kmh": (distance / duration * 3.6) if duration else 0,
        "max_kmh": fastest,
        "start": format_timestamp(min(rows, key=lambda row: row["epoch"])["time"]),
        "end": format_timestamp(max(rows, key=lambda row: row["epoch"])["time"]),
        "center_lat": sum(row["lat"] for row in rows) / len(rows),
        "center_lon": sum(row["lon"] for row in rows) / len(rows),
    }


def build_saved_map(features, summary):
    fields = [
        {"name": "geometry", "type": "geojson", "format": "", "analyzerType": "GEOMETRY"},
        {"name": "id", "type": "string", "format": "", "analyzerType": "STRING"},
        {"name": "speed_kmh", "type": "real", "format": "", "analyzerType": "FLOAT"},
        {"name": "altitude", "type": "real", "format": "", "analyzerType": "FLOAT"},
        {"name": "trip_id", "type": "string", "format": "", "analyzerType": "STRING"},
    ]
    rows = []
    for feature in features:
        props = feature["properties"]
        rows.append(
            [
                {"type": "Feature", "properties": {}, "geometry": feature["geometry"]},
                props["id"],
                props["speed_kmh"],
                props["altitude"],
                props["trip_id"],
            ]
        )
    inner = {
        "visState": {
            "filters": [],
            "layers": [
                {
                    "id": "ride-trip",
                    "type": "trip",
                    "config": {
                        "dataId": DATA_ID,
                        "label": "轨迹",
                        "color": [255, 196, 64],
                        "highlightColor": [252, 242, 26, 255],
                        "columns": {"geojson": {"value": "geometry", "fieldIdx": 0}},
                        "isVisible": True,
                        "visConfig": {
                            "opacity": 0.95,
                            "thickness": 4,
                            "trailLength": 220,
                            "fadeTrail": True,
                            "sizeRange": [0, 10],
                            "colorRange": {
                                "name": "Ride speed",
                                "type": "sequential",
                                "category": "Custom",
                                "colors": SPEED_COLORS,
                            },
                        },
                    },
                    "visualChannels": {
                        "colorField": {"name": "speed_kmh", "type": "real"},
                        "colorScale": "quantile",
                        "sizeField": None,
                        "sizeScale": "linear",
                    },
                }
            ],
            "interactionConfig": {
                "tooltip": {
                    "fieldsToShow": {
                        DATA_ID: [
                            {"name": "id", "format": None},
                            {"name": "speed_kmh", "format": None},
                            {"name": "altitude", "format": None},
                        ]
                    },
                    "enabled": True,
                },
                "brush": {"size": 0.5, "enabled": False},
                "geocoder": {"enabled": False},
                "coordinate": {"enabled": False},
            },
            "layerBlending": "additive",
            "splitMaps": [],
            "animationConfig": {"currentTime": None, "speed": 1},
        },
        "mapState": {
            "bearing": 0,
            "dragRotate": False,
            "latitude": round(summary["center_lat"], 6),
            "longitude": round(summary["center_lon"], 6),
            "pitch": 0,
            "zoom": 12.5,
            "isSplit": False,
        },
        "mapStyle": {
            "styleType": "dark-matter",
            "topLayerGroups": {},
            "visibleLayerGroups": {
                "label": True,
                "road": True,
                "border": False,
                "building": True,
                "water": True,
                "land": True,
                "3d building": False,
            },
            "threeDBuildingColor": [9.665468314072013, 17.183054267933154, 31.1442867897876],
            "mapStyles": {},
        },
    }
    saved = {
        "datasets": [
            {
                "version": "v1",
                "data": {
                    "id": DATA_ID,
                    "label": "轨迹",
                    "color": [255, 196, 64],
                    "allData": rows,
                    "fields": fields,
                },
            }
        ],
        "config": {"version": "v1", "config": inner},
        "info": {
            "app": "kepler.gl",
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "title": "轨迹时空动画",
            "source": "mini-03-kepler-motion",
        },
    }
    return saved, rows, fields, inner


def write_points_csv(path, rows):
    frame = pd.DataFrame(
        {
            "id": [row["id"] for row in rows],
            "trip_id": [row["trip_id"] for row in rows],
            "timestamp": [format_timestamp(row["time"]) for row in rows],
            "lat": [round(row["lat"], 6) for row in rows],
            "lon": [round(row["lon"], 6) for row in rows],
            "altitude": [round(row["ele"], 1) for row in rows],
            "speed_kmh": [round(row["speed_kmh"], 1) for row in rows],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="清洗轨迹 → Kepler.gl Trip 文件")
    parser.add_argument("input", nargs="?", default=str(SAMPLE), help="CSV 或 GPX，默认教学样本")
    parser.add_argument("--segment-seconds", type=int, default=SEGMENT_SECONDS)
    parser.add_argument("--no-gif", action="store_true", help="不渲染 README 动图")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    segment_seconds = max(5, args.segment_seconds)
    source = Path(args.input)
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    if not source.exists():
        raise SystemExit(
            f"找不到输入文件：{source}\n"
            "先运行 python make_sample.py 生成教学样本，或传入 Q2 的 track_cleaned.csv / GPX。"
        )
    if source.resolve() != SAMPLE.resolve():
        print("注意：这次用的不是仓库里的教学样本。")
        print("输出会覆盖 data/ 与 docs/ 里的 Kepler 文件。个人轨迹不要提交到公开仓库。")

    rows, dropped = load_points(read_table(source))
    fast = sum(row["speed_kmh"] > 80 for row in rows)
    if fast:
        print(f"提示：有 {fast} 个点速度超过 80 km/h，动画会在这些点上跳。请先回到 Q2 的清洗规则。")

    segments = segment_rows(rows, segment_seconds)
    features = build_features(segments)
    broken = [
        feature["properties"]["id"]
        for feature in features
        if any(len(coord) != 4 for coord in feature["geometry"]["coordinates"])
    ]
    if broken:
        raise SystemExit(f"有线段不是四维坐标：{broken[:5]}")

    summary = summarize(rows)
    saved, table_rows, fields, inner = build_saved_map(features, summary)
    csv_path = ROOT / "data" / "kepler_track.csv"
    geojson_path = ROOT / "data" / "kepler_trip.geojson"
    config_path = ROOT / "docs" / "kepler_config.json"
    html_path = ROOT / "docs" / "kepler_map.html"

    write_points_csv(csv_path, rows)
    geojson_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    write_html(html_path, table_rows, fields, inner)

    print(f"输入：{source}")
    print(f"点数：{summary['points']}    线段：{len(features)}    丢弃空值/重复时刻：{dropped}")
    print(f"里程：{summary['distance_km']:.2f} km    时长：{summary['duration_min']:.1f} 分钟")
    print(f"均速：{summary['mean_kmh']:.1f} km/h    最快：{summary['max_kmh']:.1f} km/h")
    print(f"时间：{summary['start']}  →  {summary['end']}")
    for path in (csv_path, geojson_path, config_path, html_path):
        print(f"已写 {path.relative_to(ROOT)}")

    if not args.no_gif:
        from render_gif import render

        render(csv_path, ROOT / "docs" / "animation.gif")
    return summary


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
