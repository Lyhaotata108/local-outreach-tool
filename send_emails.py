"""
Step 2: 读取 scrape_leads.py 生成的 CSV，逐条人工确认后发送外联邮件。
运行：python send_emails.py --file leads_output/leads_Orlando_20260630.csv

配置：
  推荐在项目目录创建 .env。脚本会自动读取，不需要每次 source .env。

依赖：
  只用标准库 smtplib；邮件模板来自 email_templates.py
"""

import argparse
import csv
import hashlib
import os
import re
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from urllib.parse import urlencode, urlparse

from blocklist_utils import is_blocked
from email_templates import render_subject, render_body, render_html_body


# ============================================================
# 本地 .env 自动读取：支持 KEY=value 和 export KEY=value
# ============================================================

def load_env_file(path: Path) -> None:
    """读取项目目录下的 .env，避免每次打开新终端都要手动 source .env。"""
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


BASE_DIR = Path(__file__).resolve().parent
load_env_file(BASE_DIR / ".env")


# ============================================================
# 配置
# ============================================================

GMAIL_SENDER = os.environ.get("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
SENDER_DISPLAY_NAME = os.environ.get("SENDER_DISPLAY_NAME", "Foxiren Growth Check")

# 诊断工具的基础链接，发信时会自动拼接 lead_id 方便追踪
DIAGNOSTIC_BASE_URL = os.environ.get("DIAGNOSTIC_BASE_URL", "https://local-business-test.vercel.app/")

# 发信间隔（秒）—— 避免短时间内大量发信触发 Gmail 限流/垃圾邮件检测
SEND_DELAY_SECONDS = 8

# SMTP 连接超时时间（秒）—— 避免网络卡住时整个脚本长时间无响应
SMTP_TIMEOUT_SECONDS = 30

DO_NOT_SEND_STATUSES = {"do_not_contact", "not_interested", "replied", "converted"}


# ============================================================
# 商家名称清洗：去掉 Google Maps / 法人名称里常见的公司后缀
# 例如：Orlando Spa Oasis Limited Liability Company -> Orlando Spa Oasis
# ============================================================

LEGAL_SUFFIX_PATTERNS = [
    r"limited liability company",
    r"l\.l\.c\.",
    r"llc",
    r"incorporated",
    r"inc\.",
    r"inc",
    r"corporation",
    r"corp\.",
    r"corp",
    r"company",
    r"co\.",
    r"ltd\.",
    r"ltd",
]


def clean_business_name(name: str) -> str:
    """把法人后缀清掉，让标题和正文更像真人写的。"""
    cleaned = " ".join((name or "").strip().split())
    if not cleaned:
        return "your business"

    # 去掉末尾括号信息，例如 "ABC Spa (Orlando)" -> "ABC Spa"
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned).strip()

    changed = True
    while changed:
        before = cleaned
        for pattern in LEGAL_SUFFIX_PATTERNS:
            cleaned = re.sub(rf"\s*,?\s+{pattern}\.?\s*$", "", cleaned, flags=re.IGNORECASE).strip()
        changed = cleaned != before

    return cleaned or name or "your business"


# ============================================================
# Lead ID 兜底逻辑：正常情况下 scrape_leads.py 已经写入 lead_id
# ============================================================

def normalize_website_for_id(website: str) -> str:
    raw = (website or "").strip().lower()
    if not raw:
        return ""

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    netloc = parsed.netloc.replace("www.", "", 1)
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def generate_fallback_lead_id(business_name: str, website: str) -> str:
    """
    给旧CSV兜底生成稳定 lead_id。
    新CSV应该直接读取 scrape_leads.py 生成的 lead_id，而不是用行号现造。
    """
    normalized_name = " ".join((business_name or "").strip().lower().split())
    normalized_website = normalize_website_for_id(website)
    source = f"{normalized_name}|{normalized_website}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"lead_{digest}"


# ============================================================
# 发信核心函数
# ============================================================

def build_email_message(to_email: str, subject: str, text_body: str, html_body: str) -> MIMEMultipart:
    """构建同时包含纯文本备用版本和HTML按钮版本的邮件。"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((SENDER_DISPLAY_NAME, GMAIL_SENDER))
    msg["To"] = to_email

    # 顺序很重要：先plain，再html；支持HTML的邮箱客户端会优先展示最后的HTML版本
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_via_starttls(to_email: str, msg: MIMEMultipart) -> bool:
    """优先使用 Gmail 587 STARTTLS。"""
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER, [to_email], msg.as_string())
    return True


def send_via_ssl(to_email: str, msg: MIMEMultipart) -> bool:
    """587 端口连接失败时，回退使用 Gmail 465 SSL。"""
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER, [to_email], msg.as_string())
    return True


def send_email(to_email: str, subject: str, text_body: str, html_body: str) -> bool:
    """
    通过 Gmail SMTP 发送一封HTML邮件，返回是否成功。
    - 先尝试 587 STARTTLS
    - 如果网络/端口超时，再尝试 465 SSL
    - 如果仍失败，返回 False，不让整个脚本崩掉
    """
    msg = build_email_message(to_email, subject, text_body, html_body)

    try:
        return send_via_starttls(to_email, msg)
    except (smtplib.SMTPException, TimeoutError, OSError) as e:
        print(f"    587端口发送失败或连接超时: {e}")
        print("    正在尝试465 SSL端口...")

    try:
        return send_via_ssl(to_email, msg)
    except (smtplib.SMTPException, TimeoutError, OSError) as e:
        print(f"    465端口也失败: {e}")
        print("    这通常是网络、防火墙、VPN、公司/校园网络或运营商阻断SMTP导致。")
        return False


def build_diagnostic_link(lead_id: str, outreach_angle: str = "") -> str:
    """
    拼接诊断工具链接。
    注意：这里直接使用CSV里的 lead_id，不再使用CSV行号。
    """
    query_data = {"lead_id": lead_id}
    if outreach_angle:
        query_data["angle"] = outreach_angle
    query = urlencode(query_data)
    return f"{DIAGNOSTIC_BASE_URL}?{query}"


def extract_city_from_address(address: str) -> str:
    """从 Google Places formattedAddress 里尽量取城市名，用于邮件正文。"""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) >= 3:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return "your area"


def ensure_csv_columns(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """
    兼容旧CSV：
    - 如果没有 lead_id，基于商家名+网站补一个稳定ID
    - 如果没有 sent_at，补空值
    - 如果没有增长机会字段，补空值
    """
    if not rows:
        return rows, []

    fieldnames = list(rows[0].keys())

    required_fields = [
        "lead_id", "sent_at", "growth_score", "growth_tier", "growth_reason",
        "website_maturity_score", "website_maturity_tier", "outreach_angle", "dynamic_email_intro",
    ]
    for field in required_fields:
        if field not in fieldnames:
            if field == "lead_id":
                fieldnames.insert(0, field)
            elif field == "sent_at":
                insert_at = fieldnames.index("status") + 1 if "status" in fieldnames else len(fieldnames)
                fieldnames.insert(insert_at, field)
            else:
                fieldnames.append(field)

    for row in rows:
        if not row.get("lead_id"):
            row["lead_id"] = generate_fallback_lead_id(row.get("business_name", ""), row.get("website", ""))
        row.setdefault("sent_at", "")
        for field in required_fields:
            row.setdefault(field, "")

    return rows, fieldnames


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="读取CSV名单，逐条确认后发送外联邮件")
    parser.add_argument("--file", required=True, help="scrape_leads.py 生成的 CSV 文件路径")
    parser.add_argument("--industry", default="local service", help="行业名称，用于邮件正文里的 {industry} 变量")
    parser.add_argument("--auto-skip-generic", action="store_true",
                         help="自动跳过质量为 generic 的邮箱（info@/support@等），不询问")
    args = parser.parse_args()

    if not GMAIL_SENDER or not GMAIL_APP_PASSWORD:
        print("错误：未设置 GMAIL_SENDER 或 GMAIL_APP_PASSWORD 环境变量")
        print("请在项目目录创建 .env，并写入：")
        print("  export GMAIL_SENDER='youraccount@gmail.com'")
        print("  export GMAIL_APP_PASSWORD='xxxx xxxx xxxx xxxx'")
        print("  export SENDER_DISPLAY_NAME='Foxiren Growth Check'  # 可选")
        print("脚本会自动读取 .env，不需要每次 source .env。")
        return

    if not os.path.exists(args.file):
        print(f"错误：找不到文件 {args.file}")
        return

    with open(args.file, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("CSV为空，没有可发送记录")
        return

    rows, fieldnames = ensure_csv_columns(rows)

    pending_rows = [r for r in rows if r.get("status") == "pending"]
    print(f"共 {len(rows)} 条记录，其中 {len(pending_rows)} 条待发送\n")

    sent_count = 0
    skipped_count = 0

    for i, row in enumerate(pending_rows, 1):
        raw_business_name = row["business_name"]
        business_name = clean_business_name(raw_business_name)
        email = row["email"]
        quality = row["email_quality"]
        lead_id = row.get("lead_id") or generate_fallback_lead_id(raw_business_name, row.get("website", ""))
        outreach_angle = row.get("outreach_angle", "")
        custom_intro = row.get("dynamic_email_intro", "")
        row["lead_id"] = lead_id

        print(f"[{i}/{len(pending_rows)}] {raw_business_name}")
        if business_name != raw_business_name:
            print(f"    显示名称: {business_name}")
        print(f"    Lead ID: {lead_id}")
        print(f"    邮箱: {email} (质量: {quality})")
        if row.get("growth_score"):
            print(f"    增长分: {row.get('growth_score')} / {row.get('growth_tier')} / {outreach_angle}")
            print(f"    增长原因: {row.get('growth_reason', '')}")

        blocked, block_reason = is_blocked(email=email, website=row.get("website", ""), base_dir=BASE_DIR)
        if blocked:
            print(f"    已在 blocklist 中，自动跳过: {block_reason}\n")
            row["status"] = "do_not_contact"
            skipped_count += 1
            continue

        if row.get("status") in DO_NOT_SEND_STATUSES:
            print(f"    状态为 {row.get('status')}，自动跳过\n")
            skipped_count += 1
            continue

        if quality == "generic" and args.auto_skip_generic:
            print("    自动跳过（generic邮箱）\n")
            row["status"] = "skipped"
            skipped_count += 1
            continue

        diagnostic_link = build_diagnostic_link(lead_id, outreach_angle=outreach_angle)
        city = extract_city_from_address(row.get("address", ""))
        subject = render_subject(business_name, variant_index=i)
        body = render_body(
            business_name=business_name,
            city=city,
            diagnostic_url=diagnostic_link,
            industry=args.industry,
            custom_intro=custom_intro,
        )
        html_body = render_html_body(
            business_name=business_name,
            city=city,
            diagnostic_url=diagnostic_link,
            industry=args.industry,
            custom_intro=custom_intro,
        )

        print(f"    发件人显示: {SENDER_DISPLAY_NAME} <{GMAIL_SENDER}>")
        print(f"    标题: {subject}")
        print("    --- 正文预览（客户会优先看到HTML按钮版）---")
        print("    按钮文案: View My Free Growth Check")
        print(f"    按钮链接: {diagnostic_link}")
        print("    纯文本备用正文:")
        print("    " + body.replace("\n", "\n    "))
        print("    ----------------")

        choice = input("    发送这封邮件吗？[y]发送 / [n]跳过 / [q]退出: ").strip().lower()

        if choice == "q":
            print("\n用户中止，保存已处理的记录...")
            break
        elif choice == "n":
            row["status"] = "skipped"
            skipped_count += 1
            print("    已跳过\n")
            continue
        elif choice == "y":
            success = send_email(email, subject, body, html_body)
            if success:
                row["status"] = "sent"
                row["sent_at"] = datetime.now().isoformat(timespec="seconds")
                sent_count += 1
                print("    已发送 ✓\n")
            else:
                row["status"] = "failed"
                print("    发送失败，已标记；程序继续处理下一条\n")
            time.sleep(SEND_DELAY_SECONDS)
        else:
            print("    无效输入，按跳过处理\n")
            row["status"] = "skipped"
            skipped_count += 1

    # 把更新后的状态写回原CSV文件（覆盖）
    with open(args.file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n完成！本次发送 {sent_count} 封，跳过 {skipped_count} 封")
    print(f"状态已更新到: {args.file}")


if __name__ == "__main__":
    main()
