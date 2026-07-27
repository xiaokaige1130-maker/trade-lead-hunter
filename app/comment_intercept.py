"""
社媒热门视频评论截流

支持：
- YouTube：yt-dlp 拉评论（最稳）
- TikTok / Instagram / Facebook：优先 yt-dlp；失败则用公开页/oEmbed 降级提示
- 从评论中提取：邮箱、WhatsApp、Telegram、电话、外链
- 线索入库 + 按视频/平台统计

用途：外贸/B2B 从热门视频评论区截流留资（公开评论中的联系方式）。
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from . import db
from .extractor import (
    extract_emails,
    extract_phones,
    extract_whatsapps,
    score_lead,
)

YT_DLP = str(Path(__file__).resolve().parent.parent / ".venv" / "bin" / "yt-dlp")
if not Path(YT_DLP).exists():
    YT_DLP = "yt-dlp"

# 评论里常见社媒/即时通讯
TELEGRAM_RE = re.compile(
    r"(?i)(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{4,32})"
)
IG_HANDLE_RE = re.compile(r"(?:^|[\s(@])@([A-Za-z0-9._]{2,30})\b")
URL_RE = re.compile(r"https?://[^\s<>\"']{6,200}")

PLATFORM_PATTERNS = {
    "youtube": [
        r"(?:youtube\.com|youtu\.be)",
    ],
    "tiktok": [
        r"tiktok\.com",
        r"vm\.tiktok\.com",
    ],
    "instagram": [
        r"instagram\.com",
    ],
    "facebook": [
        r"facebook\.com",
        r"fb\.watch",
        r"fb\.com",
    ],
}


def detect_platform(url: str) -> str:
    u = (url or "").lower()
    for plat, pats in PLATFORM_PATTERNS.items():
        for p in pats:
            if re.search(p, u):
                return plat
    return "unknown"


def normalize_video_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    # 去掉多余追踪参数（保留 v=）
    try:
        p = urlparse(url)
        if "youtube.com" in p.netloc and p.path == "/watch":
            qs = parse_qs(p.query)
            vid = (qs.get("v") or [""])[0]
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
        if "youtu.be" in p.netloc:
            vid = p.path.strip("/").split("/")[0]
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
    except Exception:
        pass
    return url


def extract_contacts_from_text(text: str) -> dict[str, Any]:
    text = text or ""
    emails = extract_emails(text)
    whatsapps = extract_whatsapps(text, text)
    phones = extract_phones(text)
    telegrams = list(dict.fromkeys(TELEGRAM_RE.findall(text)))
    urls = list(dict.fromkeys(URL_RE.findall(text)))
    # 过滤平台自身链接
    urls = [
        u
        for u in urls
        if not re.search(
            r"(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)",
            u,
            re.I,
        )
    ]
    handles = list(dict.fromkeys(IG_HANDLE_RE.findall(text)))
    has_contact = bool(emails or whatsapps or telegrams or phones)
    return {
        "emails": emails,
        "email": emails[0] if emails else "",
        "whatsapps": whatsapps,
        "whatsapp": whatsapps[0] if whatsapps else "",
        "phones": phones,
        "phone": phones[0] if phones else "",
        "telegrams": telegrams,
        "telegram": telegrams[0] if telegrams else "",
        "urls": urls[:5],
        "handles": handles[:5],
        "has_contact": has_contact,
    }


def _run_ytdlp_json(url: str, extra_args: list[str] | None = None, timeout: int = 120) -> dict:
    """调用 yt-dlp 输出 info json（含评论）。"""
    args = [
        YT_DLP,
        "--skip-download",
        "--no-warnings",
        "--no-check-certificates",
        "-J",
        * (extra_args or []),
        url,
    ]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"yt-dlp 超时（>{timeout}s）：{url}")
    if proc.returncode != 0 and not proc.stdout.strip():
        err = (proc.stderr or proc.stdout or "unknown error")[-800:]
        raise RuntimeError(f"yt-dlp 失败: {err}")
    raw = proc.stdout.strip()
    if not raw:
        raise RuntimeError(f"yt-dlp 无输出: {(proc.stderr or '')[-500:]}")
    # 有时是多行 JSON（playlist），取第一个对象
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 尝试逐行
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except Exception:
                    continue
        raise RuntimeError("无法解析 yt-dlp JSON 输出")


def fetch_video_with_comments(
    url: str,
    max_comments: int = 200,
    timeout: int = 150,
) -> dict[str, Any]:
    """
    拉取视频元数据 + 评论。
    YouTube 对 --write-comments 支持最好。
    """
    url = normalize_video_url(url)
    platform = detect_platform(url)

    extra = [
        "--write-comments",
        # extractor args：限制评论数（YouTube）
        "--extractor-args",
        f"youtube:max_comments={max_comments},comment_sort=top",
    ]

    info = _run_ytdlp_json(url, extra_args=extra, timeout=timeout)
    comments_raw = info.get("comments") or []

    # 某些平台评论在其他字段
    if not comments_raw and isinstance(info.get("entries"), list):
        # playlist 取第一条
        for ent in info["entries"]:
            if ent and ent.get("comments"):
                info = ent
                comments_raw = ent.get("comments") or []
                break

    comments: list[dict[str, Any]] = []
    for c in comments_raw[:max_comments]:
        if not isinstance(c, dict):
            continue
        text = c.get("text") or c.get("content") or ""
        if not text:
            continue
        comments.append(
            {
                "id": str(c.get("id") or c.get("comment_id") or ""),
                "author": c.get("author") or c.get("user") or c.get("author_id") or "",
                "author_id": str(c.get("author_id") or c.get("user_id") or ""),
                "text": text,
                "like_count": c.get("like_count") or c.get("likes") or 0,
                "timestamp": c.get("timestamp") or c.get("time") or "",
                "parent": c.get("parent") or "",
            }
        )

    return {
        "platform": platform if platform != "unknown" else (info.get("extractor_key") or "unknown").lower(),
        "video_id": info.get("id") or "",
        "title": info.get("title") or "",
        "description": (info.get("description") or "")[:2000],
        "uploader": info.get("uploader") or info.get("creator") or info.get("channel") or "",
        "uploader_url": info.get("uploader_url") or info.get("channel_url") or "",
        "webpage_url": info.get("webpage_url") or url,
        "view_count": info.get("view_count") or 0,
        "like_count": info.get("like_count") or 0,
        "comment_count_meta": info.get("comment_count") or len(comments),
        "thumbnail": info.get("thumbnail") or "",
        "duration": info.get("duration") or 0,
        "comments": comments,
        "comment_count": len(comments),
    }


def comments_to_leads(
    video: dict[str, Any],
    country: str = "",
    industry: str = "",
    keywords: str = "",
    only_with_contact: bool = True,
) -> list[dict[str, Any]]:
    """把评论转成线索；默认只保留含联系方式的评论。"""
    leads: list[dict[str, Any]] = []
    platform = video.get("platform") or ""
    video_url = video.get("webpage_url") or ""
    title = video.get("title") or ""

    # 视频简介也可能有联系方式（创作者）
    desc_contacts = extract_contacts_from_text(video.get("description") or "")
    if desc_contacts["has_contact"]:
        leads.append(
            {
                "company": (video.get("uploader") or "视频作者")[:80],
                "contact_name": video.get("uploader") or "",
                "country": country,
                "industry": industry,
                "website": video.get("uploader_url") or video_url,
                "email": desc_contacts["email"],
                "emails": desc_contacts["emails"],
                "phone": desc_contacts["phone"],
                "phones": desc_contacts["phones"],
                "whatsapp": desc_contacts["whatsapp"],
                "whatsapps": desc_contacts["whatsapps"],
                "linkedin": "",
                "source": f"{platform}_video_desc",
                "source_url": video_url,
                "keywords": keywords or title[:60],
                "notes": f"[视频简介截流] {title}\nTG:{','.join(desc_contacts['telegrams'])}\nURLs:{','.join(desc_contacts['urls'])}",
                "score": score_lead(
                    desc_contacts["emails"],
                    desc_contacts["whatsapps"],
                    desc_contacts["phones"],
                    video_url,
                    video.get("uploader") or "",
                )
                + 5,
                "status": "new",
                "tags": f"{platform},video_desc",
                "meta": {
                    "telegram": desc_contacts["telegram"],
                    "from": "description",
                },
            }
        )

    for c in video.get("comments") or []:
        text = c.get("text") or ""
        contacts = extract_contacts_from_text(text)
        if only_with_contact and not contacts["has_contact"]:
            continue
        if not only_with_contact and not text.strip():
            continue

        author = (c.get("author") or "匿名评论").strip()[:80]
        note_parts = [
            f"[评论截流] 平台:{platform}",
            f"视频:{title[:80]}",
            f"作者/评论人:{author}",
            f"评论:{text[:500]}",
        ]
        if contacts["telegrams"]:
            note_parts.append("Telegram: " + ", ".join(contacts["telegrams"]))
        if contacts["urls"]:
            note_parts.append("链接: " + ", ".join(contacts["urls"]))
        if contacts["handles"]:
            note_parts.append("Handles: " + ", ".join("@" + h for h in contacts["handles"]))

        score = score_lead(
            contacts["emails"],
            contacts["whatsapps"],
            contacts["phones"],
            "",
            author,
        )
        if contacts["telegrams"]:
            score = min(100, score + 20)
        if not contacts["has_contact"]:
            score = max(score, 5)  # 无联系方式的纯评论，低分保留（可选）

        lead = {
            "company": author,
            "contact_name": author,
            "country": country,
            "industry": industry,
            "website": video_url,
            "email": contacts["email"],
            "emails": contacts["emails"],
            "phone": contacts["phone"],
            "phones": contacts["phones"],
            "whatsapp": contacts["whatsapp"],
            "whatsapps": contacts["whatsapps"],
            "linkedin": "",
            "source": f"{platform}_comment",
            "source_url": video_url,
            "keywords": keywords or title[:60],
            "notes": "\n".join(note_parts),
            "score": score,
            "status": "new",
            "tags": f"{platform},comment" + (",hot" if (c.get("like_count") or 0) >= 10 else ""),
            "meta": {
                "comment_id": c.get("id"),
                "like_count": c.get("like_count") or 0,
                "telegram": contacts["telegram"],
                "handles": contacts["handles"],
                "urls": contacts["urls"],
                "has_contact": contacts["has_contact"],
                "raw_text": text[:1000],
            },
        }
        leads.append(lead)

    return leads


def intercept_video(
    url: str,
    country: str = "",
    industry: str = "",
    keywords: str = "",
    max_comments: int = 200,
    only_with_contact: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """
    单视频评论截流主入口。
    返回：视频信息 + 评论 + 线索 + 入库数量
    """
    url = normalize_video_url(url)
    platform = detect_platform(url)
    job_id = db.create_job(
        query=f"comment_intercept:{platform}:{url[:80]}",
        country=country,
        industry=industry or platform,
    )

    try:
        video = fetch_video_with_comments(url, max_comments=max_comments)
        # 若 yt-dlp 没拿到评论，标记原因
        warning = ""
        if video["comment_count"] == 0:
            warning = (
                f"{video.get('platform') or platform} 未拉到评论。"
                "YouTube 最稳；TikTok/INS/FB 常需登录 Cookie 或风控更严。"
                "可在设置里配置 cookies 文件后重试。"
            )

        leads = comments_to_leads(
            video,
            country=country,
            industry=industry,
            keywords=keywords,
            only_with_contact=only_with_contact,
        )

        saved_ids = []
        if save:
            for lead in leads:
                meta = lead.pop("meta", {}) or {}
                has_c = bool(
                    lead.get("email")
                    or lead.get("whatsapp")
                    or lead.get("phone")
                    or meta.get("telegram")
                )
                if only_with_contact and not has_c:
                    continue
                # 无联系方式的纯评论：写入 notes 便于分析，但不强行堆重复空记录
                try:
                    lid = db.upsert_lead(lead)
                except Exception as ex:
                    # 单条失败不中断整视频
                    continue
                lead["id"] = lid
                lead["meta"] = meta
                saved_ids.append(lid)

        db.finish_job(job_id, result_count=len(saved_ids))
        return {
            "ok": True,
            "job_id": job_id,
            "platform": video.get("platform") or platform,
            "video": {
                "id": video.get("video_id"),
                "title": video.get("title"),
                "uploader": video.get("uploader"),
                "url": video.get("webpage_url"),
                "view_count": video.get("view_count"),
                "comment_count": video.get("comment_count"),
                "comment_count_meta": video.get("comment_count_meta"),
                "thumbnail": video.get("thumbnail"),
            },
            "comments_total": video.get("comment_count") or 0,
            "comments_sample": (video.get("comments") or [])[:30],
            "leads_found": len(leads),
            "leads_saved": len(saved_ids),
            "leads": leads[:100],
            "warning": warning,
        }
    except Exception as e:
        db.finish_job(job_id, result_count=0, error=str(e))
        return {
            "ok": False,
            "job_id": job_id,
            "platform": platform,
            "error": str(e),
            "hint": _platform_hint(platform),
            "leads_found": 0,
            "leads_saved": 0,
            "leads": [],
        }


def _platform_hint(platform: str) -> str:
    hints = {
        "youtube": "YouTube 一般可直接拉评论。若失败：检查网络/换视频链接。",
        "tiktok": "TikTok 评论常需 cookies.txt（浏览器登录后导出）才能稳定获取。",
        "instagram": "Instagram 需登录态；建议导出 cookies 或改用公开网页+手动粘贴评论。",
        "facebook": "Facebook 视频评论限制多；可试 fb.watch 公开链接，或配置 cookies。",
        "unknown": "请粘贴完整视频链接（YouTube / TikTok / Instagram / Facebook）。",
    }
    return hints.get(platform, hints["unknown"])


def search_youtube_videos(keyword: str, max_results: int = 5) -> list[dict[str, str]]:
    """用 yt-dlp 搜索 YouTube 热门相关视频（ytsearch）。"""
    query = f"ytsearch{max_results}:{keyword}"
    try:
        info = _run_ytdlp_json(query, extra_args=["--flat-playlist"], timeout=60)
    except Exception:
        return []
    entries = info.get("entries") or []
    out = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id") or ""
        title = e.get("title") or ""
        url = e.get("url") or e.get("webpage_url") or ""
        if vid and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={vid}"
        if url:
            out.append(
                {
                    "id": vid,
                    "title": title,
                    "url": url,
                    "uploader": e.get("uploader") or e.get("channel") or "",
                    "platform": "youtube",
                }
            )
    return out


def intercept_keyword_youtube(
    keyword: str,
    max_videos: int = 3,
    max_comments: int = 100,
    country: str = "",
    industry: str = "",
    only_with_contact: bool = True,
) -> dict[str, Any]:
    """搜索关键词相关 YouTube 视频并批量截流评论。"""
    videos = search_youtube_videos(keyword, max_results=max_videos)
    results = []
    total_leads = 0
    for v in videos:
        r = intercept_video(
            v["url"],
            country=country,
            industry=industry,
            keywords=keyword,
            max_comments=max_comments,
            only_with_contact=only_with_contact,
            save=True,
        )
        total_leads += r.get("leads_saved") or 0
        results.append(
            {
                "url": v["url"],
                "title": v.get("title") or r.get("video", {}).get("title"),
                "ok": r.get("ok"),
                "comments_total": r.get("comments_total") or 0,
                "leads_saved": r.get("leads_saved") or 0,
                "error": r.get("error"),
            }
        )
    return {
        "ok": True,
        "keyword": keyword,
        "videos_scanned": len(videos),
        "total_leads_saved": total_leads,
        "results": results,
    }


def parse_pasted_comments(
    text: str,
    platform: str = "manual",
    video_url: str = "",
    country: str = "",
    industry: str = "",
    only_with_contact: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """
    手动粘贴评论区文本（任意平台复制）→ 提取联系方式入库。
    当自动爬取被风控时，这是最稳的降级方案。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    # 也按空行分块（有的复制是块状）
    blocks: list[str] = []
    if len(lines) >= 3:
        blocks = lines
    else:
        blocks = re.split(r"\n\s*\n", text or "")
        blocks = [b.strip() for b in blocks if b.strip()]

    fake_comments = []
    for i, b in enumerate(blocks):
        fake_comments.append(
            {
                "id": f"paste-{i}",
                "author": "",
                "text": b,
                "like_count": 0,
            }
        )

    video = {
        "platform": platform or "manual",
        "title": "手动粘贴评论",
        "webpage_url": video_url or "",
        "uploader": "",
        "description": "",
        "comments": fake_comments,
    }
    leads = comments_to_leads(
        video,
        country=country,
        industry=industry,
        keywords="pasted_comments",
        only_with_contact=only_with_contact,
    )
    # 对整段再扫一次（防止分行切断邮箱）
    whole = extract_contacts_from_text(text)
    if whole["emails"] or whole["whatsapps"] or whole["telegrams"]:
        # 补漏：整段出现但分行没抓全的
        existing_emails = {l.get("email") for l in leads}
        for e in whole["emails"]:
            if e not in existing_emails:
                leads.append(
                    {
                        "company": e.split("@")[-1].split(".")[0].title(),
                        "email": e,
                        "emails": [e],
                        "whatsapp": whole["whatsapp"],
                        "whatsapps": whole["whatsapps"],
                        "phone": whole["phone"],
                        "phones": whole["phones"],
                        "country": country,
                        "industry": industry,
                        "source": f"{platform}_paste",
                        "source_url": video_url,
                        "keywords": "pasted_comments",
                        "notes": f"[粘贴评论整段提取]\n{text[:300]}",
                        "score": score_lead([e], whole["whatsapps"], whole["phones"]),
                        "status": "new",
                        "tags": f"{platform},paste",
                    }
                )

    saved = 0
    if save:
        for lead in leads:
            lead.pop("meta", None)
            lid = db.upsert_lead(lead)
            lead["id"] = lid
            saved += 1

    return {
        "ok": True,
        "blocks": len(blocks),
        "leads_found": len(leads),
        "leads_saved": saved,
        "leads": leads[:100],
    }


# ---------- Cookie 支持（提升 TK/INS/FB 成功率）----------

def cookies_path() -> Path:
    p = Path(__file__).resolve().parent.parent / "data" / "cookies.txt"
    return p


def save_cookies_file(content: str) -> str:
    path = cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")
    return str(path)


def ytdlp_with_cookies_args() -> list[str]:
    path = cookies_path()
    if path.exists() and path.stat().st_size > 10:
        return ["--cookies", str(path)]
    return []


# 给 fetch 打补丁：自动带 cookies
_orig_run = _run_ytdlp_json


def _run_ytdlp_json_with_cookies(url: str, extra_args: list[str] | None = None, timeout: int = 120) -> dict:
    extra = list(extra_args or [])
    extra = ytdlp_with_cookies_args() + extra
    return _orig_run(url, extra_args=extra, timeout=timeout)


# 替换模块内调用
_run_ytdlp_json = _run_ytdlp_json_with_cookies  # type: ignore
