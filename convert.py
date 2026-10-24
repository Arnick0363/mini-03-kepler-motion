# -*- coding: utf-8 -*-
"""
convert.py — Q7 Kepler.gl 轨迹时空动画 · 数据转换
把 Q2 清洗后的轨迹转为 Kepler.gl Trip 图层要求的 CSV 格式（timestamp / lat / lon）。

用法：
    python convert.py                          # 默认读取 ../mini-02-gps-tracks/outputs/track_cleaned.csv
    python convert.py <你的轨迹csv路径>         # 指定其他输入
输出：data/kepler_track.csv（浏览器拖入 kepler.gl 即可）
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_INPUT = "../mini-02-gps-tracks/outputs/track_cleaned.csv"
OUTPUT = "data/kepler_track.csv"


def main():
    ap = argparse.ArgumentParser(description="轨迹 → Kepler.gl Trip CSV 转换器")
    ap.add_argument("input", nargs="?", default=DEFAULT_INPUT,
                    help=f"输入轨迹 CSV，默认 {DEFAULT_INPUT}")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        sys.exit(f"输入文件不存在：{src}\n请先在 Q2 项目运行 parse_tracks.py，或指定其他轨迹文件")

    df = pd.read_csv(src)

    # 列名探测（兼容 Q2 输出与常见格式）
    col_time = next((c for c in df.columns if c.lower() in ("time", "timestamp", "datetime")), None)
    col_lat = next((c for c in df.columns if c.lower() in ("lat", "latitude")), None)
    col_lon = next((c for c in df.columns if c.lower() in ("lon", "lng", "longitude")), None)
    if not all([col_time, col_lat, col_lon]):
        sys.exit(f"缺少必要列（需 time/lat/lon），实际列：{list(df.columns)}")

    out = pd.DataFrame({
        "timestamp": pd.to_datetime(df[col_time]).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lat": df[col_lat],
        "lon": df[col_lon],
    })

    # 附加列（有则带上，Kepler 里可做颜色/高度映射）
    for cand, name in [("speed_kmh", "speed_kmh"), ("ele", "elevation")]:
        if cand in df.columns:
            out[name] = df[cand]

    # 排序 + 去空（Trip 动画要求时间单调递增）
    out = out.dropna().sort_values("timestamp").reset_index(drop=True)

    Path("data").mkdir(exist_ok=True)
    out.to_csv(OUTPUT, index=False)

    span = f"{out['timestamp'].iloc[0]} → {out['timestamp'].iloc[-1]}"
    print(f"转换完成：{OUTPUT}")
    print(f"  点数：{len(out)}")
    print(f"  时间范围：{span}")
    print(f"  下一步：浏览器打开 https://kepler.gl/demo ，把该 CSV 拖入页面")


if __name__ == "__main__":
    main()
