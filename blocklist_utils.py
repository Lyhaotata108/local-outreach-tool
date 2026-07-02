"""
本地 blocklist 工具。

用途：
- 记录明确不应继续联系的商户、邮箱或网站
- 抓取和发送前都可以用它判断是否应该跳过
- blocklist.csv 只保存在本地，不需要上传到 GitHub
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

BLOCKLIST_FILENAME = "blocklist.csv"
BLOCKLIST_FIELDNAMES = [
    "email",
    "website",
    "business_name",
    "reason",
    "blocked_at",
    "source",
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


def get_blocklist_path(base_dir: Path) -> Path:
    return Path(base_dir) / BLOCKLIST_FILENAME


def ensure_blocklist_file(base_dir: Path) -> Path:
    path = get_blocklist_path(base_dir)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=BLOCKLIST_FIELDNAMES)
            writer.writeheader()
    return path


def load_blocklist(base_dir: Path) -> dict[str, set[str]]:
    path = get_blocklist_path(base_dir)
    result = {
        "emails": set(),
        "websites": set(),
    }

    if not path.exists():
        return result

    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = normalize_email(row.get("email", ""))
                website = normalize_website(row.get("website", ""))
                if email:
                    result["emails"].add(email)
                if website:
                    result["websites"].add(website)
    except (OSError, csv.Error, UnicodeDecodeError):
        return result

    return result


def is_blocked(email: str = "", website: str = "", base_dir: Path | None = None) -> tuple[bool, str]:
    base_dir = base_dir or Path(__file__).resolve().parent
    blocklist = load_blocklist(base_dir)

    normalized_email = normalize_email(email)
    normalized_website = normalize_website(website)

    if normalized_email and normalized_email in blocklist["emails"]:
        return True, "blocked_email"
    if normalized_website and normalized_website in blocklist["websites"]:
        return True, "blocked_website"
    return False, ""


def add_to_blocklist(
    base_dir: Path,
    email: str = "",
    website: str = "",
    business_name: str = "",
    reason: str = "manual_do_not_contact",
    source: str = "panel",
) -> bool:
    """
    添加一条 blocklist 记录。
    返回 True 表示新增；False 表示邮箱/网站已经存在，不重复写入。
    """
    path = ensure_blocklist_file(base_dir)

    normalized_email = normalize_email(email)
    normalized_website = normalize_website(website)
    existing = load_blocklist(base_dir)

    if normalized_email and normalized_email in existing["emails"]:
        return False
    if normalized_website and normalized_website in existing["websites"]:
        return False

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BLOCKLIST_FIELDNAMES)
        writer.writerow({
            "email": normalized_email,
            "website": normalized_website,
            "business_name": business_name or "",
            "reason": reason or "manual_do_not_contact",
            "blocked_at": datetime.now().isoformat(timespec="seconds"),
            "source": source or "panel",
        })

    return True
