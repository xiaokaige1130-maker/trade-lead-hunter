"""python -m app  启动服务并尝试打开浏览器（桌面安装入口）。"""
from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from .config import get_settings


def main() -> None:
    s = get_settings()
    host = s["server"].get("host") or "127.0.0.1"
    port = int(s["server"].get("port") or 8866)
    open_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{open_host}:{port}/"

    def _open():
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()
    print(f"TradeLead Hunter → {url}")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
