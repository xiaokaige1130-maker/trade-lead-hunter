"""
公开信息获客引擎

数据来源（均可公开访问，无需付费 API Key）：
1. DuckDuckGo HTML 搜索 — 发现目标国家/行业公司官网与目录页
2. 网站首页 / contact / about 页抓取 — 提取邮箱、WhatsApp、电话
3. 用户手动粘贴网址批量提取
4. CSV / 文本导入

说明：仅采集公开网页上主动展示的联系方式，用于合法 B2B 商务拓展。
请遵守目标站 robots 与当地反垃圾邮件法规（如 GDPR/CAN-SPAM），并做好退订与合规。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from . import db
from .extractor import extract_from_page, score_lead
from .profile import build_profile, has_reachable_contact

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 TradeLeadHunter/1.0"
)

# 国家 → 搜索用英文名 / 本地提示
COUNTRY_MAP: dict[str, dict[str, str]] = {
    "US": {"name": "United States", "name_zh": "美国", "tld": ".com"},
    "GB": {"name": "United Kingdom", "name_zh": "英国", "tld": ".co.uk"},
    "DE": {"name": "Germany", "name_zh": "德国", "tld": ".de"},
    "FR": {"name": "France", "name_zh": "法国", "tld": ".fr"},
    "IT": {"name": "Italy", "name_zh": "意大利", "tld": ".it"},
    "ES": {"name": "Spain", "name_zh": "西班牙", "tld": ".es"},
    "NL": {"name": "Netherlands", "name_zh": "荷兰", "tld": ".nl"},
    "PL": {"name": "Poland", "name_zh": "波兰", "tld": ".pl"},
    "AE": {"name": "United Arab Emirates", "name_zh": "阿联酋", "tld": ".ae"},
    "SA": {"name": "Saudi Arabia", "name_zh": "沙特", "tld": ".sa"},
    "AU": {"name": "Australia", "name_zh": "澳大利亚", "tld": ".au"},
    "CA": {"name": "Canada", "name_zh": "加拿大", "tld": ".ca"},
    "MX": {"name": "Mexico", "name_zh": "墨西哥", "tld": ".mx"},
    "BR": {"name": "Brazil", "name_zh": "巴西", "tld": ".br"},
    "IN": {"name": "India", "name_zh": "印度", "tld": ".in"},
    "JP": {"name": "Japan", "name_zh": "日本", "tld": ".jp"},
    "KR": {"name": "South Korea", "name_zh": "韩国", "tld": ".kr"},
    "SG": {"name": "Singapore", "name_zh": "新加坡", "tld": ".sg"},
    "MY": {"name": "Malaysia", "name_zh": "马来西亚", "tld": ".my"},
    "TH": {"name": "Thailand", "name_zh": "泰国", "tld": ".th"},
    "VN": {"name": "Vietnam", "name_zh": "越南", "tld": ".vn"},
    "ID": {"name": "Indonesia", "name_zh": "印尼", "tld": ".id"},
    "PH": {"name": "Philippines", "name_zh": "菲律宾", "tld": ".ph"},
    "TR": {"name": "Turkey", "name_zh": "土耳其", "tld": ".tr"},
    "RU": {"name": "Russia", "name_zh": "俄罗斯", "tld": ".ru"},
    "ZA": {"name": "South Africa", "name_zh": "南非", "tld": ".za"},
    "NG": {"name": "Nigeria", "name_zh": "尼日利亚", "tld": ".ng"},
    "EG": {"name": "Egypt", "name_zh": "埃及", "tld": ".eg"},
    "NZ": {"name": "New Zealand", "name_zh": "新西兰", "tld": ".nz"},
    "SE": {"name": "Sweden", "name_zh": "瑞典", "tld": ".se"},
    "CH": {"name": "Switzerland", "name_zh": "瑞士", "tld": ".ch"},
    "BE": {"name": "Belgium", "name_zh": "比利时", "tld": ".be"},
    "AT": {"name": "Austria", "name_zh": "奥地利", "tld": ".at"},
    "PT": {"name": "Portugal", "name_zh": "葡萄牙", "tld": ".pt"},
    "IE": {"name": "Ireland", "name_zh": "爱尔兰", "tld": ".ie"},
    "CL": {"name": "Chile", "name_zh": "智利", "tld": ".cl"},
    "CO": {"name": "Colombia", "name_zh": "哥伦比亚", "tld": ".co"},
    "AR": {"name": "Argentina", "name_zh": "阿根廷", "tld": ".ar"},
    "PE": {"name": "Peru", "name_zh": "秘鲁", "tld": ".pe"},
}

INDUSTRY_PRESETS = [
    "importer",
    "wholesaler",
    "distributor",
    "retailer",
    "manufacturer",
    "trading company",
    "supermarket",
    "hotel supplier",
    "construction company",
    "furniture store",
    "auto parts",
    "electronics distributor",
    "beauty supply",
    "hardware store",
    "agricultural equipment",
    "medical equipment",
    "packaging company",
    "food importer",
]

CONTACT_PATHS = [
    "",
    "/contact",
    "/contact-us",
    "/contactus",
    "/about",
    "/about-us",
    "/aboutus",
    "/en/contact",
    "/en/contact-us",
    "/company/contact",
    "/pages/contact",
    "/support",
    "/get-in-touch",
]


def build_queries(
    keyword: str,
    country_code: str = "",
    industry: str = "",
    want_whatsapp: bool = True,
) -> list[str]:
    """构造多组搜索词，提高命中公开联系方式的概率。"""
    country_name = ""
    if country_code and country_code.upper() in COUNTRY_MAP:
        country_name = COUNTRY_MAP[country_code.upper()]["name"]
    elif country_code:
        country_name = country_code

    base_parts = [keyword.strip()]
    if industry:
        base_parts.append(industry.strip())
    if country_name:
        base_parts.append(country_name)
    base = " ".join(p for p in base_parts if p)

    queries = [
        f'{base} contact email',
        f'{base} "contact us" email',
        f'{base} importer email',
        f'{base} wholesale email',
    ]
    if want_whatsapp:
        queries.extend(
            [
                f'{base} whatsapp',
                f'{base} "whatsapp" contact',
                f'{base} wa.me',
            ]
        )
    if country_name:
        queries.append(f'{keyword} {industry} {country_name} directory email'.strip())
    # 去重
    return list(dict.fromkeys(q for q in queries if q.strip()))


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=10.0),
        verify=True,
    )


async def duckduckgo_search(query: str, max_results: int = 15) -> list[dict[str, str]]:
    """通过 DuckDuckGo HTML 版获取搜索结果（公开网页，无需 API Key）。"""
    results: list[dict[str, str]] = []
    url = "https://html.duckduckgo.com/html/"
    async with await _client() as client:
        try:
            resp = await client.post(url, data={"q": query, "b": ""})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.select("a.result__a"):
                href = a.get("href") or ""
                title = a.get_text(" ", strip=True)
                if not href or not title:
                    continue
                # DDG 有时包一层 redirect
                if "uddg=" in href:
                    from urllib.parse import parse_qs, urlparse as up

                    qs = parse_qs(up(href).query)
                    if "uddg" in qs:
                        href = qs["uddg"][0]
                if not href.startswith("http"):
                    continue
                host = urlparse(href).netloc.lower()
                if any(
                    x in host
                    for x in (
                        "duckduckgo.com",
                        "youtube.com",
                        "facebook.com",
                        "instagram.com",
                        "twitter.com",
                        "x.com",
                        "linkedin.com",
                        "pinterest.com",
                        "reddit.com",
                        "wikipedia.org",
                        "amazon.com",
                        "ebay.com",
                        "alibaba.com",
                        "made-in-china.com",
                    )
                ):
                    continue
                results.append({"title": title, "url": href})
                if len(results) >= max_results:
                    break
        except Exception:
            # 备用：GET 方式
            try:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                )
                soup = BeautifulSoup(resp.text, "lxml")
                for a in soup.select("a.result__a"):
                    href = a.get("href") or ""
                    title = a.get_text(" ", strip=True)
                    if href.startswith("http"):
                        results.append({"title": title, "url": href})
                    if len(results) >= max_results:
                        break
            except Exception:
                pass
    # URL 去重
    seen = set()
    uniq = []
    for r in results:
        key = urlparse(r["url"]).netloc + urlparse(r["url"]).path
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _same_site(base: str, link: str) -> bool:
    try:
        b = urlparse(base).netloc.lower().lstrip("www.")
        l = urlparse(link).netloc.lower().lstrip("www.")
        return b == l or (not l)
    except Exception:
        return False


async def fetch_page(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    """返回 (final_url, html)。失败返回 ("", "")。"""
    try:
        resp = await client.get(url)
        if resp.status_code >= 400:
            return "", ""
        ctype = resp.headers.get("content-type", "")
        if "text/html" not in ctype and "application/xhtml" not in ctype and ctype:
            # 有些站 content-type 不准，仍尝试
            if not resp.text or len(resp.text) < 50:
                return "", ""
        return str(resp.url), resp.text
    except Exception:
        return "", ""


async def harvest_site(
    client: httpx.AsyncClient,
    start_url: str,
    title: str = "",
    country: str = "",
    industry: str = "",
    keywords: str = "",
) -> Optional[dict[str, Any]]:
    """抓取官网及 contact 相关页，合并联系方式。"""
    parsed = urlparse(start_url)
    if not parsed.scheme.startswith("http"):
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"

    all_emails: list[str] = []
    all_phones: list[str] = []
    all_wa: list[str] = []
    linkedin = ""
    best_url = start_url
    company = title.split("-")[0].split("|")[0].strip()[:80] if title else ""

    paths = [start_url]
    for p in CONTACT_PATHS:
        if p:
            paths.append(urljoin(origin + "/", p.lstrip("/")))
    # 去重
    paths = list(dict.fromkeys(paths))[:8]

    for url in paths:
        final_url, html = await fetch_page(client, url)
        if not html:
            continue
        text = _html_to_text(html)
        info = extract_from_page(final_url or url, html, text)
        all_emails.extend(info["emails"])
        all_phones.extend(info["phones"])
        all_wa.extend(info["whatsapps"])
        if info.get("linkedin") and not linkedin:
            linkedin = info["linkedin"]
        if info.get("company") and (not company or len(info["company"]) > 2):
            if not company:
                company = info["company"]
        if info["emails"] or info["whatsapps"]:
            best_url = final_url or url

        # 从首页再挖一次 contact 内链
        if url == start_url or url.rstrip("/") == origin:
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                label = (a.get_text(" ", strip=True) or "").lower()
                full = urljoin(origin + "/", href)
                if not _same_site(origin, full):
                    continue
                if any(
                    k in label or k in href.lower()
                    for k in ("contact", "about", "support", "whatsapp", "get-in-touch")
                ):
                    if full not in paths and len(paths) < 12:
                        paths.append(full)

        await asyncio.sleep(0.35)  # 礼貌延迟

    all_emails = list(dict.fromkeys(all_emails))
    all_phones = list(dict.fromkeys(all_phones))
    all_wa = list(dict.fromkeys(all_wa))

    if not all_emails and not all_wa and not all_phones:
        return None

    if not company:
        from .extractor import guess_company_from_url

        company = guess_company_from_url(origin)

    email0 = all_emails[0] if all_emails else ""
    phone0 = all_phones[0] if all_phones else ""
    wa0 = all_wa[0] if all_wa else ""
    if not has_reachable_contact(email=email0, whatsapp=wa0, phone=phone0):
        return None

    # 用已抓正文拼画像（取最后一次 text 不够，用 notes 级摘要）
    prof = build_profile(
        company=company,
        keyword=keywords,
        industry=industry,
        email=email0,
        page_text=title or "",
        country=country,
        source="官网/网页",
    )

    return {
        "company": company,
        "contact_name": prof["contact_name"],
        "contact_title": prof["contact_title"],
        "business_type": prof["business_type"],
        "description": prof["description"],
        "country": country,
        "industry": industry or prof["industry"],
        "website": origin,
        "emails": all_emails,
        "email": email0,
        "phones": all_phones,
        "phone": phone0,
        "whatsapps": all_wa,
        "whatsapp": wa0,
        "linkedin": linkedin,
        "source": "web_search",
        "source_url": best_url,
        "keywords": keywords,
        "notes": f"[网页获客] {prof['description']}",
        "score": score_lead(all_emails, all_wa, all_phones, origin, company),
        "status": "new",
        "tags": "web,contact",
    }


async def run_search(
    keyword: str,
    country_code: str = "",
    industry: str = "",
    max_sites: int = 12,
    want_whatsapp: bool = True,
) -> dict[str, Any]:
    """
    完整搜索流水线：
    搜索 → 去重域名 → 逐站抓 contact → 入库
    """
    country_name = ""
    if country_code and country_code.upper() in COUNTRY_MAP:
        country_name = COUNTRY_MAP[country_code.upper()]["name_zh"]
        country_en = COUNTRY_MAP[country_code.upper()]["name"]
    else:
        country_en = country_code
        country_name = country_code

    job_id = db.create_job(
        query=f"{keyword} | {industry} | {country_code}",
        country=country_name or country_code,
        industry=industry,
    )

    queries = build_queries(keyword, country_code, industry, want_whatsapp)
    # 控制搜索次数，避免过慢
    queries = queries[:4]

    try:
        all_hits: list[dict[str, str]] = []
        for q in queries:
            hits = await duckduckgo_search(q, max_results=10)
            all_hits.extend(hits)
            await asyncio.sleep(0.8)

        # 按域名去重
        by_domain: dict[str, dict[str, str]] = {}
        for h in all_hits:
            dom = urlparse(h["url"]).netloc.lower().lstrip("www.")
            if not dom or dom in by_domain:
                continue
            by_domain[dom] = h

        sites = list(by_domain.values())[:max_sites]
        saved: list[dict] = []
        errors: list[str] = []

        async with await _client() as client:
            for hit in sites:
                try:
                    lead = await harvest_site(
                        client,
                        hit["url"],
                        title=hit.get("title") or "",
                        country=country_name or country_en,
                        industry=industry,
                        keywords=keyword,
                    )
                    if lead:
                        lid = db.upsert_lead(lead, require_contact=True)
                        if lid:
                            lead["id"] = lid
                            saved.append(lead)
                except Exception as e:
                    errors.append(f"{hit.get('url')}: {e}")
                await asyncio.sleep(0.4)

        db.finish_job(job_id, result_count=len(saved))
        return {
            "job_id": job_id,
            "queries": queries,
            "sites_scanned": len(sites),
            "leads_found": len(saved),
            "leads": saved,
            "errors": errors[:10],
        }
    except Exception as e:
        db.finish_job(job_id, result_count=0, error=str(e))
        return {
            "job_id": job_id,
            "queries": queries,
            "sites_scanned": 0,
            "leads_found": 0,
            "leads": [],
            "errors": [str(e)],
        }


async def harvest_urls(
    urls: list[str],
    country: str = "",
    industry: str = "",
    keywords: str = "",
) -> dict[str, Any]:
    """批量从用户提供的网址提取联系方式。"""
    saved = []
    async with await _client() as client:
        for raw in urls:
            url = raw.strip()
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://" + url
            try:
                lead = await harvest_site(
                    client,
                    url,
                    country=country,
                    industry=industry,
                    keywords=keywords,
                )
                if lead:
                    lid = db.upsert_lead(lead, require_contact=True)
                    if lid:
                        lead["id"] = lid
                        saved.append(lead)
            except Exception:
                pass
            await asyncio.sleep(0.3)
    return {"leads_found": len(saved), "leads": saved}


def parse_import_text(text: str, country: str = "", industry: str = "") -> list[dict]:
    """
    从粘贴文本中提取线索。
    支持：纯邮箱列表、邮箱+WhatsApp 混排、简单 CSV 行。
    """
    from .extractor import extract_emails, extract_whatsapps, extract_phones

    leads = []
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    # 若整段是一块文本
    if len(lines) <= 2 and len(text) > 200:
        emails = extract_emails(text)
        was = extract_whatsapps(text, text)
        phones = extract_phones(text)
        for e in emails:
            leads.append(
                {
                    "company": e.split("@")[-1].split(".")[0].title(),
                    "email": e,
                    "emails": [e],
                    "whatsapp": was[0] if was else "",
                    "whatsapps": was,
                    "phone": phones[0] if phones else "",
                    "phones": phones,
                    "country": country,
                    "industry": industry,
                    "source": "import_text",
                    "score": score_lead([e], was, phones),
                }
            )
        if was and not emails:
            for w in was:
                leads.append(
                    {
                        "company": f"WA {w}",
                        "whatsapp": w,
                        "whatsapps": [w],
                        "country": country,
                        "industry": industry,
                        "source": "import_text",
                        "score": score_lead([], [w], []),
                    }
                )
        return leads

    for ln in lines:
        # CSV: company,email,whatsapp,website,country
        if "," in ln and ln.count(",") >= 1:
            parts = [p.strip().strip('"') for p in ln.split(",")]
            if "@" in ln or re.search(r"\d{8,}", ln):
                company = parts[0] if parts and "@" not in parts[0] else ""
                emails = extract_emails(ln)
                was = extract_whatsapps(ln, ln)
                phones = extract_phones(ln)
                website = ""
                for p in parts:
                    if p.startswith("http") or ("." in p and " " not in p and "@" not in p and not p[0].isdigit()):
                        if "http" in p or p.count(".") >= 1:
                            if "@" not in p and not re.match(r"^\+?\d", p):
                                website = p if p.startswith("http") else "https://" + p
                leads.append(
                    {
                        "company": company or (emails[0].split("@")[-1] if emails else "导入线索"),
                        "email": emails[0] if emails else "",
                        "emails": emails,
                        "whatsapp": was[0] if was else "",
                        "whatsapps": was,
                        "phone": phones[0] if phones else "",
                        "phones": phones,
                        "website": website,
                        "country": country,
                        "industry": industry,
                        "source": "import_csv",
                        "score": score_lead(emails, was, phones, website, company),
                    }
                )
                continue

        emails = extract_emails(ln)
        was = extract_whatsapps(ln, ln)
        phones = extract_phones(ln)
        if not emails and not was and not phones:
            continue
        leads.append(
            {
                "company": (emails[0].split("@")[-1].split(".")[0].title() if emails else f"线索"),
                "email": emails[0] if emails else "",
                "emails": emails,
                "whatsapp": was[0] if was else "",
                "whatsapps": was,
                "phone": phones[0] if phones else "",
                "phones": phones,
                "country": country,
                "industry": industry,
                "source": "import_text",
                "score": score_lead(emails, was, phones),
            }
        )
    return leads
