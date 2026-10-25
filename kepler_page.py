# -*- coding: utf-8 -*-
"""把轨迹和配置嵌进一个可直接打开的 Kepler.gl 页面。"""

import json
from pathlib import Path

HTML_SHELL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>轨迹时空动画 · Kepler.gl</title>
  <link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" />
  <style>
    html, body, #app { margin: 0; padding: 0; width: 100%; height: 100%; background: #0b0e14; }
    #status {
      position: absolute; z-index: 20; left: 16px; bottom: 16px;
      max-width: 460px; padding: 10px 14px; border-radius: 10px;
      background: rgba(8, 12, 18, 0.88); color: #f4f7fb;
      font: 14px/1.5 "Segoe UI", "Microsoft YaHei", sans-serif;
    }
  </style>
  <script>window.esmsInitOptions = {shimMode: true};</script>
  <script src="https://unpkg.com/es-module-shims@1.10.1/dist/es-module-shims.js"></script>
  <script type="importmap">
  {
    "imports": {
      "react": "https://esm.sh/react@19.1.0",
      "react/jsx-runtime": "https://esm.sh/react@19.1.0/jsx-runtime",
      "react-dom": "https://esm.sh/react-dom@19.1.0?external=react",
      "react-dom/client": "https://esm.sh/react-dom@19.1.0/client?external=react",
      "redux": "https://esm.sh/redux@5.0.1",
      "react-redux": "https://esm.sh/react-redux@9.3.0?external=react,react-dom,redux",
      "styled-components": "https://esm.sh/styled-components@6.1.19?external=react,react-dom"
    }
  }
  </script>
</head>
<body>
  <div id="app"></div>
  <div id="status">正在加载 Kepler.gl 与轨迹…</div>
  <script type="module">
    import * as React from "react";
    import * as ReactDOM from "react-dom";
    import * as ReactDOMClient from "react-dom/client";
    import * as Redux from "redux";
    import * as ReactRedux from "react-redux";
    import * as StyledComponents from "styled-components";

    window.React = React.default || React;
    window.ReactDOM = Object.assign({}, ReactDOM.default || ReactDOM, ReactDOMClient);
    window.Redux = Redux.default || Redux;
    window.ReactRedux = ReactRedux.default || ReactRedux;
    window.styled = Object.assign(StyledComponents.default, StyledComponents);

    const DATASET = __DATASET__;
    const MAP_CONFIG = __MAP_CONFIG__;

    function loadScript(src) {
      return new Promise(function (resolve, reject) {
        const script = document.createElement("script");
        script.src = src;
        script.onload = resolve;
        script.onerror = function () { reject(new Error(src)); };
        document.head.appendChild(script);
      });
    }

    function fail(message) {
      document.getElementById("status").textContent = message;
    }

    loadScript("https://unpkg.com/kepler.gl@3.3.0-alpha.6/umd/keplergl.min.js")
      .then(function () { boot(); })
      .catch(function (err) {
        fail("地图没有启动：" + (err && err.message ? err.message : err));
      });

    function boot() {
      const reducers = Redux.combineReducers({ keplerGl: KeplerGl.keplerGlReducer });
      const middlewares = KeplerGl.enhanceReduxMiddleware([]);
      const store = Redux.createStore(reducers, {}, Redux.applyMiddleware(...middlewares));

      function App() {
        const pair = React.useState({ width: window.innerWidth, height: window.innerHeight });
        const dimensions = pair[0];
        const setDimensions = pair[1];
        React.useEffect(function () {
          function onResize() {
            setDimensions({ width: window.innerWidth, height: window.innerHeight });
          }
          window.addEventListener("resize", onResize);
          return function () { window.removeEventListener("resize", onResize); };
        }, []);
        return React.createElement(
          "div",
          { style: { position: "absolute", inset: 0 } },
          React.createElement(KeplerGl.KeplerGl, {
            id: "map",
            mapboxApiAccessToken: "",
            width: dimensions.width,
            height: dimensions.height
          })
        );
      }

      const app = React.createElement(
        ReactRedux.Provider,
        { store: store },
        React.createElement(App, null)
      );
      ReactDOMClient.createRoot(document.getElementById("app")).render(app);

      let tries = 0;
      (function mountWhenReady() {
        const root = store.getState().keplerGl;
        if (!root || !root.map) {
          if (++tries > 80) {
            fail("地图容器没有挂上。可以改用 https://kepler.gl/demo 拖入 GeoJSON。");
            return;
          }
          setTimeout(mountWhenReady, 50);
          return;
        }
        store.dispatch(KeplerGl.addDataToMap({
          datasets: {
            info: { id: "kepler-track", label: "轨迹" },
            data: DATASET
          },
          options: { centerMap: true, readOnly: false },
          config: MAP_CONFIG
        }));
        setTimeout(startPlayback, 800);
      })();

      function startPlayback() {
        const vis = store.getState().keplerGl.map.visState;
        const layers = vis.layers || [];
        if (!layers.length) {
          fail("配置已载入，但没有图层。在左侧把图层类型改成 Trip，几何列选 geometry。");
          return;
        }
        document.getElementById("status").style.display = "none";
        if (!vis.animationConfig.isAnimating && KeplerGl.toggleLayerAnimation) {
          store.dispatch(KeplerGl.toggleLayerAnimation());
        }
      }
    }
  </script>
</body>
</html>
"""


def write_html(path: Path, rows, fields, inner_config):
    dataset = json.dumps({"fields": fields, "rows": rows}, ensure_ascii=False).replace("<", "\\u003c")
    config = json.dumps(inner_config, ensure_ascii=False).replace("<", "\\u003c")
    html = HTML_SHELL.replace("__DATASET__", dataset).replace("__MAP_CONFIG__", config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
