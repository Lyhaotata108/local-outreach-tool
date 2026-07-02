"""
自动读取本地 .env 后再运行 scrape_leads.py，并对新生成的 CSV 做增长机会评分、网站成熟度判断、话术角度分配和二次筛选。

用法示例：
python run_scrape.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20
python run_scrape.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20 --min-rating 4.0 --min-reviews 10 --min-growth-score 60
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

from blocklist_utils import is_blocked

BASE_DIR = Path(__file__).resolve().parent
LEADS_DIR = BASE_DIR / "leads_output"
WEBSITE_SCAN_TIMEOUT = 8

BOOKING_KEYWORDS = [
    "book now", "book online", "book appointment", "schedule", "appointment", "reserve", "reservation",
    "booking", "make an appointment", "online booking", "request appointment", "mindbody", "vagaro", "square appointments",
]
PHONE_CTA_KEYWORDS = [
    "tel:", "call now", "tap to call", "call us", "phone", "contact us",
]
REVIEW_KEYWORDS = [
    "review", "reviews", "testimonial", "testimonials", "google reviews", "happy clients", "rating",
]
OFFER_KEYWORDS = [
    "special", "specials", "coupon", "discount", "deal", "promotion", "gift card", "membership", "package", "packages",
]
GIFT_MEMBERSHIP_KEYWORDS = [
    "gift card", "gift cards", "membership", "memberships", "loyalty", "monthly plan", "package", "packages",
]
LOCAL_SEO_KEYWORDS = [
    "near me", "serving", "service area", "locations", "areas served", "city", "neighborhood",
]
CHAIN_KEYWORDS = [
    "massage envy", "hand and stone", "hand & stone", "elements massage", "the now massage",
    "spavia", "woodhouse", "massage heights", "franchise", "corporate", "careers",
]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        if line.startswith("export "):
            line = line[len("export "):].strip()

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and value:
            os.environ.setdefault(key, value)


def safe_city_name(city: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", city.strip())


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def parse_exclude_keywords(raw: str) -> list[str]:
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def find_new_csv_files(start_time: float, city: str) -> list[Path]:
    if not LEADS_DIR.exists():
        return []

    safe_city = safe_city_name(city)
    candidates = []
    for path in LEADS_DIR.glob("*.csv"):
        if path.stat().st_mtime < start_time:
            continue
        if path.name.startswith(f"leads_{safe_city}_"):
            candidates.append(path)

    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def contains_any(text: str, keywords: list[str]) -> bool:
    text = text.lower()
    return any(keyword in text for keyword in keywords)


def fetch_website_text(url: str) -> tuple[str, str]:
    if not url:
        return "", "no_website"

    try:
        resp = requests.get(
            url,
            timeout=WEBSITE_SCAN_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; GrowthCheckBot/1.0)"},
        )
        if resp.status_code >= 400:
            return "", f"http_{resp.status_code}"
        return resp.text.lower(), "ok"
    except requests.RequestException as exc:
        return "", f"request_error:{exc.__class__.__name__}"


def analyze_website(row: dict) -> dict[str, str]:
    website = str(row.get("website", "")).strip()
    business_name = str(row.get("business_name", "")).strip().lower()
    html_text, scan_status = fetch_website_text(website)
    combined = f"{business_name} {website.lower()} {html_text}"

    has_booking = contains_any(combined, BOOKING_KEYWORDS)
    has_phone_cta = contains_any(combined, PHONE_CTA_KEYWORDS)
    has_reviews = contains_any(combined, REVIEW_KEYWORDS)
    has_offer = contains_any(combined, OFFER_KEYWORDS)
    has_gift_membership = contains_any(combined, GIFT_MEMBERSHIP_KEYWORDS)
    has_local_seo = contains_any(combined, LOCAL_SEO_KEYWORDS)
    is_chain = contains_any(combined, CHAIN_KEYWORDS)

    link_count = html_text.count("href=") if html_text else 0
    has_multi_page_structure = link_count >= 12

    return {
        "website_has_booking": "yes" if has_booking else "no",
        "website_has_phone_cta": "yes" if has_phone_cta else "no",
        "website_has_reviews": "yes" if has_reviews else "no",
        "website_has_offer": "yes" if has_offer else "no",
        "website_has_gift_or_membership": "yes" if has_gift_membership else "no",
        "website_has_local_seo_signals": "yes" if has_local_seo else "no",
        "website_has_multi_page_structure": "yes" if has_multi_page_structure else "no",
        "is_likely_chain": "yes" if is_chain else "no",
        "website_scan_status": scan_status,
    }


def calculate_website_maturity_score(signals: dict[str, str]) -> tuple[int, str]:
    score = 0
    if signals.get("website_scan_status") == "ok":
        score += 10
    if signals.get("website_has_booking") == "yes":
        score += 20
    if signals.get("website_has_phone_cta") == "yes":
        score += 15
    if signals.get("website_has_reviews") == "yes":
        score += 15
    if signals.get("website_has_offer") == "yes":
        score += 15
    if signals.get("website_has_gift_or_membership") == "yes":
        score += 10
    if signals.get("website_has_multi_page_structure") == "yes":
        score += 10
    if signals.get("website_has_local_seo_signals") == "yes":
        score += 5

    score = max(0, min(100, score))
    if score >= 80:
        tier = "mature"
    elif score >= 55:
        tier = "developing"
    else:
        tier = "weak"
    return score, tier


def choose_outreach_angle(row: dict, signals: dict[str, str], maturity_score: int) -> str:
    rating = parse_float(row.get("google_rating", ""))
    reviews = parse_int(row.get("review_count", ""))

    if signals.get("is_likely_chain") == "yes":
        return "skip_chain_or_corporate"
    if maturity_score >= 80 and reviews >= 500:
        return "skip_mature_business"
    if reviews < 150 and rating >= 4.0:
        return "review_growth"
    if signals.get("website_has_booking") == "no" or signals.get("website_has_phone_cta") == "no":
        return "website_conversion"
    if signals.get("website_has_gift_or_membership") == "no" or signals.get("website_has_offer") == "no":
        return "repeat_booking"
    if signals.get("website_has_local_seo_signals") == "no":
        return "local_seo"
    return "general_growth"


def build_dynamic_intro(outreach_angle: str, signals: dict[str, str], maturity_score: int) -> str:
    if outreach_angle == "review_growth":
        if maturity_score >= 70:
            return "Your website already looks fairly polished, but there may still be room to grow reviews, local visibility, and trust compared with nearby competitors."
        return "You appear to have a solid customer foundation, but the review count and local trust signals may still have room to grow."

    if outreach_angle == "website_conversion":
        missing = []
        if signals.get("website_has_booking") == "no":
            missing.append("a clear booking path")
        if signals.get("website_has_phone_cta") == "no":
            missing.append("a strong mobile call button")
        detail = " and ".join(missing) or "a few conversion points"
        return f"You already have an online presence, but the website may be missing {detail}, which can matter a lot for mobile visitors ready to book."

    if outreach_angle == "repeat_booking":
        return "Your online presence has a good foundation, but I did not see many clear repeat-booking hooks such as packages, gift cards, memberships, or limited-time offers."

    if outreach_angle == "local_seo":
        return "Your business has a foundation online, but there may be room to strengthen local search visibility and make it clearer why customers nearby should choose you."

    if outreach_angle == "skip_mature_business":
        return "Your online presence already appears mature, so this is likely lower priority unless you are specifically looking for more review growth or local visibility."

    if outreach_angle == "skip_chain_or_corporate":
        return "This business appears to be part of a larger brand or corporate structure, so it may not be the best fit for small-business growth outreach."

    return "A lot of local service businesses lose customers not because of marketing budget, but because of small gaps in visibility, trust, website conversion, offers, or repeat-customer strategy."


def calculate_growth_score(row: dict, signals: dict[str, str], maturity_score: int, outreach_angle: str) -> tuple[int, str, str]:
    rating = parse_float(row.get("google_rating", ""))
    reviews = parse_int(row.get("review_count", ""))
    email_quality = str(row.get("email_quality", "")).strip().lower()
    website = str(row.get("website", "")).strip()

    score = 0
    reasons: list[str] = []

    if 4.0 <= rating <= 4.8:
        score += 20
        reasons.append("solid rating")
    elif rating > 4.8:
        score += 12
        reasons.append("very high rating")
    elif 3.8 <= rating < 4.0:
        score += 10
        reasons.append("acceptable rating")
    else:
        reasons.append("weak rating")

    if 10 <= reviews <= 300:
        score += 20
        reasons.append("review count still has growth room")
    elif 301 <= reviews <= 700:
        score += 10
        reasons.append("moderate review base")
    elif 5 <= reviews < 10:
        score += 8
        reasons.append("early review base")
    elif reviews > 700:
        score += 3
        reasons.append("already has many reviews")
    else:
        reasons.append("very few reviews")

    if website:
        score += 10
        reasons.append("has a website")

    if email_quality == "good":
        score += 15
        reasons.append("direct-looking email")
    elif email_quality:
        score += 6
        reasons.append("generic email")

    if signals.get("is_likely_chain") == "yes":
        score -= 25
        reasons.append("likely chain or corporate brand")
    else:
        score += 10
        reasons.append("likely independent business")

    if signals.get("website_scan_status") == "ok":
        if signals.get("website_has_booking") == "no":
            score += 12
            reasons.append("website may be missing a clear booking CTA")
        if signals.get("website_has_phone_cta") == "no":
            score += 8
            reasons.append("website may be missing a strong phone CTA")
        if signals.get("website_has_reviews") == "no":
            score += 6
            reasons.append("website may be missing reviews or testimonials")
        if signals.get("website_has_offer") == "no":
            score += 6
            reasons.append("website may be missing specials, packages, or offers")
    else:
        reasons.append("website could not be scanned")

    if maturity_score >= 80 and reviews >= 500:
        score -= 35
        reasons.append("mature website and large review base")
    elif maturity_score >= 80:
        score -= 10
        reasons.append("website already looks mature")
    elif maturity_score < 55:
        score += 8
        reasons.append("website maturity looks low")

    if outreach_angle == "review_growth":
        score += 8
        reasons.append("review growth angle")
    elif outreach_angle == "skip_mature_business":
        score = min(score, 35)
    elif outreach_angle == "skip_chain_or_corporate":
        score = min(score, 30)

    score = max(0, min(100, score))
    if score >= 80:
        tier = "hot"
    elif score >= 60:
        tier = "warm"
    elif score >= 40:
        tier = "low"
    else:
        tier = "skip"

    return score, tier, "; ".join(reasons[:7])


def enrich_row_with_growth(row: dict) -> dict:
    signals = analyze_website(row)
    maturity_score, maturity_tier = calculate_website_maturity_score(signals)
    outreach_angle = choose_outreach_angle(row, signals, maturity_score)
    dynamic_intro = build_dynamic_intro(outreach_angle, signals, maturity_score)
    score, tier, reason = calculate_growth_score(row, signals, maturity_score, outreach_angle)

    row.update(signals)
    row["website_maturity_score"] = str(maturity_score)
    row["website_maturity_tier"] = maturity_tier
    row["outreach_angle"] = outreach_angle
    row["dynamic_email_intro"] = dynamic_intro
    row["growth_score"] = str(score)
    row["growth_tier"] = tier
    row["growth_reason"] = reason
    return row


def row_matches_filters(
    row: dict,
    min_rating: float,
    min_reviews: int,
    require_good_email: bool,
    exclude_keywords: list[str],
    min_growth_score: int,
) -> tuple[bool, str]:
    rating = parse_float(row.get("google_rating", ""))
    reviews = parse_int(row.get("review_count", ""))
    email_quality = str(row.get("email_quality", "")).strip().lower()
    growth_score = parse_int(row.get("growth_score", ""))

    blocked, blocked_reason = is_blocked(email=row.get("email", ""), website=row.get("website", ""), base_dir=BASE_DIR)
    if blocked:
        return False, blocked_reason

    if row.get("outreach_angle") in {"skip_mature_business", "skip_chain_or_corporate"}:
        return False, row.get("outreach_angle")

    if min_rating > 0 and rating < min_rating:
        return False, "评分不足"

    if min_reviews > 0 and reviews < min_reviews:
        return False, "评论数不足"

    if min_growth_score > 0 and growth_score < min_growth_score:
        return False, "增长机会分不足"

    if require_good_email and email_quality != "good":
        return False, "非good邮箱"

    haystack = " ".join([
        str(row.get("business_name", "")),
        str(row.get("website", "")),
        str(row.get("address", "")),
        str(row.get("email", "")),
        str(row.get("growth_reason", "")),
        str(row.get("outreach_angle", "")),
    ]).lower()
    for keyword in exclude_keywords:
        if keyword and keyword in haystack:
            return False, f"命中排除词:{keyword}"

    return True, "保留"


def filter_csv_file(
    path: Path,
    min_rating: float,
    min_reviews: int,
    require_good_email: bool,
    exclude_keywords: list[str],
    min_growth_score: int,
) -> None:
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    growth_fields = [
        "growth_score", "growth_tier", "growth_reason",
        "website_maturity_score", "website_maturity_tier", "outreach_angle", "dynamic_email_intro",
        "website_has_booking", "website_has_phone_cta", "website_has_reviews", "website_has_offer",
        "website_has_gift_or_membership", "website_has_local_seo_signals", "website_has_multi_page_structure",
        "is_likely_chain", "website_scan_status",
    ]
    for field in growth_fields:
        if field not in fieldnames:
            fieldnames.append(field)

    kept_rows = []
    reason_counts: dict[str, int] = {}

    for row in rows:
        enriched = enrich_row_with_growth(row)
        keep, reason = row_matches_filters(
            enriched,
            min_rating=min_rating,
            min_reviews=min_reviews,
            require_good_email=require_good_email,
            exclude_keywords=exclude_keywords,
            min_growth_score=min_growth_score,
        )
        if keep:
            kept_rows.append(enriched)
        else:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)

    print("\n增长机会评分与筛选完成：")
    print(f"  文件: {path}")
    print(f"  原始线索: {len(rows)}")
    print(f"  保留线索: {len(kept_rows)}")
    if kept_rows:
        avg_score = sum(parse_int(r.get("growth_score", "0")) for r in kept_rows) / len(kept_rows)
        avg_maturity = sum(parse_int(r.get("website_maturity_score", "0")) for r in kept_rows) / len(kept_rows)
        print(f"  保留线索平均增长分: {avg_score:.1f}")
        print(f"  保留线索平均网站成熟度: {avg_maturity:.1f}")
    if reason_counts:
        print("  过滤原因：")
        for reason, count in reason_counts.items():
            print(f"    {reason}: {count}")


def build_scrape_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(BASE_DIR / "scrape_leads.py"),
        "--industry", args.industry,
        "--city", args.city,
        "--state", args.state,
        "--limit", str(args.limit),
    ]
    if args.no_dedupe_existing:
        cmd.append("--no-dedupe-existing")
    return cmd


def main() -> int:
    load_env_file(BASE_DIR / ".env")

    parser = argparse.ArgumentParser(description="自动读取 .env，运行抓取，并按增长机会筛选新CSV")
    parser.add_argument("--industry", required=True, help="行业，例如 massage spa")
    parser.add_argument("--city", required=True, help="城市，例如 Orlando")
    parser.add_argument("--state", required=True, help="州，例如 FL")
    parser.add_argument("--limit", type=int, default=20, help="抓取数量")
    parser.add_argument("--no-dedupe-existing", action="store_true", help="关闭历史CSV去重")
    parser.add_argument("--min-rating", type=float, default=0.0, help="最低 Google 评分；0 表示不筛选")
    parser.add_argument("--min-reviews", type=int, default=0, help="最低评论数；0 表示不筛选")
    parser.add_argument("--min-growth-score", type=int, default=0, help="最低增长机会分；0 表示只打分不筛选")
    parser.add_argument("--require-good-email", action="store_true", help="只保留 good 邮箱，过滤 info/support/contact 等通用邮箱")
    parser.add_argument("--exclude-keywords", default="", help="排除关键词，多个用英文逗号分隔，例如 franchise,corporate,chain")
    args = parser.parse_args()

    start_time = time.time() - 1
    cmd = build_scrape_command(args)
    print("运行抓取命令：")
    print(" ".join(cmd))
    print()

    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        env=os.environ.copy(),
        text=True,
    )

    if result.returncode != 0:
        return result.returncode

    new_csv_files = find_new_csv_files(start_time, args.city)
    if not new_csv_files:
        print("\n没有发现新 CSV，可能本次没有新增线索，或全部被历史去重过滤。")
        return 0

    exclude_keywords = parse_exclude_keywords(args.exclude_keywords)
    for csv_path in new_csv_files:
        filter_csv_file(
            csv_path,
            min_rating=args.min_rating,
            min_reviews=args.min_reviews,
            require_good_email=args.require_good_email,
            exclude_keywords=exclude_keywords,
            min_growth_score=args.min_growth_score,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
