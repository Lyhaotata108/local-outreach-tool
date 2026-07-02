"""
Step 1: 抓取商家 + 网站上的邮箱，过滤邮箱质量，存到本地 CSV。
运行：python scrape_leads.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20

依赖：
  pip install requests
"""

import argparse
import csv
import hashlib
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

from seen_leads_utils import add_seen_lead, load_seen_keys

# ============================================================
# 配置
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
OUTPUT_DIR = "leads_output"

# 通用邮箱前缀黑名单 —— 这些大概率不是老板本人会看的邮箱，命中即降低优先级而非直接丢弃
GENERIC_EMAIL_PREFIXES = {
    "info", "support", "contact", "admin", "noreply", "no-reply",
    "hello", "help", "sales", "office", "team", "service", "webmaster",
    "marketing", "press", "careers", "jobs", "billing",
}

# 明显是垃圾/占位邮箱的，直接丢弃
JUNK_EMAIL_PATTERNS = [
    r"example\.com$",
    r"sentry\.io$",
    r"wixpress\.com$",
    r"godaddy\.com$",
    r"\.png$", r"\.jpg$", r"\.jpeg$", r"\.gif$", r"\.svg$",
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


# ============================================================
# Lead ID：稳定唯一ID，后续诊断链接和CSV对照都靠它
# ============================================================

def normalize_website_for_id(website: str) -> str:
    """归一化网站地址，避免同一家店生成不同 lead_id。"""
    raw = (website or "").strip().lower()
    if not raw:
        return ""

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    netloc = parsed.netloc.replace("www.", "", 1)
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def generate_lead_id(business_name: str, website: str) -> str:
    """基于 business_name + website 生成稳定ID。"""
    normalized_name = " ".join((business_name or "").strip().lower().split())
    normalized_website = normalize_website_for_id(website)
    source = f"{normalized_name}|{normalized_website}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"lead_{digest}"


# ============================================================
# 历史去重：避免每天抓到同一批商家
# ============================================================

def load_existing_lead_keys(output_dir: str = OUTPUT_DIR) -> dict[str, set[str]]:
    """
    读取 seen_leads.csv + leads_output 下所有历史 CSV，建立去重索引。
    seen_leads.csv 会记录所有曾经检查过的商户，所以即使某些线索后续被评分过滤掉，也不会反复抓取。
    """
    keys = {
        "lead_ids": set(),
        "websites": set(),
        "emails": set(),
    }

    # 1. 优先读取全局 seen_leads.csv
    seen_keys = load_seen_keys(BASE_DIR)
    for key_name in keys:
        keys[key_name].update(seen_keys[key_name])

    # 2. 兼容旧版本：继续读取 leads_output 下历史 CSV
    if not os.path.isdir(output_dir):
        return keys

    for filename in os.listdir(output_dir):
        if not filename.lower().endswith(".csv"):
            continue

        path = os.path.join(output_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    business_name = row.get("business_name", "")
                    website = row.get("website", "")
                    lead_id = row.get("lead_id") or generate_lead_id(business_name, website)
                    normalized_website = normalize_website_for_id(website)
                    email = (row.get("email") or "").strip().lower()

                    if lead_id:
                        keys["lead_ids"].add(lead_id)
                    if normalized_website:
                        keys["websites"].add(normalized_website)
                    if email:
                        keys["emails"].add(email)
        except (OSError, csv.Error, UnicodeDecodeError):
            continue

    return keys


def record_seen_place(place: dict, args: argparse.Namespace, email: str = "", status: str = "seen") -> None:
    """把已经检查过的商户写入 seen_leads.csv，用于长期去重。"""
    add_seen_lead(
        BASE_DIR,
        lead_id=place.get("lead_id", ""),
        business_name=place.get("business_name", ""),
        website=place.get("website", ""),
        email=email,
        city=args.city,
        state=args.state,
        industry=args.industry,
        status=status,
        source="scrape_leads",
    )


def is_existing_place(place: dict, existing_keys: dict[str, set[str]]) -> bool:
    """判断 Google Places 返回的商家是否已经在历史记录中出现过。"""
    normalized_website = normalize_website_for_id(place.get("website", ""))
    return (
        place.get("lead_id") in existing_keys["lead_ids"]
        or (normalized_website and normalized_website in existing_keys["websites"])
    )


def has_existing_email(emails: list[dict], existing_keys: dict[str, set[str]]) -> bool:
    """判断本次抓到的邮箱是否已经出现在历史记录中。"""
    for item in emails:
        email = (item.get("email") or "").strip().lower()
        if email and email in existing_keys["emails"]:
            return True
    return False


# ============================================================
# Step A: 用 Google Places API 搜索商家
# ============================================================

def search_places(industry: str, city: str, state: str, limit: int) -> list[dict]:
    """用 Places API (New) 的 searchText 接口搜索商家。"""
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,"
            "places.websiteUri,places.internationalPhoneNumber,"
            "places.rating,places.userRatingCount"
        ),
    }
    body = {
        "textQuery": f"{industry} in {city}, {state}",
        "maxResultCount": min(limit, 20),
    }

    resp = requests.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for place in data.get("places", []):
        website = place.get("websiteUri")
        if not website:
            continue

        business_name = place.get("displayName", {}).get("text", "")
        results.append({
            "lead_id": generate_lead_id(business_name, website),
            "business_name": business_name,
            "address": place.get("formattedAddress", ""),
            "website": website,
            "phone": place.get("internationalPhoneNumber", ""),
            "google_rating": place.get("rating", ""),
            "review_count": place.get("userRatingCount", ""),
        })

    return results[:limit]


# ============================================================
# Step B: 抓取网站上的邮箱
# ============================================================

def is_junk_email(email: str) -> bool:
    email_lower = email.lower()
    for pattern in JUNK_EMAIL_PATTERNS:
        if re.search(pattern, email_lower):
            return True
    return False


def classify_email_quality(email: str) -> str:
    """返回 good 或 generic。"""
    prefix = email.split("@")[0].lower()
    if prefix in GENERIC_EMAIL_PREFIXES:
        return "generic"
    return "good"


def extract_emails_from_website(url: str, timeout: int = 8) -> list[dict]:
    """访问网站首页以及常见联系页面，提取邮箱并分类。"""
    pages_to_try = [url]
    for path in ["/contact", "/contact-us", "/about"]:
        pages_to_try.append(url.rstrip("/") + path)

    found_emails = set()

    for page_url in pages_to_try:
        try:
            resp = requests.get(
                page_url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; LeadResearchBot/1.0)"},
            )
            if resp.status_code != 200:
                continue
            matches = EMAIL_REGEX.findall(resp.text)
            for m in matches:
                if not is_junk_email(m):
                    found_emails.add(m.lower())
        except requests.RequestException:
            continue

        time.sleep(0.5)

        if found_emails:
            break

    result = []
    for email in found_emails:
        result.append({"email": email, "quality": classify_email_quality(email)})

    result.sort(key=lambda x: 0 if x["quality"] == "good" else 1)
    return result


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="抓取本地商家 + 网站邮箱，输出待发信名单")
    parser.add_argument("--industry", required=True, help="行业，例如 'massage spa'")
    parser.add_argument("--city", required=True, help="城市，例如 'Orlando'")
    parser.add_argument("--state", required=True, help="州，例如 'FL'")
    parser.add_argument("--limit", type=int, default=20, help="抓取商家数量上限")
    parser.add_argument("--no-dedupe-existing", action="store_true", help="关闭历史CSV/seen_leads去重，允许重复抓取旧线索")
    args = parser.parse_args()

    if not GOOGLE_PLACES_API_KEY:
        print("错误：未设置 GOOGLE_PLACES_API_KEY 环境变量")
        print("请在项目目录创建 .env，并写入: export GOOGLE_PLACES_API_KEY='你的key'")
        return

    existing_keys = {"lead_ids": set(), "websites": set(), "emails": set()}
    if not args.no_dedupe_existing:
        existing_keys = load_existing_lead_keys(OUTPUT_DIR)
        existing_total = len(existing_keys["lead_ids"])
        print(f"历史去重已开启：已读取 {existing_total} 条历史 lead_id（seen_leads.csv + leads_output）。")
        print("如果确实要重复抓旧线索，可加参数: --no-dedupe-existing\n")

    print(f"正在搜索 {args.city}, {args.state} 的 {args.industry} 商家（最多{args.limit}家）...")
    places = search_places(args.industry, args.city, args.state, args.limit)
    print(f"找到 {len(places)} 家有网站的商家，开始抓取邮箱...\n")

    rows = []
    seen_lead_ids_this_run = set()
    skipped_existing = 0
    skipped_no_email = 0
    skipped_same_run = 0
    skipped_existing_email = 0

    for i, place in enumerate(places, 1):
        print(f"[{i}/{len(places)}] {place['business_name']} - {place['website']}")

        if place["lead_id"] in seen_lead_ids_this_run:
            print(f"    本次重复线索，跳过: {place['lead_id']}")
            skipped_same_run += 1
            continue
        seen_lead_ids_this_run.add(place["lead_id"])

        if not args.no_dedupe_existing and is_existing_place(place, existing_keys):
            print(f"    历史重复线索，跳过: {place['lead_id']}")
            skipped_existing += 1
            continue

        emails = extract_emails_from_website(place["website"])

        if not emails:
            print("    未找到邮箱，记录到 seen_leads 后跳过")
            record_seen_place(place, args, email="", status="no_email")
            skipped_no_email += 1
            continue

        if not args.no_dedupe_existing and has_existing_email(emails, existing_keys):
            print("    邮箱已在历史记录中出现过，跳过")
            record_seen_place(place, args, email=emails[0].get("email", ""), status="duplicate_email")
            skipped_existing_email += 1
            continue

        best_email = emails[0]
        print(f"    Lead ID: {place['lead_id']}")
        print(f"    找到邮箱: {best_email['email']} (质量: {best_email['quality']})")

        record_seen_place(place, args, email=best_email["email"], status="captured")

        rows.append({
            **place,
            "email": best_email["email"],
            "email_quality": best_email["quality"],
            "all_emails_found": "; ".join(e["email"] for e in emails),
            "status": "pending",
            "sent_at": "",
            "scraped_at": datetime.now().isoformat(timespec="seconds"),
        })

    print("\n抓取统计：")
    print(f"  新增可用线索: {len(rows)}")
    print(f"  历史重复商家: {skipped_existing}")
    print(f"  历史重复邮箱: {skipped_existing_email}")
    print(f"  本次重复: {skipped_same_run}")
    print(f"  未找到邮箱: {skipped_no_email}")
    print("  seen_leads.csv 已记录本次检查过的商户，用于后续长期去重。")

    if not rows:
        print("\n没有抓到新的带邮箱商家，结束。")
        print("建议：换城市、换关键词，或临时加 --no-dedupe-existing 检查是否只是被历史去重过滤了。")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_city = re.sub(r"[^a-zA-Z0-9_-]+", "_", args.city.strip())
    output_file = os.path.join(
        OUTPUT_DIR, f"leads_{safe_city}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    fieldnames = [
        "lead_id", "business_name", "address", "website", "phone", "google_rating",
        "review_count", "email", "email_quality", "all_emails_found",
        "status", "sent_at", "scraped_at",
    ]
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    good_count = sum(1 for r in rows if r["email_quality"] == "good")
    print(f"\n完成！共 {len(rows)} 条新的带邮箱线索（{good_count} 个高质量邮箱）")
    print(f"已保存到: {output_file}")
    print("\n下一步：检查这份名单，确认无误后运行 send_emails.py 来发信")


if __name__ == "__main__":
    main()
