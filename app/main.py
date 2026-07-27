"""
外贸获客台 · 社媒评论截流
FastAPI 主入口
"""
from __future__ import annotations

import csv
import io
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from . import comment_intercept as ci
from . import hunter

app = FastAPI(
    title="外贸获客台",
    description="社媒热门视频评论截流 · 多国线索 · 邮箱/WhatsApp",
    version="1.1.0",
)

db.init_db()


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


# ---------- pages ----------


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = (
        __import__("pathlib").Path(__file__).resolve().parent.parent / "static" / "index.html"
    )
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


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
    for lead in leads:
        db.upsert_lead(lead)
        saved += 1
    return {"ok": True, "leads_found": len(leads), "leads_saved": saved, "leads": leads[:50]}


# ---------- 线索库 ----------


@app.get("/api/leads")
async def api_list_leads(
    q: str = "",
    country: str = "",
    industry: str = "",
    status: str = "",
    has_email: Optional[bool] = None,
    has_whatsapp: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows, total = db.list_leads(
        q=q,
        country=country,
        industry=industry,
        status=status,
        has_email=has_email,
        has_whatsapp=has_whatsapp,
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


@app.get("/api/export.csv")
async def api_export_csv(
    country: str = "",
    industry: str = "",
    status: str = "",
    has_email: Optional[bool] = None,
    has_whatsapp: Optional[bool] = None,
):
    rows = db.export_rows(
        country=country,
        industry=industry,
        status=status,
        has_email=has_email,
        has_whatsapp=has_whatsapp,
    )
    buf = io.StringIO()
    fields = [
        "id",
        "company",
        "contact_name",
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
    return {"ok": True, "service": "外贸获客台", "version": "1.1.0"}
