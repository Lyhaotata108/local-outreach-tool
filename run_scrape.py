"""
自动读取本地 .env 后再运行 scrape_leads.py，并对新生成的 CSV 做二次筛选。

用法示例：
python run_scrape.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20
python run_scrape.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20 --min-rating 4.0 --min-reviews 20 --require-good-email
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

BASE_DIR = Path(__file__).resolve().parent
LEADS_DIR = BASE_DIR / "leads_output"


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


def row_matches_filters(
    row: dict,
    min_rating: float,
    min_reviews: int,
    require_good_email: bool,
    exclude_keywords: list[str],
) -> tuple[bool, str]:
    rating = parse_float(row.get("google_rating", ""))
    reviews = parse_int(row.get("review_count", ""))
    email_quality = str(row.get("email_quality", "")).strip().lower()

    if min_rating > 0 and rating < min_rating:
        return False, "评分不足"

    if min_reviews > 0 and reviews < min_reviews:
        return False, "评论数不足"

    if require_good_email and email_quality != "good":
        return False, "非good邮箱"

    haystack = " ".join([
        str(row.get("business_name", "")),
        str(row.get("website", "")),
        str(row.get("address", "")),
        str(row.get("email", "")),
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
) -> None:
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    kept_rows = []
    reason_counts: dict[str, int] = {}

    for row in rows:
        keep, reason = row_matches_filters(row, min_rating, min_reviews, require_good_email, exclude_keywords)
        if keep:
            kept_rows.append(row)
        else:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)

    print("\n筛选完成：")
    print(f"  文件: {path}")
    print(f"  原始线索: {len(rows)}")
    print(f"  保留线索: {len(kept_rows)}")
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

    parser = argparse.ArgumentParser(description="自动读取 .env，运行抓取，并按商户质量筛选新CSV")
    parser.add_argument("--industry", required=True, help="行业，例如 massage spa")
    parser.add_argument("--city", required=True, help="城市，例如 Orlando")
    parser.add_argument("--state", required=True, help="州，例如 FL")
    parser.add_argument("--limit", type=int, default=20, help="抓取数量")
    parser.add_argument("--no-dedupe-existing", action="store_true", help="关闭历史CSV去重")
    parser.add_argument("--min-rating", type=float, default=0.0, help="最低 Google 评分；0 表示不筛选")
    parser.add_argument("--min-reviews", type=int, default=0, help="最低评论数；0 表示不筛选")
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
    has_filters = args.min_rating > 0 or args.min_reviews > 0 or args.require_good_email or bool(exclude_keywords)
    if not has_filters:
        print("\n未启用额外筛选，保留原始新CSV。")
        return 0

    for csv_path in new_csv_files:
        filter_csv_file(
            csv_path,
            min_rating=args.min_rating,
            min_reviews=args.min_reviews,
            require_good_email=args.require_good_email,
            exclude_keywords=exclude_keywords,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
