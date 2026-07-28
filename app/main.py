"""
TradeLead Hunter · 外贸获客台
产品级 FastAPI 入口 — 本地安装 / 云服务器共用
"""
from __future__ import annotations

import csv
import io
import time
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import comment_intercept as ci
from . import db
from . import hunter
from . import multi_scraper as ms
from .config import app_meta, get_settings

_BOOT = time.time()
_META = app_meta()
_SETTINGS = get_settings()

app = FastAPI(
    title=_META["name"],
    description=_META["tagline"],
    version=_META["version"],
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_SETTINGS["server"].get("cors_origins") or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()


@app.middleware("http")
async def api_token_guard(request: Request, call_next):
    """云部署可选：设置 LEADHUNTER_API_TOKEN 后，/api/* 需带 X-API-Token。"""
    token = (get_settings().get("security") or {}).get("api_token") or ""
    path = request.url.path
    if token and path.startswith("/api/") and path not in ("/api/health", "/api/meta"):
        got = request.headers.get("X-API-Token") or request.query_params.get("token") or ""
        if got != token:
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    return await call_next(request)


# ---------- models ----------


class InterceptBody(BaseModel):
    url: str = Field(..., description="视频链接")
    country: str = ""
    industry: str = ""
    keywords: str = ""
    max_comments: int = 200
    only_with_contact: bool = True


class KeywordBody(BaseModel):
    keyword: str
    max_videos: int = 3
    max_comments: int = 100
    country: str = ""
    industry: str = ""
    only_with_contact: bool = True


class PasteBody(BaseModel):
    text: str
    platform: str = "manual"
    video_url: str = ""
    country: str = ""
    industry: str = ""
    only_with_contact: bool = True


class BatchUrlsBody(BaseModel):
    urls: list[str]
    country: str = ""
    industry: str = ""
    max_comments: int = 150
    only_with_contact: bool = True


class SearchWebBody(BaseModel):
    keyword: str
    country_code: str = ""
    industry: str = ""
    max_sites: int = 10
    want_whatsapp: bool = True


class ImportTextBody(BaseModel):
    text: str
    country: str = ""
    industry: str = ""


class LeadUpdate(BaseModel):
    company: Optional[str] = None
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    business_type: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    score: Optional[int] = None
    tags: Optional[str] = None
    keywords: Optional[str] = None


class CookiesBody(BaseModel):
    content: str


class MapsBody(BaseModel):
    keyword: str = Field(..., description="商户/品类关键词，如 furniture / restaurant")
    country_code: str = ""
    city: str = ""
    limit: int = 25
    radius: Optional[int] = None


class DirectoryBody(BaseModel):
    keyword: str
    country_code: str = ""
    industry: str = ""
    city: str = ""
    max_sites: int = 12


class B2BBody(BaseModel):
    keyword: str
    country_code: str = ""
    city: str = ""
    max_sites: int = 12


class DomainsBody(BaseModel):
    domains: list[str]
    country: str = ""
    industry: str = ""
    keywords: str = ""


class EmailGenBody(BaseModel):
    companies: list[str] = Field(..., description="公司名或域名，一行一个")
    country: str = ""
    industry: str = ""
    max_locals: int = 8
    verify_mx: bool = True


class RawTextBody(BaseModel):
    text: str
    country: str = ""
    industry: str = ""
    source: str = "raw_text"


class ComboBody(BaseModel):
    keyword: str
    country_code: str = ""
    city: str = ""
    industry: str = ""
    use_maps: bool = True
    use_directory: bool = True
    use_b2b: bool = True
    max_per_source: int = 10


# ---------- pages ----------


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = (
        __import__("pathlib").Path(__file__).resolve().parent.parent / "static" / "index.html"
    )
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/meta")
async def api_meta():
    s = get_settings()
    return {
        "ok": True,
        **app_meta(),
        "features": s.get("features") or {},
        "scrape": {
            "require_contact": (s.get("scrape") or {}).get("require_contact", True),
        },
        "deploy": {
            "host": s["server"]["host"],
            "port": s["server"]["port"],
            "data_dir": s["data"]["dir"],
        },
    }


# ---------- 评论截流 ----------


@app.post("/api/intercept/video")
async def api_intercept_video(body: InterceptBody):
    if not body.url.strip():
        raise HTTPException(400, "请填写视频链接")
    result = ci.intercept_video(
        url=body.url.strip(),
        country=body.country,
        industry=body.industry,
        keywords=body.keywords,
        max_comments=min(max(body.max_comments, 10), 500),
        only_with_contact=body.only_with_contact,
        save=True,
    )
    return result


@app.post("/api/intercept/keyword")
async def api_intercept_keyword(body: KeywordBody):
    if not body.keyword.strip():
        raise HTTPException(400, "请填写关键词")
    result = ci.intercept_keyword_youtube(
        keyword=body.keyword.strip(),
        max_videos=min(max(body.max_videos, 1), 8),
        max_comments=min(max(body.max_comments, 20), 300),
        country=body.country,
        industry=body.industry,
        only_with_contact=body.only_with_contact,
    )
    return result


@app.post("/api/intercept/paste")
async def api_intercept_paste(body: PasteBody):
    if not body.text.strip():
        raise HTTPException(400, "请粘贴评论内容")
    return ci.parse_pasted_comments(
        text=body.text,
        platform=body.platform or "manual",
        video_url=body.video_url,
        country=body.country,
        industry=body.industry,
        only_with_contact=body.only_with_contact,
        save=True,
    )


@app.post("/api/intercept/batch")
async def api_intercept_batch(body: BatchUrlsBody):
    urls = [u.strip() for u in body.urls if u and u.strip()]
    if not urls:
        raise HTTPException(400, "请至少提供一个视频链接")
    results = []
    total = 0
    for u in urls[:15]:
        r = ci.intercept_video(
            url=u,
            country=body.country,
            industry=body.industry,
            max_comments=body.max_comments,
            only_with_contact=body.only_with_contact,
            save=True,
        )
        total += r.get("leads_saved") or 0
        results.append(
            {
                "url": u,
                "ok": r.get("ok"),
                "platform": r.get("platform"),
                "title": (r.get("video") or {}).get("title"),
                "comments_total": r.get("comments_total") or 0,
                "leads_saved": r.get("leads_saved") or 0,
                "error": r.get("error"),
                "warning": r.get("warning"),
            }
        )
    return {"ok": True, "total_leads_saved": total, "results": results}


@app.get("/api/platforms")
async def api_platforms():
    return {
        "platforms": [
            {
                "id": "youtube",
                "name": "YouTube",
                "support": "高",
                "tip": "直接粘贴视频链接即可拉评论；也可用关键词搜索热门视频批量截流",
            },
            {
                "id": "tiktok",
                "name": "TikTok",
                "support": "中（建议 cookies）",
                "tip": "公开视频可试；失败时导出浏览器 cookies.txt 上传，或手动复制评论粘贴",
            },
            {
                "id": "instagram",
                "name": "Instagram",
                "support": "中低（需登录）",
                "tip": "强烈建议配置 cookies，或用「粘贴评论」模式",
            },
            {
                "id": "facebook",
                "name": "Facebook",
                "support": "中低",
                "tip": "公开 fb.watch / 公开视频可试；否则 cookies 或粘贴评论",
            },
        ],
        "countries": [
            {"code": k, **v} for k, v in hunter.COUNTRY_MAP.items()
        ],
    }


@app.post("/api/cookies")
async def api_save_cookies(body: CookiesBody):
    path = ci.save_cookies_file(body.content)
    return {"ok": True, "path": path, "size": len(body.content or "")}


@app.get("/api/cookies/status")
async def api_cookies_status():
    p = ci.cookies_path()
    exists = p.exists() and p.stat().st_size > 10
    return {
        "configured": exists,
        "path": str(p),
        "size": p.stat().st_size if p.exists() else 0,
    }


# ---------- 网页获客（前期模块） ----------


@app.post("/api/hunt/web")
async def api_hunt_web(body: SearchWebBody):
    result = await hunter.run_search(
        keyword=body.keyword,
        country_code=body.country_code,
        industry=body.industry,
        max_sites=min(max(body.max_sites, 3), 20),
        want_whatsapp=body.want_whatsapp,
    )
    return result


@app.post("/api/hunt/urls")
async def api_hunt_urls(body: BatchUrlsBody):
    result = await hunter.harvest_urls(
        urls=body.urls,
        country=body.country,
        industry=body.industry,
    )
    return result


@app.post("/api/hunt/import")
async def api_hunt_import(body: ImportTextBody):
    leads = hunter.parse_import_text(body.text, body.country, body.industry)
    saved = 0
    out = []
    for lead in leads:
        lid = db.upsert_lead(lead, require_contact=True)
        if lid:
            lead["id"] = lid
            saved += 1
            out.append(lead)
    return {"ok": True, "leads_found": len(leads), "leads_saved": saved, "leads": out[:50]}


# ---------- 多源客户数据爬取 ----------


@app.get("/api/scrape/sources")
async def api_scrape_sources():
    return {"sources": ms.list_sources(), "cities": sorted(ms.CITY_CENTER.keys())}


@app.post("/api/scrape/maps")
async def api_scrape_maps(body: MapsBody):
    if not body.keyword.strip():
        raise HTTPException(400, "请填写关键词")
    return await ms.scrape_osm_places(
        keyword=body.keyword.strip(),
        country_code=body.country_code,
        city=body.city,
        limit=min(max(body.limit, 5), 50),
        radius=body.radius,
    )


@app.post("/api/scrape/directory")
async def api_scrape_directory(body: DirectoryBody):
    if not body.keyword.strip():
        raise HTTPException(400, "请填写关键词")
    return await ms.scrape_directory(
        keyword=body.keyword.strip(),
        country_code=body.country_code,
        industry=body.industry,
        city=body.city,
        max_sites=min(max(body.max_sites, 3), 20),
    )


@app.post("/api/scrape/b2b")
async def api_scrape_b2b(body: B2BBody):
    if not body.keyword.strip():
        raise HTTPException(400, "请填写关键词")
    return await ms.scrape_b2b_buyers(
        keyword=body.keyword.strip(),
        country_code=body.country_code,
        city=body.city,
        max_sites=min(max(body.max_sites, 3), 20),
    )


@app.post("/api/scrape/domains")
async def api_scrape_domains(body: DomainsBody):
    if not body.domains:
        raise HTTPException(400, "请提供至少一个域名")
    return await ms.scrape_domains(
        domains=body.domains,
        country=body.country,
        industry=body.industry,
        keywords=body.keywords,
    )


@app.post("/api/scrape/email-gen")
async def api_scrape_email_gen(body: EmailGenBody):
    if not body.companies:
        raise HTTPException(400, "请提供公司名或域名")
    return await ms.generate_emails(
        companies=body.companies,
        country=body.country,
        industry=body.industry,
        max_locals=body.max_locals,
        verify_mx=body.verify_mx,
    )


@app.post("/api/scrape/raw")
async def api_scrape_raw(body: RawTextBody):
    if not body.text.strip():
        raise HTTPException(400, "请粘贴文本")
    return ms.scrape_raw_text(
        text=body.text,
        country=body.country,
        industry=body.industry,
        source=body.source or "raw_text",
    )


@app.post("/api/scrape/combo")
async def api_scrape_combo(body: ComboBody):
    if not body.keyword.strip():
        raise HTTPException(400, "请填写关键词")
    return await ms.scrape_combo(
        keyword=body.keyword.strip(),
        country_code=body.country_code,
        city=body.city,
        industry=body.industry,
        use_maps=body.use_maps,
        use_directory=body.use_directory,
        use_b2b=body.use_b2b,
        max_per_source=min(max(body.max_per_source, 3), 20),
    )


# ---------- 线索库 ----------


@app.get("/api/leads")
async def api_list_leads(
    q: str = "",
    country: str = "",
    industry: str = "",
    status: str = "",
    has_email: Optional[bool] = None,
    has_whatsapp: Optional[bool] = None,
    has_contact: Optional[bool] = None,
    contact_mode: str = Query("reachable"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    # contact_mode: reachable=只要能联系 | all=全部 | none=只要不能联系
    if has_contact is None:
        if contact_mode == "all":
            has_contact = None
        elif contact_mode == "none":
            has_contact = False
        else:
            has_contact = True
    rows, total = db.list_leads(
        q=q,
        country=country,
        industry=industry,
        status=status,
        has_email=has_email,
        has_whatsapp=has_whatsapp,
        has_contact=has_contact,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": rows, "limit": limit, "offset": offset}


@app.get("/api/leads/{lead_id}")
async def api_get_lead(lead_id: int):
    row = db.get_lead(lead_id)
    if not row:
        raise HTTPException(404, "线索不存在")
    return row


@app.patch("/api/leads/{lead_id}")
async def api_update_lead(lead_id: int, body: LeadUpdate):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    ok = db.update_lead_fields(lead_id, fields)
    if not ok:
        raise HTTPException(404, "更新失败")
    return db.get_lead(lead_id)


@app.delete("/api/leads/{lead_id}")
async def api_delete_lead(lead_id: int):
    if not db.delete_lead(lead_id):
        raise HTTPException(404, "线索不存在")
    return {"ok": True}


@app.get("/api/stats")
async def api_stats():
    return db.stats()


@app.get("/api/jobs")
async def api_jobs(limit: int = 20):
    return {"items": db.list_jobs(limit=limit)}


@app.post("/api/leads/purge-no-contact")
async def api_purge_no_contact():
    n = db.purge_no_contact()
    return {"ok": True, "deleted": n, "stats": db.stats()}


@app.get("/api/export.csv")
async def api_export_csv(
    country: str = "",
    industry: str = "",
    status: str = "",
    has_email: Optional[bool] = None,
    has_whatsapp: Optional[bool] = None,
    has_contact: Optional[bool] = None,
    contact_mode: str = "reachable",
):
    if has_contact is None:
        has_contact = None if contact_mode == "all" else True
    rows = db.export_rows(
        country=country,
        industry=industry,
        status=status,
        has_email=has_email,
        has_whatsapp=has_whatsapp,
        has_contact=has_contact,
    )
    buf = io.StringIO()
    fields = [
        "id",
        "company",
        "business_type",
        "contact_name",
        "contact_title",
        "description",
        "country",
        "city",
        "industry",
        "website",
        "email",
        "phone",
        "whatsapp",
        "linkedin",
        "source",
        "source_url",
        "keywords",
        "status",
        "score",
        "tags",
        "notes",
        "created_at",
        "updated_at",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in fields})
    data = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="leads_export.csv"'
        },
    )


@app.get("/api/health")
async def health():
    meta = app_meta()
    st = db.stats()
    return {
        "ok": True,
        "service": meta["name_zh"],
        "name": meta["name"],
        "version": meta["version"],
        "uptime_sec": int(time.time() - _BOOT),
        "leads_total": st.get("total", 0),
        "with_email": st.get("with_email", 0),
        "with_whatsapp": st.get("with_whatsapp", 0),
    }


# 静态资源（logo/未来扩展）
try:
    static_dir = __import__("pathlib").Path(__file__).resolve().parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
except Exception:
    pass
