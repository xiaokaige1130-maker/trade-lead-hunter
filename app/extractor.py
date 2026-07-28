"""从公开网页文本中提取邮箱、电话、WhatsApp 等联系方式。"""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

# 邮箱
EMAIL_RE = re.compile(
    r"(?i)(?<![a-z0-9._%+\-])([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,24})(?![a-z0-9._%+\-])"
)

# 常见垃圾/占位/技术域名（误提取）
EMAIL_BLACKLIST = {
    "example.com",
    "example.org",
    "email.com",
    "domain.com",
    "sentry.io",
    "wixpress.com",
    "cloudflare.com",
    "schema.org",
    "w3.org",
    "googleapis.com",
    "gstatic.com",
    "google.com",
    "googlemail.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "pinterest.com",
    "tiktok.com",
    "github.com",
    "npmjs.com",
    "jquery.com",
    "gravatar.com",
    "wordpress.com",
    "wp.com",
    "squarespace.com",
    "shopify.com",
    "myshopify.com",
    "sentry-next.wixpress.com",
    "amazonaws.com",
    "cloudfront.net",
    "jsdelivr.net",
    "cdnjs.com",
    "fontawesome.com",
    "yimg.com",
    "w3c.org",
    "javascript",
    "localhost",
    "test.com",
    "yourdomain.com",
    "company.com",
    "mailinator.com",
    "doe.com",  # john@doe.com 占位
    "clare.ai",  # 聊天插件
    "gstatic.com",
}

# 技术假域名片段
EMAIL_DOMAIN_BAD_PARTS = (
    "wixpress",
    "sentry",
    "cloudflare",
    "schema",
    "googleapis",
    "gstatic",
    "w3.org",
    "jquery",
    "jsdelivr",
    "cloudfront",
    "amazonaws",
    "alayer",
    "savereferr",
    "webpack",
    "polyfill",
)

EMAIL_LOCAL_BLACKLIST = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "mailer-daemon",
    "postmaster",
    "webmaster",
    "abuse",
    "privacy",
    "legal",
    "spam",
    "example",
    "test",
    "user",
    "username",
    "yourname",
    "name",
    "email",
    "window",
    "document",
    "function",
    "undefined",
    "null",
    "webpack",
    "chunk",
    "module",
    "export",
    "import",
    "oper",
    "awswafintegr",
    "d",
    "n",
    "x",
    "js",
    "css",
    "img",
    "png",
    "jpg",
    "john",  # john@doe 占位
}

# WhatsApp 链接
WA_LINK_RE = re.compile(
    r"(?i)(?:https?://)?(?:api\.|web\.|www\.)?wa(?:\.me|tsapp\.com)/(?:send\?[^\"'\s<>]+|[\d+]+)"
)
WA_ME_RE = re.compile(r"(?i)(?:https?://)?(?:www\.)?wa\.me/(\+?\d{8,15})")
WA_API_RE = re.compile(
    r"(?i)(?:https?://)?(?:api\.)?whatsapp\.com/send\?([^\"'\s<>]+)"
)
WA_TEXT_RE = re.compile(
    r"(?i)(?:whatsapp|whats\s*app|w\.?\s*a\.?|wa)[:\s#\-]*([+\d][\d\s\-()]{7,20}\d)"
)

# 电话（国际格式偏好）
PHONE_RE = re.compile(
    r"(?<!\d)(\+?\d{1,3}[\s\-]?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{3,4})(?!\d)"
)

# 混淆邮箱：info [at] company [dot] com
OBFUSCATED_EMAIL_RE = re.compile(
    r"(?i)([a-z0-9._%+\-]+)\s*(?:\[?\s*at\s*\]?|\(at\)|@)\s*([a-z0-9.\-]+)\s*(?:\[?\s*dot\s*\]?|\(dot\)|\.)\s*([a-z]{2,10})"
)


def _clean_email(email: str) -> str | None:
    email = email.strip().lower().rstrip(".,;:)>\"'")
    if email.count("@") != 1:
        return None
    local, domain = email.split("@", 1)
    if not local or not domain or "." not in domain:
        return None
    if len(email) > 80 or len(local) > 64:
        return None
    # 域名黑名单
    if domain in EMAIL_BLACKLIST or any(domain.endswith("." + b) for b in EMAIL_BLACKLIST):
        return None
    if any(p in domain for p in EMAIL_DOMAIN_BAD_PARTS):
        return None
    # 明显 JS/CSS 拼出来的假邮箱
    if any(x in local for x in ("noreply", "no-reply", "donotreply")):
        return None
    if local in EMAIL_LOCAL_BLACKLIST:
        return None
    # local 含点且像代码路径 window.d / operations.download
    if local.count(".") >= 2 and not re.match(r"^[a-z0-9._%+\-]+$", local):
        return None
    if re.search(r"(window|document|function|jquery|webpack|bundle)", local):
        return None
    if re.search(r"(window|document|function|jquery|webpack|bundle|push|layer)", domain):
        return None
    # TLD 必须像真的
    tld = domain.rsplit(".", 1)[-1]
    if tld in {
        "js", "css", "png", "jpg", "gif", "svg", "webp", "json", "xml", "php",
        "asp", "now", "let", "var", "push", "download", "savereferr", "ttf",
        "woff", "woff2", "map", "all", "html", "htm", "pdf", "page", "create",
        "apply", "getbyname", "getall",
    }:
        return None
    if len(tld) < 2 or len(tld) > 24:
        return None
    # 排除图片/静态资源/字体/PDF 误伤
    if domain.endswith((".png", ".jpg", ".gif", ".svg", ".css", ".js", ".pdf", ".ttf", ".woff")):
        return None
    if re.search(r"\.(png|jpe?g|gif|svg|webp|css|js|pdf|ttf|woff2?|html?)$", email):
        return None
    if "fonts." in domain or domain.startswith("www."):
        # www.xxx.com 作为邮箱域名极少见（www.ectr@ech 类）
        if domain.startswith("www."):
            return None
    # 单字母 / 纯数字 local 基本是误提取
    if len(local) <= 1:
        return None
    if local.isdigit():
        return None
    # u003e 等 unicode 转义残留
    if "u003" in local or "u002" in local:
        return None
    return email


def extract_emails(text: str) -> list[str]:
    found: list[str] = []
    for m in EMAIL_RE.finditer(text or ""):
        e = _clean_email(m.group(1))
        if e:
            found.append(e)
    for m in OBFUSCATED_EMAIL_RE.finditer(text or ""):
        e = _clean_email(f"{m.group(1)}@{m.group(2)}.{m.group(3)}")
        if e:
            found.append(e)
    # 去重保序
    return list(dict.fromkeys(found))


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    # 纯数字
    pure = digits.lstrip("+")
    if not pure.isdigit():
        return None
    if len(pure) < 8 or len(pure) > 15:
        return None
    # 过滤明显年份/邮编
    if pure.startswith("20") and len(pure) == 4:
        return None
    if digits.startswith("+"):
        return "+" + pure
    return pure


def extract_phones(text: str) -> list[str]:
    found: list[str] = []
    for m in PHONE_RE.finditer(text or ""):
        p = _normalize_phone(m.group(1))
        if p:
            found.append(p)
    return list(dict.fromkeys(found))


def extract_whatsapps(text: str, html: str = "") -> list[str]:
    """从文本与 HTML 中提取 WhatsApp 号码。"""
    found: list[str] = []
    blob = (text or "") + "\n" + (html or "")

    for m in WA_ME_RE.finditer(blob):
        p = _normalize_phone(m.group(1))
        if p:
            found.append(p)

    for m in WA_API_RE.finditer(blob):
        qs = parse_qs(m.group(1))
        phone = (qs.get("phone") or qs.get("text") or [""])[0]
        # text 参数里也可能含号码；优先 phone
        if "phone" in qs:
            phone = qs["phone"][0]
        p = _normalize_phone(unquote(phone))
        if p:
            found.append(p)

    for m in WA_TEXT_RE.finditer(blob):
        p = _normalize_phone(m.group(1))
        if p:
            found.append(p)

    # tel: 链接旁若有 WhatsApp 文案，也常是同一号码 — 已在 phones 中处理
    # 扫描 href="whatsapp://send?phone=..."
    for m in re.finditer(r"(?i)whatsapp://send\?[^\"'\s<>]*phone=(\+?\d{8,15})", blob):
        p = _normalize_phone(m.group(1))
        if p:
            found.append(p)

    return list(dict.fromkeys(found))


def extract_linkedin(text: str, html: str = "") -> str:
    blob = (html or "") + "\n" + (text or "")
    m = re.search(
        r"(?i)https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-z0-9\-_%/]+",
        blob,
    )
    return m.group(0).rstrip("/") if m else ""


def score_lead(
    emails: Iterable[str],
    whatsapps: Iterable[str],
    phones: Iterable[str],
    website: str = "",
    company: str = "",
) -> int:
    score = 0
    emails = list(emails)
    whatsapps = list(whatsapps)
    phones = list(phones)
    if emails:
        score += 40
        # 企业邮箱加分（非 gmail/yahoo 等）
        free = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "qq.com", "163.com"}
        if any(e.split("@")[-1] not in free for e in emails):
            score += 15
    if whatsapps:
        score += 35
    if phones:
        score += 10
    if website:
        score += 10
    if company and company not in ("未知公司", ""):
        score += 5
    return min(score, 100)


def guess_company_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        # 去掉常见后缀
        parts = host.split(".")
        if len(parts) >= 2:
            return parts[-2].replace("-", " ").title()
        return host
    except Exception:
        return ""


def extract_from_page(url: str, html: str, text: str) -> dict:
    emails = extract_emails(text + "\n" + html)
    phones = extract_phones(text)
    whatsapps = extract_whatsapps(text, html)
    linkedin = extract_linkedin(text, html)
    company = guess_company_from_url(url)
    return {
        "company": company,
        "website": url,
        "emails": emails,
        "email": emails[0] if emails else "",
        "phones": phones,
        "phone": phones[0] if phones else "",
        "whatsapps": whatsapps,
        "whatsapp": whatsapps[0] if whatsapps else "",
        "linkedin": linkedin,
        "score": score_lead(emails, whatsapps, phones, url, company),
        "source_url": url,
    }
