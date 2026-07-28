"""
线索画像：做什么的 + 联系人/职位

把地图标签、搜索词、网页标题/正文，整理成业务员能看懂的：
- business_type（业态/做什么）
- contact_name（联系人）
- contact_title（职位）
- description（一句话）
"""
from __future__ import annotations

import re
from typing import Any, Optional

# OSM shop/office/amenity → 中文业态
OSM_TYPE_ZH: dict[str, str] = {
    "furniture": "家具店/家具商",
    "electronics": "电子产品店",
    "computer": "电脑/IT 设备",
    "mobile_phone": "手机通讯店",
    "appliance": "家电卖场",
    "hardware": "五金建材",
    "doityourself": "建材/DIY 超市",
    "convenience": "便利店",
    "supermarket": "超市",
    "mall": "购物中心",
    "department_store": "百货商场",
    "wholesale": "批发商",
    "trade": "贸易公司",
    "company": "公司/企业",
    "estate_agent": "地产中介",
    "car": "汽车销售",
    "car_repair": "汽修",
    "car_parts": "汽车配件",
    "bicycle": "自行车店",
    "clothes": "服装店",
    "shoes": "鞋店",
    "beauty": "美妆/美容",
    "hairdresser": "美发",
    "chemist": "药店",
    "pharmacy": "药房",
    "optician": "眼镜店",
    "jewelry": "珠宝",
    "gift": "礼品店",
    "books": "书店",
    "stationery": "文具",
    "sports": "体育用品",
    "toys": "玩具店",
    "pet": "宠物店",
    "florist": "花店",
    "bakery": "面包店",
    "butcher": "肉店",
    "seafood": "海鲜店",
    "greengrocer": "果蔬店",
    "alcohol": "酒类专卖",
    "restaurant": "餐厅",
    "cafe": "咖啡馆",
    "fast_food": "快餐",
    "bar": "酒吧",
    "pub": "酒馆",
    "hotel": "酒店",
    "motel": "汽车旅馆",
    "guest_house": "民宿/宾馆",
    "travel_agency": "旅行社",
    "laundry": "洗衣店",
    "dry_cleaning": "干洗",
    "copyshop": "文印店",
    "storage_rental": "仓储租赁",
    "logistics": "物流",
    "warehouse": "仓库/仓储",
    "manufacturer": "制造商/工厂",
    "industrial": "工业企业",
    "construction": "建筑公司",
    "architect": "建筑设计",
    "engineer": "工程公司",
    "advertising_agency": "广告公司",
    "it": "IT/软件",
    "telecommunication": "电信",
    "lawyer": "律师事务所",
    "accountant": "会计事务所",
    "insurance": "保险",
    "financial": "金融服务",
    "bank": "银行",
    "government": "政府机构",
    "ngo": "NGO/协会",
    "association": "行业协会",
    "educational_institution": "教育机构",
    "clinic": "诊所",
    "hospital": "医院",
    "dentist": "牙科",
    "veterinary": "宠物医院",
    "yes": "商户",
    "vacant": "空置",
}

# 关键词 → 业态补充
KEYWORD_TYPE_ZH: dict[str, str] = {
    "importer": "进口商",
    "exporter": "进口商/进口采购",
    "wholesaler": "批发商",
    "wholesale": "批发商",
    "distributor": "分销商",
    "distributor": "分销商",
    "retailer": "零售商",
    "retail": "零售商",
    "manufacturer": "制造商",
    "factory": "工厂",
    "trading": "贸易公司",
    "trader": "贸易商",
    "supplier": "供应商",
    "dealer": "经销商",
    "agent": "代理商",
    "buyer": "采购商/买家",
    "purchasing": "采购",
    "procurement": "采购",
    "furniture": "家具相关",
    "led": "LED/照明相关",
    "lighting": "照明相关",
    "auto parts": "汽车配件",
    "electronics": "电子产品",
    "packaging": "包装相关",
    "textile": "纺织",
    "garment": "服装",
    "cosmetic": "化妆品",
    "beauty": "美妆",
    "hardware": "五金",
    "construction": "建材/工程",
    "medical": "医疗器械/用品",
    "food": "食品",
    "agriculture": "农业设备/农资",
}

# 邮箱 local → 可能职位
EMAIL_ROLE_ZH: dict[str, str] = {
    "info": "综合咨询",
    "sales": "销售",
    "sale": "销售",
    "export": "出口业务",
    "import": "进口业务",
    "purchase": "采购",
    "purchasing": "采购",
    "buyer": "采购",
    "procurement": "采购",
    "trade": "贸易业务",
    "trading": "贸易业务",
    "order": "订单",
    "orders": "订单",
    "enquiry": "询盘",
    "inquiry": "询盘",
    "contact": "对外联系",
    "hello": "对外联系",
    "office": "办公室",
    "admin": "行政",
    "support": "客户支持",
    "marketing": "市场",
    "business": "商务",
    "b2b": "B2B 业务",
    "wholesale": "批发业务",
    "manager": "经理",
    "director": "总监",
    "ceo": "高管",
    "owner": "负责人",
}

TITLE_PATTERNS = [
    # English
    re.compile(
        r"(?i)\b("
        r"CEO|CFO|CTO|COO|Founder|Co-?Founder|Owner|Director|Managing Director|"
        r"General Manager|Sales Manager|Export Manager|Import Manager|"
        r"Purchase Manager|Purchasing Manager|Procurement Manager|"
        r"Marketing Manager|Business Development|BD Manager|"
        r"Sales Representative|Account Manager|Store Manager|"
        r"President|Vice President|VP Sales|Head of Sales|Head of Purchasing"
        r")\b[:\-\s]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})?"
    ),
    re.compile(
        r"(?i)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b[,，\-\s]+("
        r"CEO|Director|Manager|Owner|Founder|President|Sales|Export|Import|Purchase"
        r")\b"
    ),
    # 中文
    re.compile(
        r"(老板|总经理|销售经理|出口经理|进口经理|采购经理|业务经理|店长|负责人)"
        r"[:：\s]*([\u4e00-\u9fa5·]{2,8})?"
    ),
]

CONTACT_LINE_RE = re.compile(
    r"(?i)(?:contact|联系人|attn|attention|负责人|业务员)\s*[:：]\s*([A-Za-z\u4e00-\u9fa5·\.\s]{2,40})"
)


def osm_type_label(shop_type: str) -> str:
    raw = (shop_type or "").strip().lower().replace(" ", "_")
    if not raw:
        return ""
    if raw in OSM_TYPE_ZH:
        return OSM_TYPE_ZH[raw]
    # 复合
    for k, v in OSM_TYPE_ZH.items():
        if k in raw:
            return v
    return raw.replace("_", " ")


def keyword_business_type(keyword: str = "", industry: str = "") -> str:
    blob = f"{keyword} {industry}".lower()
    hits = []
    for k, v in KEYWORD_TYPE_ZH.items():
        if k in blob and v not in hits:
            hits.append(v)
    return " / ".join(hits[:3])


def role_from_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local = email.split("@", 1)[0].lower()
    local = re.sub(r"[\d._\-]+", " ", local)
    parts = [p for p in local.split() if p]
    for p in parts:
        if p in EMAIL_ROLE_ZH:
            return EMAIL_ROLE_ZH[p]
    # sales-asia 之类
    for key, val in EMAIL_ROLE_ZH.items():
        if key in local:
            return val
    return ""


def extract_contact_person(text: str) -> tuple[str, str]:
    """从正文猜联系人姓名 + 职位。返回 (name, title)。"""
    if not text:
        return "", ""
    sample = text[:8000]

    m = CONTACT_LINE_RE.search(sample)
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .,;，。")
        if 2 <= len(name) <= 40 and not re.search(r"http|www|@|\d{5,}", name):
            return name, ""

    for pat in TITLE_PATTERNS:
        m = pat.search(sample)
        if not m:
            continue
        g1, g2 = (m.group(1) or "").strip(), (m.group(2) or "").strip() if m.lastindex and m.lastindex >= 2 else ""
        # 模式1: Title + Name
        if re.search(
            r"(?i)manager|director|ceo|owner|founder|president|销售|采购|经理|老板",
            g1,
        ):
            title, name = g1, g2
        else:
            name, title = g1, g2
        name = re.sub(r"\s+", " ", name).strip(" .,;，。")
        title = re.sub(r"\s+", " ", title).strip(" .,;，。")
        if name and (len(name.split()) >= 2 or re.search(r"[\u4e00-\u9fa5]", name)):
            if not re.search(r"http|www|@|contact|email|phone", name, re.I):
                return name[:40], title[:40]
        if title and not name:
            return "", title[:40]
    return "", ""


def build_profile(
    *,
    company: str = "",
    keyword: str = "",
    industry: str = "",
    shop_type: str = "",
    email: str = "",
    title_hint: str = "",
    page_text: str = "",
    source: str = "",
    city: str = "",
    country: str = "",
) -> dict[str, str]:
    """生成统一画像字段。"""
    parts = []
    osm_l = osm_type_label(shop_type)
    kw_l = keyword_business_type(keyword, industry)
    if osm_l:
        parts.append(osm_l)
    if kw_l:
        for p in kw_l.split(" / "):
            if p and p not in parts:
                parts.append(p)
    if industry and industry not in ("yes", "node", "way") and industry not in "".join(parts):
        # 英文 industry 转一嘴
        ind_zh = keyword_business_type(industry, "") or industry
        if ind_zh not in parts:
            parts.append(ind_zh)
    if keyword and not parts:
        parts.append(f"与「{keyword}」相关商户/公司")

    business_type = " · ".join(parts[:4]) if parts else (industry or keyword or "待标注业态")

    contact_name, contact_title = extract_contact_person(page_text)
    if not contact_title:
        contact_title = role_from_email(email)
    if title_hint and not contact_title:
        contact_title = title_hint

    # 一句话描述
    where = " · ".join(x for x in [city, country] if x)
    desc_bits = [company or "未知主体"]
    if business_type:
        desc_bits.append(f"业态：{business_type}")
    if where:
        desc_bits.append(f"地区：{where}")
    if contact_name or contact_title:
        who = " ".join(x for x in [contact_title, contact_name] if x)
        desc_bits.append(f"联系人：{who}")
    if source:
        desc_bits.append(f"来源：{source}")
    description = "｜".join(desc_bits)

    return {
        "business_type": business_type[:120],
        "contact_name": contact_name[:80],
        "contact_title": contact_title[:80],
        "description": description[:300],
        "industry": (industry or shop_type or keyword or "")[:80],
    }


def has_reachable_contact(
    email: str = "",
    whatsapp: str = "",
    phone: str = "",
    emails: Optional[list] = None,
    whatsapps: Optional[list] = None,
    phones: Optional[list] = None,
) -> bool:
    """是否具备可跟进联系方式（邮箱 / WhatsApp / 电话 任一）。"""
    if (email or "").strip():
        return True
    if (whatsapp or "").strip():
        return True
    if (phone or "").strip():
        return True
    if emails and any(str(x).strip() for x in emails):
        return True
    if whatsapps and any(str(x).strip() for x in whatsapps):
        return True
    if phones and any(str(x).strip() for x in phones):
        return True
    return False
