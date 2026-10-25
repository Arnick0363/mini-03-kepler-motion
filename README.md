# mini-03-kepler-motion

把一条 GPS 轨迹放进 Kepler.gl 的 Trip 图层，沿时间轴看它怎么走完。暗色底图上，慢的地方偏青，快的地方偏橙。

![珠海情侣路轨迹动画](docs/animation.gif)

这是空间可视化的速成练习，把清洗后的点做成带时间轴的轨迹地图。

## 数据来源

仓库里的样本是教学数据，可以公开。

- 路线来自 OpenStreetMap 上的珠海情侣南路 / 情侣中路。`data/route_lovers_road.json` 是 OSRM 自行车路径，南起拱北一侧，北到香炉湾、渔女一带，约 15 公里。
- 时间、速度和高程由 `make_sample.py` 按骑行节奏合成：2024-11-16 07:32（UTC+8）出发，大约 44 分钟，直线段 20 km/h 出头，弯道降到 11 km/h 左右。高程只是一个几米到十几米的缓坡，用来占住 Trip 坐标里的高度位。
- 个人定位不在这个仓库里。Q2 如果已经洗出 `track_cleaned.csv` 或 GPX，把它的路径传给 `convert.py` 即可；那个输出不要提交。

## 复现

一条命令会写出点表、Trip GeoJSON、配置、交互地图和上面的动图。

```bash
pip install -r requirements.txt
python convert.py
```

然后用浏览器打开 `docs/kepler_map.html`。页面会载入 Trip 图层、Dark Matter 底图，并自动播放。需要能访问 Kepler.gl 和底图的 CDN。

如果浏览器拦截本地页面里的模块，在项目目录执行 `python -m http.server 8765`，再打开 `http://127.0.0.1:8765/docs/kepler_map.html`。

要在 [kepler.gl/demo](https://kepler.gl/demo) 里打开同一份动画，把 `docs/kepler_config.json` 拖进去。这个文件同时带有 133 段轨迹和图层配置。也可以只拖 `data/kepler_trip.geojson`：几何是 `[经度, 纬度, 高度, Unix 秒]`，Kepler 会把它认成 Trip。

换自己的轨迹时：

```bash
python convert.py path/to/track_cleaned.csv
python convert.py path/to/ride.gpx
```

输入认 `time` / `timestamp`、`lat`、`lon`（或 `lng`）。有 `ele` 和 `speed_kmh` 会保留，没有就按点距和时间补速度，高度记 0。

## 结果

教学样本转换后：

| 项目 | 数值 |
| --- | --- |
| 点数 | 1326，每 2 秒一个点 |
| 里程 | 14.98 km |
| 时长 | 44.1 分钟（07:32–08:16，UTC+8） |
| 均速 / 最快 | 20.4 / 23.3 km/h |
| Trip 线段 | 133 段，每段约 20 秒 |

轨迹从情侣南路靠海的一端往北，收到香炉湾附近的情侣中路。弯道段速度降到 11 km/h 左右，直线段回到 20 km/h 以上，颜色会跟着变。快慢来自样本生成时设定的骑行节奏，用来确认颜色通道。

交互地图里拖尾大约 220 秒，图层混合是 additive。动图用同一条轨迹画在 Esri 深色底图上，镜头跟着当前位置，灰线是还没走到的路。动图 3.7 MB，低于 10 MB，可以直接放在 README 顶部。

## 局限与致谢

- Kepler 页面固定使用 3.3.0-alpha.6 的 UMD 构建。官网 demo 的版本不同，拖入 GeoJSON 后如果没有自动变成 Trip，在图层类型里手动选 Trip。
- 点表 `data/kepler_track.csv` 的 `id` 是分段号，不是整趟行程的编号。整趟行程看 `trip_id`。分段是为了让每一小段带着自己的速度，Trip 才能沿路变色。
- 样本高程是脚本里的示意缓坡。真实轨迹里的漂移点要在 Q2 清洗阶段去掉；这里只在速度超过 80 km/h 时提示。
- CARTO 的栅格瓦片现在要 API Key，所以动图改用 Esri World Dark Gray。交互地图仍用 Kepler 自带的 dark-matter 矢量样式。
- 底图 © Esri、© OpenStreetMap 贡献者。路径几何经由 OSRM 对公开路网求了一次自行车路线。Kepler.gl 是开源时空可视化库（<https://docs.kepler.gl/>）。

## 项目结构

```
mini-03-kepler-motion/
├── make_sample.py              # 由公开路网生成教学样本
├── convert.py                  # CSV / GPX → Kepler 点表、GeoJSON、配置、HTML
├── render_gif.py               # 同一条轨迹的 README 动图
├── kepler_page.py              # 交互地图页面模板
├── data/sample_track.csv       # 教学样本，列与 Q2 清洗结果对齐
├── data/kepler_track.csv       # id, trip_id, timestamp, lat, lon, altitude, speed_kmh
├── data/kepler_trip.geojson    # Trip 用的四维 LineString
├── docs/kepler_config.json     # 数据集 + 图层配置
├── docs/kepler_map.html
└── docs/animation.gif
```

MIT
