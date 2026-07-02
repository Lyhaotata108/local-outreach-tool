"""
本地 seen_leads 工具。

用途：
- 记录所有已经抓到过/检查过的商户
- 不管线索最后是否进入 leads_output，后续都能参与去重
- 防止被评分筛选掉、没有邮箱、或后续删除CSV后又反复抓到同一批商户
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SEEN_LEADS_FILENAME = "seen_leads.csv"
SEEN_LEADS_FIELDNAMES = [
    "lead_id",
    "business_name",
    "website",
    "email",
    "city",
    "state",
    "industry",
    "status",
    "source",
    "last_seen_at",
]


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def normalize_website(website: str) -> str:
    raw = (website or "").strip().lower()
    if not raw:
        return ""

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    netloc = parsed.netloc.replace("www.", "", 1)
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def get_seen_leads_path(base_dir: Path) -> Path:
    return Path(base_dir) / SEEN_LEADS_FILENAME


def ensure_seen_leads_file(base_dir: Path) -> Path:
    path = get_seen_leads_path(base_dir)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SEEN_LEADS_FIELDNAMES)
            writer.writeheader()
    return path


def load_seen_keys(base_dir: Path) -> dict[str, set[str]]:
    path = get_seen_leads_path(base_dir)
    keys = {
        "lead_ids": set(),
        "websites": set(),
        "emails": set(),
    }

    if not path.exists():
        return keys

    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lead_id = (row.get("lead_id") or "").strip()
                website = normalize_website(row.get("website", ""))
                email = normalize_email(row.get("email", ""))

                if lead_id:
                    keys["lead_ids"].add(lead_id)
                if website:
                    keys["websites"].add(website)
                if email:
                    keys["emails"].add(email)
    except (OSError, csv.Error, UnicodeDecodeError):
        return keys

    return keys


def add_seen_lead(
    base_dir: Path,
    lead_id: str = "",
    business_name: str = "",
    website: str = "",
    email: str = "",
    city: str = "",
    state: str = "",
    industry: str = "",
    status: str = "seen",
    source: str = "scrape_leads",
) -> bool:
    """
    添加一条 seen_leads 记录。
    返回 True 表示新增；False 表示 lead_id / website / email 已经存在，不重复写入。
    """
    path = ensure_seen_leads_file(base_dir)
    existing = load_seen_keys(base_dir)

    normalized_email = normalize_email(email)
    normalized_website = normalize_website(website)
    lead_id = (lead_id or "").strip()

    if lead_id and lead_id in existing["lead_ids"]:
        return False
    if normalized_website and normalized_website in existing["websites"]:
        return False
    if normalized_email and normalized_email in existing["emails"]:
        return False

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SEEN_LEADS_FIELDNAMES)
        writer.writerow({
            "lead_id": lead_id,
            "business_name": business_name or "",
            "website": normalized_website,
            "email": normalized_email,
            "city": city or "",
            "state": state or "",
            "industry": industry or "",
            "status": status or "seen",
            "source": source or "scrape_leads",
            "last_seen_at": datetime.now().isoformat(timespec="seconds"),
        })

    return True
