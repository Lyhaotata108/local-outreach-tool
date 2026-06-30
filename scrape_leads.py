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
from urllib.parse import urlparse

import requests

# ============================================================
# 配置
# ============================================================

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
    r"\.png$", r"\.jpg$", r"\.jpeg$", r"\.gif$", r"\.svg$",  # 误抓到图片文件名
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


# ============================================================
# Lead ID：稳定唯一ID，后续诊断链接和CSV对照都靠它
# ============================================================

def normalize_website_for_id(website: str) -> str:
    """
    归一化网站地址，避免 http/https、末尾斜杠、大小写导致同一家店生成不同 lead_id。
    """
    raw = (website or "").strip().lower()
    if not raw:
        return ""

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    netloc = parsed.netloc.replace("www.", "", 1)
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def generate_lead_id(business_name: str, website: str) -> str:
    """
    基于 business_name + website 生成稳定ID。

    选择 hashlib 而不是 uuid4 的原因：
    - 同一家商家重复抓取时，仍然能得到同一个 lead_id
    - CSV重新生成、行号变化，也不会影响追踪
    """
    normalized_name = " ".join((business_name or "").strip().lower().split())
    normalized_website = normalize_website_for_id(website)
    source = f"{normalized_name}|{normalized_website}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"lead_{digest}"


# ============================================================
# Step A: 用 Google Places API 搜索商家
# ============================================================

def search_places(industry: str, city: str, state: str, limit: int) -> list[dict]:
    """
    用 Places API (New) 的 searchText 接口搜索商家。
    返回字段：name, formattedAddress, websiteUri, internationalPhoneNumber
    """
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
        "maxResultCount": min(limit, 20),  # API 单次最多返回20条
    }

    resp = requests.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for place in data.get("places", []):
        website = place.get("websiteUri")
        if not website:
            continue  # 只要有网站的商家，没网站的没法抓邮箱

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
    """
    返回 'good'（可能是老板/个人邮箱）或 'generic'（info@/support@ 这类通用邮箱）
    优先发 good，generic 作为备选，不直接丢弃（总比没有强）
    """
    prefix = email.split("@")[0].lower()
    if prefix in GENERIC_EMAIL_PREFIXES:
        return "generic"
    return "good"


def extract_emails_from_website(url: str, timeout: int = 8) -> list[dict]:
    """
    访问网站首页（以及常见的 /contact /about 页面），提取邮箱并分类。
    返回 [{"email": "...", "quality": "good"|"generic"}]
    """
    pages_to_try = [url]
    # 尝试常见的联系页面路径，邮箱经常藏在这里而不是首页
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
            continue  # 单个页面失败不影响整体，继续试下一个

        time.sleep(0.5)  # 避免请求过快被网站拦截

        if found_emails:
            break  # 找到了就不用继续试其他页面了

    result = []
    for email in found_emails:
        result.append({"email": email, "quality": classify_email_quality(email)})

    # 排序：good 排在 generic 前面，方便后续优先选用
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
    args = parser.parse_args()

    if not GOOGLE_PLACES_API_KEY:
        print("错误：未设置 GOOGLE_PLACES_API_KEY 环境变量")
        print("运行前先执行: export GOOGLE_PLACES_API_KEY='你的key'")
        return

    print(f"正在搜索 {args.city}, {args.state} 的 {args.industry} 商家（最多{args.limit}家）...")
    places = search_places(args.industry, args.city, args.state, args.limit)
    print(f"找到 {len(places)} 家有网站的商家，开始抓取邮箱...\n")

    rows = []
    seen_lead_ids = set()

    for i, place in enumerate(places, 1):
        print(f"[{i}/{len(places)}] {place['business_name']} - {place['website']}")
        emails = extract_emails_from_website(place["website"])

        if not emails:
            print("    未找到邮箱，跳过")
            continue

        if place["lead_id"] in seen_lead_ids:
            print(f"    重复线索，跳过: {place['lead_id']}")
            continue
        seen_lead_ids.add(place["lead_id"])

        best_email = emails[0]  # 已排序，good优先
        print(f"    Lead ID: {place['lead_id']}")
        print(f"    找到邮箱: {best_email['email']} (质量: {best_email['quality']})")

        rows.append({
            **place,
            "email": best_email["email"],
            "email_quality": best_email["quality"],
            "all_emails_found": "; ".join(e["email"] for e in emails),
            "status": "pending",  # pending / sent / skipped / failed
            "sent_at": "",        # send_emails.py 发送成功后写入
            "scraped_at": datetime.now().isoformat(timespec="seconds"),
        })

    if not rows:
        print("\n没有抓到任何带邮箱的商家，结束。")
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
    print(f"\n完成！共 {len(rows)} 条带邮箱的线索（{good_count} 个高质量邮箱）")
    print(f"已保存到: {output_file}")
    print("\n下一步：检查这份名单，确认无误后运行 send_emails.py 来发信")


if __name__ == "__main__":
    main()
