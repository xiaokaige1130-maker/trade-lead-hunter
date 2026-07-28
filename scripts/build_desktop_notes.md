# 桌面安装包方案（后续）

目标：用户双击安装，不配 Python，打开即用。

## 方案 A — PyInstaller（推荐先做 Linux/Windows）

```bash
pip install pyinstaller
pyinstaller --name TradeLeadHunter \
  --add-data "static:static" \
  --add-data "config.yaml:." \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.protocols.http.auto \
  app/__main__.py
```

`app/__main__.py` 启动 uvicorn 并自动打开浏览器。

## 方案 B — Electron / Tauri 套壳

- 后端仍跑 FastAPI 子进程
- 前端 load `http://127.0.0.1:8866`
- 适合要「原生窗口 + 自动更新」

## 方案 C — 云网页服务

```bash
docker compose up -d
# 或
LEADHUNTER_API_TOKEN=xxx ./start.sh
```

Nginx 反代 8866，开 HTTPS，设 API Token。
