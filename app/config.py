"""
产品级配置：本地安装 / 云服务器共用。
优先级：环境变量 > config.yaml > 默认值
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("LEADHUNTER_DATA", str(ROOT / "data")))
CONFIG_FILE = Path(os.environ.get("LEADHUNTER_CONFIG", str(ROOT / "config.yaml")))


DEFAULTS: dict[str, Any] = {
    "app": {
        "name": "TradeLead Hunter",
        "name_zh": "外贸获客台",
        "version": "2.0.0",
        "tagline": "Product-grade B2B lead acquisition workstation",
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8866,
        "workers": 1,
        "cors_origins": ["*"],
        "base_path": "",
    },
    "data": {
        "dir": str(DATA_DIR),
        "db_name": "leads.db",
    },
    "scrape": {
        "require_contact": True,
        "default_max_sites": 12,
        "request_timeout": 25,
        "polite_delay": 0.35,
        "user_agent": (
            "Mozilla/5.0 (compatible; TradeLeadHunter/2.0; +https://github.com/xiaokaige1130-maker/trade-lead-hunter)"
        ),
    },
    "features": {
        "social_comments": True,
        "maps": True,
        "directory": True,
        "b2b": True,
        "domain_crawl": True,
        "email_gen": True,
        "web_hunt": True,
    },
    "security": {
        "api_token": "",  # 非空则要求 Header: X-API-Token
        "allow_export": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_overrides(cfg: dict) -> dict:
    """从环境变量覆盖关键项。"""
    if os.environ.get("LEADHUNTER_HOST"):
        cfg["server"]["host"] = os.environ["LEADHUNTER_HOST"]
    if os.environ.get("LEADHUNTER_PORT"):
        cfg["server"]["port"] = int(os.environ["LEADHUNTER_PORT"])
    if os.environ.get("LEADHUNTER_API_TOKEN"):
        cfg["security"]["api_token"] = os.environ["LEADHUNTER_API_TOKEN"]
    if os.environ.get("LEADHUNTER_DATA"):
        cfg["data"]["dir"] = os.environ["LEADHUNTER_DATA"]
    if os.environ.get("LEADHUNTER_CORS"):
        cfg["server"]["cors_origins"] = [
            x.strip() for x in os.environ["LEADHUNTER_CORS"].split(",") if x.strip()
        ]
    return cfg


@lru_cache(maxsize=1)
def get_settings() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    # yaml
    if CONFIG_FILE.exists():
        try:
            raw = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
            cfg = _deep_merge(cfg, raw)
        except Exception:
            pass
    cfg = _env_overrides(cfg)
    # 确保 data 目录
    Path(cfg["data"]["dir"]).mkdir(parents=True, exist_ok=True)
    return cfg


def db_path() -> Path:
    s = get_settings()
    return Path(s["data"]["dir"]) / s["data"]["db_name"]


def app_meta() -> dict[str, str]:
    s = get_settings()
    return {
        "name": s["app"]["name"],
        "name_zh": s["app"]["name_zh"],
        "version": s["app"]["version"],
        "tagline": s["app"]["tagline"],
    }


def reload_settings() -> dict[str, Any]:
    get_settings.cache_clear()
    return get_settings()
