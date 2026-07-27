"""SQLite 线索库"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "leads.db"
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _lock:
        conn = get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL DEFAULT '',
                    contact_name TEXT DEFAULT '',
                    country TEXT DEFAULT '',
                    city TEXT DEFAULT '',
                    industry TEXT DEFAULT '',
                    website TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    emails_json TEXT DEFAULT '[]',
                    phone TEXT DEFAULT '',
                    phones_json TEXT DEFAULT '[]',
                    whatsapp TEXT DEFAULT '',
                    whatsapps_json TEXT DEFAULT '[]',
                    linkedin TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    source_url TEXT DEFAULT '',
                    keywords TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    status TEXT DEFAULT 'new',
                    score INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                -- 不用 website+email+whatsapp 联合唯一：空字符串会导致大量冲突
                -- 去重在 upsert_lead 里按非空字段逻辑处理

                CREATE TABLE IF NOT EXISTS search_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    country TEXT DEFAULT '',
                    industry TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    result_count INTEGER DEFAULT 0,
                    error TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    finished_at TEXT DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_leads_country ON leads(country);
                CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
                CREATE INDEX IF NOT EXISTS idx_leads_whatsapp ON leads(whatsapp);
                CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
                CREATE INDEX IF NOT EXISTS idx_leads_industry ON leads(industry);
                """
            )
            conn.commit()
        finally:
            conn.close()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("emails_json", "phones_json", "whatsapps_json"):
        raw = d.get(key) or "[]"
        try:
            d[key.replace("_json", "")] = json.loads(raw)
        except Exception:
            d[key.replace("_json", "")] = []
    return d


def upsert_lead(data: dict[str, Any]) -> int:
    """插入或更新线索，返回 id。"""
    now = _now()
    emails = data.get("emails") or ([] if not data.get("email") else [data["email"]])
    phones = data.get("phones") or ([] if not data.get("phone") else [data["phone"]])
    whatsapps = data.get("whatsapps") or (
        [] if not data.get("whatsapp") else [data["whatsapp"]]
    )
    email = (data.get("email") or (emails[0] if emails else "")).strip().lower()
    whatsapp = (data.get("whatsapp") or (whatsapps[0] if whatsapps else "")).strip()
    website = (data.get("website") or "").strip().rstrip("/")
    company = (data.get("company") or "").strip() or website or email or "未知公司"

    # 去重键：优先 website+email，其次 website+whatsapp，再次 email
    with _lock:
        conn = get_conn()
        try:
            existing = None
            # 只对「有实质联系方式」的记录去重；纯空联系方式每次可保留备注不同的记录
            if email:
                existing = conn.execute(
                    "SELECT id FROM leads WHERE email=? AND email!='' LIMIT 1",
                    (email,),
                ).fetchone()
            if not existing and whatsapp:
                existing = conn.execute(
                    "SELECT id FROM leads WHERE whatsapp=? AND whatsapp!='' LIMIT 1",
                    (whatsapp,),
                ).fetchone()
            if not existing and website and email:
                existing = conn.execute(
                    "SELECT id FROM leads WHERE website=? AND email=? AND email!='' LIMIT 1",
                    (website, email),
                ).fetchone()
            # 无 email/whatsapp 时：用 source_url + notes 前缀弱去重，避免刷屏
            notes = (data.get("notes") or "")[:180]
            source_url = (data.get("source_url") or "")[:200]
            if not existing and not email and not whatsapp and notes:
                existing = conn.execute(
                    """
                    SELECT id FROM leads
                    WHERE email='' AND whatsapp='' AND source_url=? AND notes=?
                    LIMIT 1
                    """,
                    (source_url, data.get("notes") or ""),
                ).fetchone()

            payload = {
                "company": company,
                "contact_name": data.get("contact_name") or "",
                "country": data.get("country") or "",
                "city": data.get("city") or "",
                "industry": data.get("industry") or "",
                "website": website,
                "email": email,
                "emails_json": json.dumps(list(dict.fromkeys(emails)), ensure_ascii=False),
                "phone": data.get("phone") or (phones[0] if phones else ""),
                "phones_json": json.dumps(list(dict.fromkeys(phones)), ensure_ascii=False),
                "whatsapp": whatsapp,
                "whatsapps_json": json.dumps(
                    list(dict.fromkeys(whatsapps)), ensure_ascii=False
                ),
                "linkedin": data.get("linkedin") or "",
                "source": data.get("source") or "",
                "source_url": data.get("source_url") or "",
                "keywords": data.get("keywords") or "",
                "notes": data.get("notes") or "",
                "status": data.get("status") or "new",
                "score": int(data.get("score") or 0),
                "tags": data.get("tags") or "",
                "updated_at": now,
            }

            if existing:
                lid = existing["id"]
                # 合并 notes / 补充空字段
                old = conn.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
                if old:
                    for k in (
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
                        "tags",
                    ):
                        if not payload[k] and old[k]:
                            payload[k] = old[k]
                    # 合并邮箱列表
                    try:
                        old_emails = json.loads(old["emails_json"] or "[]")
                    except Exception:
                        old_emails = []
                    try:
                        old_wa = json.loads(old["whatsapps_json"] or "[]")
                    except Exception:
                        old_wa = []
                    try:
                        old_phones = json.loads(old["phones_json"] or "[]")
                    except Exception:
                        old_phones = []
                    merged_e = list(dict.fromkeys(old_emails + emails))
                    merged_w = list(dict.fromkeys(old_wa + whatsapps))
                    merged_p = list(dict.fromkeys(old_phones + phones))
                    payload["emails_json"] = json.dumps(merged_e, ensure_ascii=False)
                    payload["whatsapps_json"] = json.dumps(merged_w, ensure_ascii=False)
                    payload["phones_json"] = json.dumps(merged_p, ensure_ascii=False)
                    if not payload["email"] and merged_e:
                        payload["email"] = merged_e[0]
                    if not payload["whatsapp"] and merged_w:
                        payload["whatsapp"] = merged_w[0]
                    if old["notes"] and payload["notes"] and old["notes"] not in payload["notes"]:
                        payload["notes"] = (old["notes"] + "\n" + payload["notes"]).strip()
                    elif old["notes"] and not payload["notes"]:
                        payload["notes"] = old["notes"]
                    if (old["score"] or 0) > payload["score"]:
                        payload["score"] = old["score"]

                sets = ", ".join(f"{k}=?" for k in payload)
                conn.execute(
                    f"UPDATE leads SET {sets} WHERE id=?",
                    (*payload.values(), lid),
                )
                conn.commit()
                return lid

            cols = list(payload.keys()) + ["created_at"]
            vals = list(payload.values()) + [now]
            placeholders = ",".join("?" for _ in cols)
            cur = conn.execute(
                f"INSERT INTO leads ({','.join(cols)}) VALUES ({placeholders})",
                vals,
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def list_leads(
    q: str = "",
    country: str = "",
    industry: str = "",
    status: str = "",
    has_email: Optional[bool] = None,
    has_whatsapp: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        clauses.append(
            "(company LIKE ? OR email LIKE ? OR whatsapp LIKE ? OR website LIKE ? OR notes LIKE ? OR keywords LIKE ? OR contact_name LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like] * 7)
    if country:
        clauses.append("country LIKE ?")
        params.append(f"%{country}%")
    if industry:
        clauses.append("industry LIKE ?")
        params.append(f"%{industry}%")
    if status:
        clauses.append("status=?")
        params.append(status)
    if has_email is True:
        clauses.append("email != ''")
    elif has_email is False:
        clauses.append("email = ''")
    if has_whatsapp is True:
        clauses.append("whatsapp != ''")
    elif has_whatsapp is False:
        clauses.append("whatsapp = ''")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _lock:
        conn = get_conn()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM leads {where}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM leads {where} ORDER BY score DESC, updated_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            return [row_to_dict(r) for r in rows], int(total)
        finally:
            conn.close()


def get_lead(lead_id: int) -> Optional[dict]:
    with _lock:
        conn = get_conn()
        try:
            row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
            return row_to_dict(row) if row else None
        finally:
            conn.close()


def update_lead_fields(lead_id: int, fields: dict[str, Any]) -> bool:
    allowed = {
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
        "notes",
        "status",
        "score",
        "tags",
        "keywords",
    }
    data = {k: v for k, v in fields.items() if k in allowed}
    if not data:
        return False
    data["updated_at"] = _now()
    with _lock:
        conn = get_conn()
        try:
            sets = ", ".join(f"{k}=?" for k in data)
            cur = conn.execute(
                f"UPDATE leads SET {sets} WHERE id=?",
                (*data.values(), lead_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def delete_lead(lead_id: int) -> bool:
    with _lock:
        conn = get_conn()
        try:
            cur = conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def stats() -> dict[str, Any]:
    with _lock:
        conn = get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
            with_email = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE email!=''"
            ).fetchone()["c"]
            with_wa = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE whatsapp!=''"
            ).fetchone()["c"]
            with_both = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE email!='' AND whatsapp!=''"
            ).fetchone()["c"]
            by_country = conn.execute(
                """
                SELECT country, COUNT(*) AS c FROM leads
                WHERE country!='' GROUP BY country ORDER BY c DESC LIMIT 20
                """
            ).fetchall()
            by_status = conn.execute(
                "SELECT status, COUNT(*) AS c FROM leads GROUP BY status ORDER BY c DESC"
            ).fetchall()
            by_industry = conn.execute(
                """
                SELECT industry, COUNT(*) AS c FROM leads
                WHERE industry!='' GROUP BY industry ORDER BY c DESC LIMIT 15
                """
            ).fetchall()
            return {
                "total": total,
                "with_email": with_email,
                "with_whatsapp": with_wa,
                "with_both": with_both,
                "by_country": [dict(r) for r in by_country],
                "by_status": [dict(r) for r in by_status],
                "by_industry": [dict(r) for r in by_industry],
            }
        finally:
            conn.close()


def create_job(query: str, country: str, industry: str) -> int:
    with _lock:
        conn = get_conn()
        try:
            cur = conn.execute(
                """
                INSERT INTO search_jobs (query, country, industry, status, created_at)
                VALUES (?,?,?,?,?)
                """,
                (query, country, industry, "running", _now()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def finish_job(job_id: int, result_count: int, error: str = "") -> None:
    with _lock:
        conn = get_conn()
        try:
            conn.execute(
                """
                UPDATE search_jobs SET status=?, result_count=?, error=?, finished_at=?
                WHERE id=?
                """,
                ("error" if error else "done", result_count, error, _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()


def list_jobs(limit: int = 20) -> list[dict]:
    with _lock:
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM search_jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def export_rows(
    country: str = "",
    industry: str = "",
    status: str = "",
    has_email: Optional[bool] = None,
    has_whatsapp: Optional[bool] = None,
) -> list[dict]:
    rows, _ = list_leads(
        country=country,
        industry=industry,
        status=status,
        has_email=has_email,
        has_whatsapp=has_whatsapp,
        limit=50000,
        offset=0,
    )
    return rows
