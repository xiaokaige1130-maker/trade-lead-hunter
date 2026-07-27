"""
多源客户数据爬虫

在「社媒评论截流 / 官网搜索」之外，再开多条公开数据管道：

1. maps      — OpenStreetMap 商户（店名、电话、官网、地址）
2. directory  — 黄页/B2B 目录向搜索（DDG）+ 页面联系方式提取
3. b2b        — 进口商/批发商/分销商专项搜索
4. domain     — 已知域名批量深挖 contact 页
5. email_gen  — 根据公司名/域名生成常见商务邮箱并做 MX 存活探测
6. combo      — 一键组合：maps + directory + b2b

全部基于公开网页 / 开放数据，无需付费 API Key。
仅用于合法 B2B 商务拓展，请遵守 robots 与当地营销法规。
"""
from __future__ import annotations

import asyncio
import re
import socket
from typing import Any, Optional
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup

from . import db
from .extractor import (
    extract_emails,
    extract_from_page,
    extract_phones,
    extract_whatsapps,
    guess_company_from_url,
    score_lead,
)
from .hunter import (
    COUNTRY_MAP,
    USER_AGENT,
    duckduckgo_search,
    harvest_site,
    _client,
    _html_to_text,
)

# ---------- 国家中心坐标（OSM 搜索用，近似） ----------
COUNTRY_CENTER: dict[str, tuple[float, float, int]] = {
    # code: (lat, lon, search_radius_meters 默认)
    "US": (39.8, -98.5, 500000),
    "GB": (54.0, -2.0, 300000),
    "DE": (51.1, 10.4, 300000),
    "FR": (46.6, 2.2, 300000),
    "IT": (42.5, 12.5, 300000),
    "ES": (40.2, -3.7, 300000),
    "NL": (52.1, 5.3, 150000),
    "AE": (24.3, 54.3, 200000),
    "SA": (23.8, 45.0, 400000),
    "AU": (-25.0, 134.0, 800000),
    "CA": (56.0, -106.0, 800000),
    "MX": (23.6, -102.5, 500000),
    "BR": (-14.2, -51.9, 800000),
    "IN": (22.0, 79.0, 600000),
    "SG": (1.35, 103.8, 30000),
    "MY": (4.2, 101.9, 300000),
    "TH": (15.8, 100.9, 400000),
    "VN": (16.0, 107.0, 400000),
    "ID": (-2.0, 118.0, 800000),
    "PH": (12.8, 121.7, 400000),
    "TR": (39.0, 35.0, 400000),
    "JP": (36.2, 138.2, 400000),
    "KR": (36.5, 127.8, 200000),
    "ZA": (-30.5, 25.0, 500000),
    "NG": (9.0, 8.0, 400000),
    "EG": (26.8, 30.8, 400000),
    "PL": (52.1, 19.4, 300000),
    "SE": (62.0, 15.0, 400000),
    "CH": (46.8, 8.2, 150000),
    "BE": (50.5, 4.4, 120000),
    "AT": (47.5, 14.5, 150000),
    "PT": (39.5, -8.0, 200000),
    "IE": (53.1, -8.0, 150000),
    "CL": (-35.6, -71.5, 500000),
    "CO": (4.5, -74.3, 400000),
    "AR": (-34.6, -58.4, 500000),
    "PE": (-9.1, -74.3, 500000),
    "NZ": (-41.0, 174.0, 400000),
    "RU": (61.5, 105.3, 1000000),
}

# 常见城市中心（更精准的 maps 搜索）
CITY_CENTER: dict[str, tuple[float, float]] = {
    "dubai": (25.2048, 55.2708),
    "abu dhabi": (24.4539, 54.3773),
    "riyadh": (24.7136, 46.6753),
    "jeddah": (21.4858, 39.1925),
    "london": (51.5074, -0.1278),
    "manchester": (53.4808, -2.2426),
    "new york": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "miami": (25.7617, -80.1918),
    "houston": (29.7604, -95.3698),
    "chicago": (41.8781, -87.6298),
    "toronto": (43.6532, -79.3832),
    "vancouver": (49.2827, -123.1207),
    "sydney": (-33.8688, 151.2093),
    "melbourne": (-37.8136, 144.9631),
    "singapore": (1.3521, 103.8198),
    "kuala lumpur": (3.1390, 101.6869),
    "bangkok": (13.7563, 100.5018),
    "ho chi minh": (10.8231, 106.6297),
    "hanoi": (21.0278, 105.8342),
    "jakarta": (-6.2088, 106.8456),
    "manila": (14.5995, 120.9842),
    "mumbai": (19.0760, 72.8777),
    "delhi": (28.6139, 77.2090),
    "sao paulo": (-23.5505, -46.6333),
    "mexico city": (19.4326, -99.1332),
    "berlin": (52.5200, 13.4050),
    "munich": (48.1351, 11.5820),
    "paris": (48.8566, 2.3522),
    "milan": (45.4642, 9.1900),
    "madrid": (40.4168, -3.7038),
    "amsterdam": (52.3676, 4.9041),
    "istanbul": (41.0082, 28.9784),
    "moscow": (55.7558, 37.6173),
    "lagos": (6.5244, 3.3792),
    "cairo": (30.0444, 31.2357),
    "johannesburg": (-26.2041, 28.0473),
    "tokyo": (35.6762, 139.6503),
    "seoul": (37.5665, 126.9780),
    "warsaw": (52.2297, 21.0122),
}

# OSM 常见商户类型（amenity/shop）
OSM_SHOP_TAGS = [
    "shop",
    "amenity",
    "office",
    "craft",
    "industrial",
]

DIRECTORY_QUERY_TEMPLATES = [
    '{kw} {ind} {loc} "email" OR contact OR "whatsapp"',
    '{kw} {ind} {loc} importer buyer email',
    '{kw} wholesaler {loc} "contact us"',
    '{kw} distributor {loc} phone OR whatsapp',
    '"{kw}" {loc} yellow pages OR directory email',
    'site:europages.com {kw} {loc}',
    'site:thomasnet.com {kw}',
    'site:kompass.com {kw} {loc}',
]

B2B_QUERY_TEMPLATES = [
    '{kw} importer {loc} email -alibaba -made-in-china',
    '{kw} wholesale buyer {loc} contact',
    '{kw} purchasing manager {loc} email',
    '{kw} trading company {loc} "whatsapp"',
    '{kw} distributor wanted {loc}',
    '{kw} OEM buyer {loc} rfq email',
]


def _country_label(code: str) -> str:
    code = (code or "").upper()
    if code in COUNTRY_MAP:
        return COUNTRY_MAP[code]["name_zh"]
    return code


def _country_en(code: str) -> str:
    code = (code or "").upper()
    if code in COUNTRY_MAP:
        return COUNTRY_MAP[code]["name"]
    return code


def _resolve_center(country_code: str, city: str = "") -> tuple[float, float, int]:
    city_key = (city or "").strip().lower()
    if city_key in CITY_CENTER:
        lat, lon = CITY_CENTER[city_key]
        return lat, lon, 25000  # 城市级 25km
    code = (country_code or "").upper()
    if code in COUNTRY_CENTER:
        return COUNTRY_CENTER[code]
    return 20.0, 0.0, 500000


# ===================== 1. OpenStreetMap 商户 =====================


async def scrape_osm_places(
    keyword: str,
    country_code: str = "",
    city: str = "",
    limit: int = 30,
    radius: Optional[int] = None,
) -> dict[str, Any]:
    """
    地图商户公开数据：
    1) 优先 Nominatim（快、稳，含 phone/email extratags）
    2) 补充 Overpass 附近 shop/office（短超时，失败忽略）
    """
    lat, lon, default_r = _resolve_center(country_code, city)
    r = radius or (25000 if city else min(default_r, 50000))
    r = min(max(r, 3000), 60000)
    kw = keyword.replace('"', "").strip()
    elements: list[dict] = []
    err = ""
    source_used = []

    # ---- 1) Nominatim 主通道 ----
    try:
        nom_q = " ".join(x for x in [kw, city, _country_en(country_code)] if x)
        async with httpx.AsyncClient(
            timeout=25.0,
            headers={"User-Agent": USER_AGENT + " LeadHunter/1.2"},
            follow_redirects=True,
        ) as client:
            # 多组查询提高覆盖
            queries_n = [nom_q]
            if city:
                queries_n.append(f"{kw} shop {city}")
                queries_n.append(f"{kw} store {city}")
            else:
                queries_n.append(f"{kw} {_country_en(country_code)}")
            seen_ids = set()
            for nq in queries_n[:3]:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": nq,
                        "format": "json",
                        "addressdetails": 1,
                        "extratags": 1,
                        "limit": min(limit, 20),
                    },
                )
                if resp.status_code != 200:
                    err = f"nominatim HTTP {resp.status_code}"
                    continue
                for item in resp.json() or []:
                    oid = item.get("osm_id") or item.get("place_id")
                    if oid in seen_ids:
                        continue
                    seen_ids.add(oid)
                    extra = item.get("extratags") or {}
                    addr = item.get("address") or {}
                    display = item.get("display_name") or ""
                    name = display.split(",")[0].strip()
                    elements.append(
                        {
                            "type": item.get("osm_type") or "node",
                            "id": item.get("osm_id") or 0,
                            "tags": {
                                "name": name,
                                "phone": extra.get("phone")
                                or extra.get("contact:phone")
                                or "",
                                "email": extra.get("email")
                                or extra.get("contact:email")
                                or "",
                                "website": extra.get("website")
                                or extra.get("url")
                                or extra.get("contact:website")
                                or "",
                                "contact:whatsapp": extra.get("contact:whatsapp") or "",
                                "addr:housenumber": addr.get("house_number") or "",
                                "addr:street": addr.get("road") or "",
                                "addr:city": addr.get("city")
                                or addr.get("town")
                                or addr.get("suburb")
                                or "",
                                "addr:country": addr.get("country") or "",
                                "shop": extra.get("shop") or item.get("type") or "",
                                "office": extra.get("office") or "",
                                "amenity": extra.get("amenity") or "",
                            },
                        }
                    )
                await asyncio.sleep(1.05)  # Nominatim 礼貌限速
            if elements:
                source_used.append("nominatim")
                err = ""
    except Exception as e:
        err = f"nominatim: {e}"

    # ---- 2) Overpass 短超时补充（有电话的节点）----
    if len(elements) < limit:
        overpass_q = f"""
        [out:json][timeout:20];
        (
          node["name"~"{kw}",i]["phone"](around:{min(r,20000)},{lat},{lon});
          node["name"~"{kw}",i]["website"](around:{min(r,20000)},{lat},{lon});
          node["shop"]["phone"](around:{min(r,8000)},{lat},{lon});
        );
        out center tags {limit};
        """
        for ep in (
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass-api.de/api/interpreter",
        ):
            try:
                async with httpx.AsyncClient(
                    timeout=22.0,
                    headers={"User-Agent": USER_AGENT + " OSMLeadBot/1.2"},
                    follow_redirects=True,
                ) as client:
                    resp = await client.post(ep, data={"data": overpass_q})
                    if resp.status_code == 200:
                        extra_els = resp.json().get("elements") or []
                        if extra_els:
                            elements.extend(extra_els)
                            source_used.append("overpass")
                            err = ""
                            break
            except Exception as e:
                err = err or f"overpass: {e}"
                continue

    elements = elements[: max(limit * 2, limit)]  # 稍后按联系方式筛选

    leads = []
    country_label = _country_label(country_code) or city
    for el in elements[:limit]:
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("name:en") or tags.get("brand") or ""
        if not name:
            continue
        phone = tags.get("phone") or tags.get("contact:phone") or tags.get("mobile") or ""
        email = (
            tags.get("email")
            or tags.get("contact:email")
            or ""
        ).lower()
        website = tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
        if website and not website.startswith("http"):
            website = "https://" + website
        whatsapp = tags.get("contact:whatsapp") or ""
        if whatsapp:
            whatsapp = re.sub(r"[^\d+]", "", whatsapp)
        addr_parts = [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", ""),
            tags.get("addr:city", "") or tags.get("addr:town", ""),
            tags.get("addr:country", ""),
        ]
        address = " ".join(p for p in addr_parts if p).strip()
        shop_type = tags.get("shop") or tags.get("office") or tags.get("amenity") or tags.get("craft") or ""

        phones = extract_phones(phone) if phone else ([] if not phone else [phone])
        if phone and not phones:
            phones = [phone]
        emails = [email] if email else []
        was = [whatsapp] if whatsapp else []
        if not was and phone:
            # 国际号有时即 WhatsApp
            was = []

        score = score_lead(emails, was, phones, website, name)
        if phone:
            score = min(100, score + 15)
        if address:
            score = min(100, score + 5)

        lead = {
            "company": name[:120],
            "contact_name": "",
            "country": country_label,
            "city": city or tags.get("addr:city") or tags.get("addr:town") or "",
            "industry": shop_type or keyword,
            "website": website,
            "email": email,
            "emails": emails,
            "phone": phones[0] if phones else phone,
            "phones": phones or ([phone] if phone else []),
            "whatsapp": whatsapp,
            "whatsapps": was,
            "linkedin": "",
            "source": "osm_maps",
            "source_url": website
            or f"https://www.openstreetmap.org/{el.get('type','node')}/{el.get('id','')}",
            "keywords": keyword,
            "notes": f"[OSM商户] {address}\n类型:{shop_type}\n坐标附近搜索",
            "score": score,
            "status": "new",
            "tags": f"maps,osm,{shop_type}",
        }
        # 至少要有电话/邮箱/网站之一；否则保留名称+地址也入库（可人工补联）
        if lead["phone"] or lead["email"] or lead["website"] or lead["whatsapp"]:
            lid = db.upsert_lead(lead)
            lead["id"] = lid
            leads.append(lead)
        elif name and address:
            lead["score"] = max(lead["score"], 15)
            lead["notes"] += "\n(暂无公开电话/邮箱，仅名称地址)"
            lid = db.upsert_lead(lead)
            lead["id"] = lid
            leads.append(lead)

    return {
        "ok": True,
        "source": "maps",
        "keyword": keyword,
        "country": country_code,
        "city": city,
        "center": {"lat": lat, "lon": lon, "radius_m": r},
        "backend": "+".join(source_used) or "none",
        "raw_elements": len(elements),
        "leads_found": len(leads),
        "leads": leads,
        "error": err,
    }


# ===================== 2. 目录 / 黄页搜索 =====================


async def scrape_directory(
    keyword: str,
    country_code: str = "",
    industry: str = "",
    city: str = "",
    max_sites: int = 12,
) -> dict[str, Any]:
    """DuckDuckGo 目录向搜索 + 站点 contact 深挖。"""
    loc = city or _country_en(country_code) or ""
    ind = industry or ""
    kw = keyword.strip()

    queries = []
    for tpl in DIRECTORY_QUERY_TEMPLATES:
        q = tpl.format(kw=kw, ind=ind, loc=loc).strip()
        q = re.sub(r"\s+", " ", q)
        queries.append(q)
    queries = list(dict.fromkeys(queries))[:5]

    job_id = db.create_job(
        query=f"directory:{kw}|{ind}|{loc}",
        country=_country_label(country_code) or loc,
        industry=industry or keyword,
    )

    all_hits: list[dict] = []
    for q in queries:
        hits = await duckduckgo_search(q, max_results=8)
        all_hits.extend(hits)
        await asyncio.sleep(0.6)

    by_dom: dict[str, dict] = {}
    for h in all_hits:
        dom = urlparse(h["url"]).netloc.lower().lstrip("www.")
        if not dom or dom in by_dom:
            continue
        # 过滤大平台
        if any(
            x in dom
            for x in (
                "youtube.com",
                "facebook.com",
                "instagram.com",
                "twitter.com",
                "linkedin.com",
                "amazon.",
                "ebay.",
                "alibaba.",
                "wikipedia.org",
            )
        ):
            continue
        by_dom[dom] = h

    sites = list(by_dom.values())[:max_sites]
    saved = []
    async with await _client() as client:
        for hit in sites:
            try:
                lead = await harvest_site(
                    client,
                    hit["url"],
                    title=hit.get("title") or "",
                    country=_country_label(country_code) or loc,
                    industry=industry or keyword,
                    keywords=keyword,
                )
                if lead:
                    lead["source"] = "directory"
                    lead["tags"] = "directory,web"
                    lid = db.upsert_lead(lead)
                    lead["id"] = lid
                    saved.append(lead)
            except Exception:
                pass
            await asyncio.sleep(0.35)

    db.finish_job(job_id, result_count=len(saved))
    return {
        "ok": True,
        "source": "directory",
        "job_id": job_id,
        "queries": queries,
        "sites_scanned": len(sites),
        "leads_found": len(saved),
        "leads": saved,
    }


# ===================== 3. B2B 进口商/批发商专项 =====================


async def scrape_b2b_buyers(
    keyword: str,
    country_code: str = "",
    city: str = "",
    max_sites: int = 12,
) -> dict[str, Any]:
    loc = city or _country_en(country_code) or ""
    kw = keyword.strip()
    queries = [
        re.sub(r"\s+", " ", tpl.format(kw=kw, loc=loc)).strip()
        for tpl in B2B_QUERY_TEMPLATES
    ][:5]

    job_id = db.create_job(
        query=f"b2b:{kw}|{loc}",
        country=_country_label(country_code) or loc,
        industry=f"buyer/{kw}",
    )

    all_hits = []
    for q in queries:
        all_hits.extend(await duckduckgo_search(q, max_results=8))
        await asyncio.sleep(0.6)

    by_dom = {}
    for h in all_hits:
        dom = urlparse(h["url"]).netloc.lower().lstrip("www.")
        if not dom or dom in by_dom:
            continue
        if any(
            x in dom
            for x in ("alibaba.", "made-in-china.", "youtube.", "facebook.", "amazon.")
        ):
            continue
        by_dom[dom] = h

    sites = list(by_dom.values())[:max_sites]
    saved = []
    async with await _client() as client:
        for hit in sites:
            try:
                lead = await harvest_site(
                    client,
                    hit["url"],
                    title=hit.get("title") or "",
                    country=_country_label(country_code) or loc,
                    industry=f"importer/{keyword}",
                    keywords=keyword,
                )
                if lead:
                    lead["source"] = "b2b_buyer"
                    lead["tags"] = "b2b,importer,buyer"
                    lead["score"] = min(100, (lead.get("score") or 0) + 10)
                    lid = db.upsert_lead(lead)
                    lead["id"] = lid
                    saved.append(lead)
            except Exception:
                pass
            await asyncio.sleep(0.35)

    db.finish_job(job_id, result_count=len(saved))
    return {
        "ok": True,
        "source": "b2b",
        "job_id": job_id,
        "queries": queries,
        "sites_scanned": len(sites),
        "leads_found": len(saved),
        "leads": saved,
    }


# ===================== 4. 域名批量深挖 =====================


async def scrape_domains(
    domains: list[str],
    country: str = "",
    industry: str = "",
    keywords: str = "",
) -> dict[str, Any]:
    """对一批域名/URL 做 contact 页深挖。"""
    urls = []
    for d in domains:
        d = d.strip()
        if not d:
            continue
        if not d.startswith("http"):
            d = "https://" + d
        urls.append(d)

    saved = []
    async with await _client() as client:
        for url in urls[:40]:
            try:
                lead = await harvest_site(
                    client,
                    url,
                    country=country,
                    industry=industry,
                    keywords=keywords,
                )
                if lead:
                    lead["source"] = "domain_crawl"
                    lead["tags"] = "domain,deep"
                    lid = db.upsert_lead(lead)
                    lead["id"] = lid
                    saved.append(lead)
            except Exception:
                pass
            await asyncio.sleep(0.3)

    return {
        "ok": True,
        "source": "domain",
        "domains": len(urls),
        "leads_found": len(saved),
        "leads": saved,
    }


# ===================== 5. 邮箱模式生成 + MX 探测 =====================

EMAIL_LOCAL_PARTS = [
    "info",
    "sales",
    "contact",
    "enquiry",
    "inquiry",
    "export",
    "import",
    "purchase",
    "purchasing",
    "buyer",
    "procurement",
    "trade",
    "trading",
    "business",
    "office",
    "hello",
    "support",
    "admin",
    "marketing",
    "order",
    "orders",
    "b2b",
    "wholesale",
]


def _domain_from_company_or_url(company_or_domain: str) -> str:
    s = (company_or_domain or "").strip().lower()
    if not s:
        return ""
    if "://" in s or "/" in s:
        host = urlparse(s if "://" in s else "https://" + s).netloc
        return host.lstrip("www.")
    if "." in s and " " not in s:
        return s.lstrip("www.")
    # 公司名 → 粗略域名猜测（仅作候选，需 MX 验证）
    slug = re.sub(r"[^a-z0-9]+", "", s.lower())
    return slug


def check_mx(domain: str, timeout: float = 3.0) -> bool:
    """检查域名是否有 MX 或 A 记录（粗略存活）。"""
    domain = domain.lower().strip().lstrip("www.")
    if not domain or "." not in domain:
        return False
    try:
        import smtplib  # noqa: F401

        # 优先 dnspython，若无则用 socket
        try:
            import dns.resolver  # type: ignore

            answers = dns.resolver.resolve(domain, "MX")
            return len(answers) > 0
        except ImportError:
            pass
        except Exception:
            pass
        # fallback: A 记录
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False


async def generate_emails(
    companies: list[str],
    country: str = "",
    industry: str = "",
    max_locals: int = 8,
    verify_mx: bool = True,
) -> dict[str, Any]:
    """
    输入公司名或域名列表，生成常见商务邮箱并（可选）MX 验证后入库。
    注意：生成的是「高概率商务邮箱」，发送前仍建议先验证/小流量测试。
    """
    locals_ = EMAIL_LOCAL_PARTS[: max(3, min(max_locals, 15))]
    saved = []
    candidates_total = 0

    for raw in companies:
        raw = raw.strip()
        if not raw:
            continue
        domain = _domain_from_company_or_url(raw)
        if not domain:
            continue
        # 若是纯 slug 无点，尝试补 .com
        trial_domains = [domain] if "." in domain else [f"{domain}.com", f"{domain}.co", f"{domain}.net"]

        alive_domain = ""
        if verify_mx:
            for td in trial_domains:
                ok = await asyncio.to_thread(check_mx, td)
                if ok:
                    alive_domain = td
                    break
        else:
            alive_domain = trial_domains[0]

        if not alive_domain:
            continue

        company_name = raw if " " in raw or raw[0].isupper() else guess_company_from_url(
            "https://" + alive_domain
        )
        emails = [f"{loc}@{alive_domain}" for loc in locals_]
        candidates_total += len(emails)

        # 主邮箱用 info/sales
        primary = next((e for e in emails if e.startswith(("sales@", "info@", "contact@"))), emails[0])
        lead = {
            "company": company_name or alive_domain,
            "country": country,
            "industry": industry,
            "website": f"https://{alive_domain}",
            "email": primary,
            "emails": emails,
            "phone": "",
            "phones": [],
            "whatsapp": "",
            "whatsapps": [],
            "source": "email_gen",
            "source_url": f"https://{alive_domain}",
            "keywords": "generated",
            "notes": f"[邮箱模式生成] 域名 MX/A 探测通过\n候选: {', '.join(emails[:6])}",
            "score": 35 if verify_mx else 20,
            "status": "new",
            "tags": "email_gen,pattern",
        }
        lid = db.upsert_lead(lead)
        lead["id"] = lid
        saved.append(lead)

    return {
        "ok": True,
        "source": "email_gen",
        "companies": len(companies),
        "candidates_total": candidates_total,
        "leads_found": len(saved),
        "leads": saved,
        "verify_mx": verify_mx,
    }


# ===================== 6. 文本/HTML 万能提取 =====================


def scrape_raw_text(
    text: str,
    country: str = "",
    industry: str = "",
    source: str = "raw_text",
) -> dict[str, Any]:
    """从任意文本/HTML 海量提取邮箱电话 WhatsApp。"""
    emails = extract_emails(text)
    phones = extract_phones(text)
    was = extract_whatsapps(text, text)
    saved = []

    # 按邮箱建线索
    for e in emails:
        domain = e.split("@")[-1]
        lead = {
            "company": domain.split(".")[0].title(),
            "country": country,
            "industry": industry,
            "website": f"https://{domain}",
            "email": e,
            "emails": [e],
            "phone": phones[0] if phones else "",
            "phones": phones[:5],
            "whatsapp": was[0] if was else "",
            "whatsapps": was[:5],
            "source": source,
            "source_url": "",
            "keywords": "raw_extract",
            "notes": "[原始文本提取]",
            "score": score_lead([e], was, phones, domain, domain),
            "status": "new",
            "tags": "raw,extract",
        }
        lid = db.upsert_lead(lead)
        lead["id"] = lid
        saved.append(lead)

    # 仅 WhatsApp 无邮箱
    if was and not emails:
        for w in was:
            lead = {
                "company": f"WA {w}",
                "country": country,
                "industry": industry,
                "whatsapp": w,
                "whatsapps": [w],
                "email": "",
                "emails": [],
                "phone": w,
                "phones": [w],
                "source": source,
                "notes": "[原始文本 WhatsApp]",
                "score": 40,
                "status": "new",
                "tags": "raw,whatsapp",
            }
            lid = db.upsert_lead(lead)
            lead["id"] = lid
            saved.append(lead)

    return {
        "ok": True,
        "source": "raw",
        "emails": len(emails),
        "phones": len(phones),
        "whatsapps": len(was),
        "leads_found": len(saved),
        "leads": saved,
    }


# ===================== 7. 组合一键获客 =====================


async def scrape_combo(
    keyword: str,
    country_code: str = "",
    city: str = "",
    industry: str = "",
    use_maps: bool = True,
    use_directory: bool = True,
    use_b2b: bool = True,
    max_per_source: int = 10,
) -> dict[str, Any]:
    """组合多源并行/串行拉取，汇总入库。"""
    results = {}
    total = 0

    if use_maps:
        try:
            results["maps"] = await scrape_osm_places(
                keyword=keyword or industry or "shop",
                country_code=country_code,
                city=city,
                limit=max_per_source,
            )
            total += results["maps"].get("leads_found") or 0
        except Exception as e:
            results["maps"] = {"ok": False, "error": str(e), "leads_found": 0}

    if use_directory:
        try:
            results["directory"] = await scrape_directory(
                keyword=keyword,
                country_code=country_code,
                industry=industry,
                city=city,
                max_sites=max_per_source,
            )
            total += results["directory"].get("leads_found") or 0
        except Exception as e:
            results["directory"] = {"ok": False, "error": str(e), "leads_found": 0}

    if use_b2b:
        try:
            results["b2b"] = await scrape_b2b_buyers(
                keyword=keyword,
                country_code=country_code,
                city=city,
                max_sites=max_per_source,
            )
            total += results["b2b"].get("leads_found") or 0
        except Exception as e:
            results["b2b"] = {"ok": False, "error": str(e), "leads_found": 0}

    return {
        "ok": True,
        "source": "combo",
        "keyword": keyword,
        "country_code": country_code,
        "city": city,
        "total_leads": total,
        "results": {
            k: {
                "ok": v.get("ok"),
                "leads_found": v.get("leads_found") or 0,
                "error": v.get("error"),
                "sites_scanned": v.get("sites_scanned") or v.get("raw_elements"),
            }
            for k, v in results.items()
        },
    }


def list_sources() -> list[dict[str, str]]:
    return [
        {
            "id": "maps",
            "name": "地图商户 (OpenStreetMap)",
            "desc": "按城市/国家抓商户名、电话、官网、邮箱（开放地图数据）",
        },
        {
            "id": "directory",
            "name": "黄页 / 目录站",
            "desc": "搜索黄页、目录、contact 页，提取公开邮箱与 WhatsApp",
        },
        {
            "id": "b2b",
            "name": "B2B 进口商/批发商",
            "desc": "专项搜索 importer / wholesaler / distributor / buyer 联系方式",
        },
        {
            "id": "domain",
            "name": "域名批量深挖",
            "desc": "给定一批官网域名，自动翻 contact/about 提取联系方式",
        },
        {
            "id": "email_gen",
            "name": "邮箱模式生成",
            "desc": "根据公司域名生成 sales@/info@ 等并做 MX 存活探测",
        },
        {
            "id": "raw",
            "name": "文本/HTML 海量提取",
            "desc": "粘贴任意名录、网页源码、聊天记录，提取邮箱电话 WhatsApp",
        },
        {
            "id": "combo",
            "name": "一键组合获客",
            "desc": "地图 + 目录 + B2B 三管齐下，适合快速起盘",
        },
    ]
