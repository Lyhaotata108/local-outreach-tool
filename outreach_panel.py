"""
本地可视化操作面板。
运行：streamlit run outreach_panel.py

功能：
- 从界面运行 run_scrape.py 抓取线索并做质量筛选
- 内置城市池，不用手动记城市
- 查看 leads_output 里的 CSV
- 统计 pending / sent / skipped / failed 状态
- 预览每条外联邮件
- 点击按钮发送单封邮件并回写 CSV 状态
- 用 lead_id 搜索线索
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

BASE_DIR = Path(__file__).resolve().parent
LEADS_DIR = BASE_DIR / "leads_output"

CITY_PRESETS: dict[str, list[tuple[str, str]]] = {
    "自定义城市": [],
    "第一轮测试：按摩/SPA 10城": [
        ("Orlando", "FL"), ("Tampa", "FL"), ("Miami", "FL"),
        ("Houston", "TX"), ("Dallas", "TX"), ("Austin", "TX"), ("Plano", "TX"),
        ("Los Angeles", "CA"), ("Irvine", "CA"), ("Pasadena", "CA"),
    ],
    "Florida：按摩/SPA 城市池": [
        ("Orlando", "FL"), ("Tampa", "FL"), ("Miami", "FL"), ("Jacksonville", "FL"),
        ("Fort Lauderdale", "FL"), ("St. Petersburg", "FL"), ("Kissimmee", "FL"),
        ("Sarasota", "FL"), ("West Palm Beach", "FL"), ("Naples", "FL"),
    ],
    "Texas：按摩/SPA 城市池": [
        ("Houston", "TX"), ("Dallas", "TX"), ("Austin", "TX"), ("San Antonio", "TX"),
        ("Plano", "TX"), ("Frisco", "TX"), ("Irving", "TX"), ("Arlington", "TX"),
        ("Fort Worth", "TX"), ("Sugar Land", "TX"),
    ],
    "California：按摩/SPA 城市池": [
        ("Los Angeles", "CA"), ("San Diego", "CA"), ("Irvine", "CA"), ("Pasadena", "CA"),
        ("Anaheim", "CA"), ("Torrance", "CA"), ("San Jose", "CA"), ("Fremont", "CA"),
        ("Sacramento", "CA"), ("Riverside", "CA"),
    ],
    "Northeast / Midwest：补充测试城市池": [
        ("Boston", "MA"), ("Quincy", "MA"), ("Edison", "NJ"), ("Jersey City", "NJ"),
        ("Flushing", "NY"), ("Philadelphia", "PA"), ("Chicago", "IL"), ("Naperville", "IL"),
        ("Ann Arbor", "MI"), ("Columbus", "OH"),
    ],
    "West / Mountain：补充测试城市池": [
        ("Las Vegas", "NV"), ("Henderson", "NV"), ("Phoenix", "AZ"), ("Scottsdale", "AZ"),
        ("Denver", "CO"), ("Aurora", "CO"), ("Salt Lake City", "UT"), ("Bellevue", "WA"),
        ("Portland", "OR"), ("Boise", "ID"),
    ],
}


# ============================================================
# 本地 .env 读取：支持 KEY=value 和 export KEY=value
# 不会上传密钥；只读取你本地项目目录里的 .env
# ============================================================

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


load_env_file(BASE_DIR / ".env")

# 必须在读取 .env 之后再导入 send_emails，否则里面的环境变量常量拿不到最新值
import send_emails as mailer  # noqa: E402


# ============================================================
# 页面基础配置
# ============================================================

st.set_page_config(
    page_title="Local Outreach Panel",
    page_icon="📬",
    layout="wide",
)

CUSTOM_CSS = """
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
.metric-card {
  padding: 14px 16px;
  border: 1px solid rgba(49, 51, 63, 0.15);
  border-radius: 12px;
  background: rgba(250, 250, 250, 0.75);
}
.small-muted { color: #6b7280; font-size: 13px; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def mask_value(value: str, keep: int = 4) -> str:
    if not value:
        return "未设置"
    if len(value) <= keep * 2:
        return "已设置"
    return f"{value[:keep]}...{value[-keep:]}"


def config_status() -> dict[str, str]:
    return {
        "GOOGLE_PLACES_API_KEY": os.environ.get("GOOGLE_PLACES_API_KEY", ""),
        "GMAIL_SENDER": os.environ.get("GMAIL_SENDER", ""),
        "GMAIL_APP_PASSWORD": os.environ.get("GMAIL_APP_PASSWORD", ""),
        "SENDER_DISPLAY_NAME": os.environ.get("SENDER_DISPLAY_NAME", "Foxiren Growth Check"),
    }


def get_csv_files() -> list[Path]:
    LEADS_DIR.mkdir(exist_ok=True)
    return sorted(LEADS_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)


@st.cache_data(show_spinner=False)
def load_csv_cached(path_str: str, mtime: float) -> pd.DataFrame:
    path = Path(path_str)
    df = pd.read_csv(path, dtype=str).fillna("")
    return ensure_dataframe_columns(df)


def load_csv(path: Path) -> pd.DataFrame:
    mtime = path.stat().st_mtime if path.exists() else 0
    return load_csv_cached(str(path), mtime).copy()


def save_csv(path: Path, df: pd.DataFrame) -> None:
    cleaned = df.drop(columns=["_row_id"], errors="ignore").fillna("")
    cleaned.to_csv(path, index=False, encoding="utf-8")
    load_csv_cached.clear()


def ensure_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["lead_id", "business_name", "address", "website", "phone", "email", "email_quality", "status", "sent_at"]:
        if col not in df.columns:
            df[col] = ""

    for idx, row in df.iterrows():
        if not row.get("status"):
            df.at[idx, "status"] = "pending"
        if not row.get("lead_id"):
            df.at[idx, "lead_id"] = mailer.generate_fallback_lead_id(
                str(row.get("business_name", "")),
                str(row.get("website", "")),
            )

    return df.fillna("")


def get_status_counts(df: pd.DataFrame) -> dict[str, int]:
    status = df.get("status", pd.Series(dtype=str)).fillna("").replace("", "pending")
    return {
        "total": int(len(df)),
        "pending": int((status == "pending").sum()),
        "sent": int((status == "sent").sum()),
        "skipped": int((status == "skipped").sum()),
        "failed": int((status == "failed").sum()),
    }


def row_label(row: pd.Series) -> str:
    name = str(row.get("business_name", "")) or "Unknown business"
    email = str(row.get("email", "")) or "no email"
    status = str(row.get("status", "pending")) or "pending"
    quality = str(row.get("email_quality", "")) or "unknown"
    return f"{name}  |  {email}  |  {quality}  |  {status}"


def render_email_for_row(row: pd.Series, industry: str) -> tuple[str, str, str, str, str]:
    raw_name = str(row.get("business_name", ""))
    business_name = mailer.clean_business_name(raw_name)
    lead_id = str(row.get("lead_id", "")) or mailer.generate_fallback_lead_id(raw_name, str(row.get("website", "")))
    city = mailer.extract_city_from_address(str(row.get("address", "")))
    diagnostic_link = mailer.build_diagnostic_link(lead_id)
    subject = mailer.render_subject(business_name, variant_index=0)
    text_body = mailer.render_body(
        business_name=business_name,
        city=city,
        diagnostic_url=diagnostic_link,
        industry=industry,
    )
    html_body = mailer.render_html_body(
        business_name=business_name,
        city=city,
        diagnostic_url=diagnostic_link,
        industry=industry,
    )
    return business_name, subject, text_body, html_body, diagnostic_link


def run_scrape_command(
    industry: str,
    city: str,
    state: str,
    limit: int,
    dedupe_existing: bool,
    min_rating: float,
    min_reviews: int,
    require_good_email: bool,
    exclude_keywords: str,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(BASE_DIR / "run_scrape.py"),
        "--industry", industry,
        "--city", city,
        "--state", state,
        "--limit", str(limit),
    ]
    if not dedupe_existing:
        cmd.append("--no-dedupe-existing")
    if min_rating > 0:
        cmd.extend(["--min-rating", str(min_rating)])
    if min_reviews > 0:
        cmd.extend(["--min-reviews", str(min_reviews)])
    if require_good_email:
        cmd.append("--require-good-email")
    if exclude_keywords.strip():
        cmd.extend(["--exclude-keywords", exclude_keywords.strip()])

    return subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )


# ============================================================
# 侧边栏：配置状态
# ============================================================

st.title("📬 Local Outreach Panel")
st.caption("本地外联工具操作面板：抓取线索、查看CSV、预览邮件、发送单封邮件、追踪 lead_id。")

with st.sidebar:
    st.header("配置状态")
    cfg = config_status()
    st.write("Google Places Key：", mask_value(cfg["GOOGLE_PLACES_API_KEY"]))
    st.write("Gmail Sender：", cfg["GMAIL_SENDER"] or "未设置")
    st.write("Gmail App Password：", "已设置" if cfg["GMAIL_APP_PASSWORD"] else "未设置")
    st.write("Sender Name：", cfg["SENDER_DISPLAY_NAME"] or "Foxiren Growth Check")

    st.divider()
    st.caption("配置文件路径")
    st.code(str(BASE_DIR / ".env"), language="text")
    st.caption("如果刚改了 .env，重启面板最稳。")


# ============================================================
# 主界面 Tabs
# ============================================================

tab_scrape, tab_csv, tab_send, tab_search = st.tabs([
    "① 抓取线索",
    "② 查看CSV",
    "③ 预览/发送邮件",
    "④ lead_id 搜索",
])


# ------------------------------------------------------------
# Tab 1: 抓取线索
# ------------------------------------------------------------

with tab_scrape:
    st.subheader("抓取本地商家")
    st.write("这里会调用 `run_scrape.py`，先抓取，再按商户质量筛选，输出仍然保存到 `leads_output/`。")

    preset_name = st.selectbox("城市池", list(CITY_PRESETS.keys()), index=1)
    preset_cities = CITY_PRESETS[preset_name]

    col_top1, col_top2, col_top3 = st.columns([1.5, 1, 1])
    with col_top1:
        industry = st.text_input("行业关键词", value="massage spa")
    with col_top2:
        limit = st.number_input("每个城市抓取数量", min_value=1, max_value=200, value=20, step=1)
    with col_top3:
        dedupe_existing = st.checkbox("启用历史CSV去重", value=True)

    with st.expander("商户质量筛选", expanded=True):
        enable_quality_filter = st.checkbox("启用质量筛选", value=True)
        f1, f2, f3, f4 = st.columns([1, 1, 1.2, 2])
        with f1:
            min_rating_input = st.number_input("最低评分", min_value=0.0, max_value=5.0, value=4.0, step=0.1)
        with f2:
            min_reviews_input = st.number_input("最低评论数", min_value=0, max_value=10000, value=10, step=5)
        with f3:
            require_good_input = st.checkbox("只保留 good 邮箱", value=False)
        with f4:
            exclude_keywords_input = st.text_input("排除关键词", value="", placeholder="多个用英文逗号分隔，例如 franchise,corporate")

        st.caption("建议前期不要太严格：最低评分 4.0、最低评论数 10、good邮箱不强制。筛太严会导致新CSV为空。")

    min_rating = float(min_rating_input) if enable_quality_filter else 0.0
    min_reviews = int(min_reviews_input) if enable_quality_filter else 0
    require_good_email = bool(require_good_input) if enable_quality_filter else False
    exclude_keywords = exclude_keywords_input if enable_quality_filter else ""

    if preset_cities:
        city_labels = [f"{city}, {state}" for city, state in preset_cities]
        selected_label = st.selectbox("选择城市", city_labels, index=0)
        selected_index = city_labels.index(selected_label)
        city, state = preset_cities[selected_index]
        batch_mode = st.checkbox("批量抓取整个城市池", value=False)
        target_cities = preset_cities if batch_mode else [(city, state)]
        st.caption(f"当前目标：{len(target_cities)} 个城市。历史去重开启后，已经抓过的商家会自动跳过。")
    else:
        col_city, col_state = st.columns([2, 1])
        with col_city:
            city = st.text_input("城市", value="Orlando")
        with col_state:
            state = st.text_input("州", value="FL")
        batch_mode = False
        target_cities = [(city, state)]

    if st.button("开始抓取", type="primary"):
        if not os.environ.get("GOOGLE_PLACES_API_KEY"):
            st.error("未检测到 GOOGLE_PLACES_API_KEY。请先在 .env 里配置，然后重启面板。")
        else:
            all_stdout: list[str] = []
            all_stderr: list[str] = []
            failed_count = 0

            progress = st.progress(0)
            status_box = st.empty()

            for idx, (run_city, run_state) in enumerate(target_cities, 1):
                status_box.info(f"正在抓取 {idx}/{len(target_cities)}：{run_city}, {run_state}")
                with st.spinner(f"正在抓取 {run_city}, {run_state}..."):
                    result = run_scrape_command(
                        industry,
                        run_city,
                        run_state,
                        int(limit),
                        dedupe_existing,
                        min_rating,
                        min_reviews,
                        require_good_email,
                        exclude_keywords,
                    )

                header = f"\n========== {run_city}, {run_state} =========="
                if result.stdout:
                    all_stdout.append(header + "\n" + result.stdout)
                if result.stderr:
                    all_stderr.append(header + "\n" + result.stderr)
                if result.returncode != 0:
                    failed_count += 1

                progress.progress(idx / len(target_cities))

            status_box.empty()
            if all_stdout:
                st.text_area("输出", "\n".join(all_stdout), height=360)
            if all_stderr:
                st.text_area("错误/警告", "\n".join(all_stderr), height=180)

            if failed_count == 0:
                st.success("抓取完成。去 ② 查看CSV 里选择最新文件。")
            else:
                st.error(f"有 {failed_count} 个城市抓取失败，请看错误输出。")


# ------------------------------------------------------------
# Tab 2 & 3 shared CSV selector
# ------------------------------------------------------------

csv_files = get_csv_files()


# ------------------------------------------------------------
# Tab 2: 查看CSV
# ------------------------------------------------------------

with tab_csv:
    st.subheader("查看线索 CSV")
    if not csv_files:
        st.info("还没有 CSV。先去 ① 抓取线索。")
    else:
        selected_csv = st.selectbox(
            "选择 CSV 文件",
            csv_files,
            format_func=lambda p: f"{p.name}  ·  {datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')}",
            key="csv_view_select",
        )
        df = load_csv(selected_csv)
        counts = get_status_counts(df)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total", counts["total"])
        c2.metric("Pending", counts["pending"])
        c3.metric("Sent", counts["sent"])
        c4.metric("Skipped", counts["skipped"])
        c5.metric("Failed", counts["failed"])

        col_a, col_b, col_c = st.columns([1, 1, 2])
        with col_a:
            status_filter = st.multiselect(
                "状态筛选",
                ["pending", "sent", "skipped", "failed"],
                default=["pending", "sent", "skipped", "failed"],
            )
        with col_b:
            quality_options = sorted([q for q in df["email_quality"].unique().tolist() if q])
            quality_filter = st.multiselect("邮箱质量", quality_options, default=quality_options)
        with col_c:
            keyword = st.text_input("搜索店名 / 邮箱 / lead_id", value="")

        filtered = df.copy()
        if status_filter:
            filtered = filtered[filtered["status"].replace("", "pending").isin(status_filter)]
        if quality_filter:
            filtered = filtered[filtered["email_quality"].isin(quality_filter)]
        if keyword.strip():
            kw = keyword.strip().lower()
            joined = filtered.astype(str).agg(" ".join, axis=1).str.lower()
            filtered = filtered[joined.str.contains(kw, na=False)]

        display_cols = [
            "lead_id", "business_name", "email", "email_quality", "status", "sent_at",
            "website", "phone", "google_rating", "review_count", "address",
        ]
        display_cols = [c for c in display_cols if c in filtered.columns]
        st.dataframe(filtered[display_cols], use_container_width=True, height=520)

        st.download_button(
            "下载当前CSV",
            data=selected_csv.read_bytes(),
            file_name=selected_csv.name,
            mime="text/csv",
        )


# ------------------------------------------------------------
# Tab 3: 预览/发送邮件
# ------------------------------------------------------------

with tab_send:
    st.subheader("预览并发送单封邮件")
    if not csv_files:
        st.info("还没有 CSV。先去 ① 抓取线索。")
    else:
        selected_csv_send = st.selectbox(
            "选择 CSV 文件",
            csv_files,
            format_func=lambda p: f"{p.name}  ·  {datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')}",
            key="csv_send_select",
        )
        send_df = load_csv(selected_csv_send)
        send_df["_row_id"] = send_df.index

        industry_send = st.text_input("邮件里的行业名称", value="massage spa", key="industry_send")

        status_to_show = st.multiselect(
            "显示哪些状态",
            ["pending", "failed", "skipped", "sent"],
            default=["pending", "failed"],
            key="send_status_filter",
        )
        candidate_df = send_df[send_df["status"].replace("", "pending").isin(status_to_show)].copy()
        candidate_df = candidate_df[candidate_df["email"].astype(str).str.len() > 0]

        if candidate_df.empty:
            st.info("当前筛选条件下没有可操作的邮箱。")
        else:
            row_id = st.selectbox(
                "选择一条线索",
                candidate_df["_row_id"].tolist(),
                format_func=lambda idx: row_label(send_df.loc[int(idx)]),
            )
            row = send_df.loc[int(row_id)]
            business_name, subject, text_body, html_body, diagnostic_link = render_email_for_row(row, industry_send)

            left, right = st.columns([1.1, 1])
            with left:
                st.markdown("#### 线索信息")
                st.write("显示店名：", business_name)
                st.write("原始店名：", row.get("business_name", ""))
                st.write("邮箱：", row.get("email", ""))
                st.write("状态：", row.get("status", "pending"))
                st.write("Lead ID：", row.get("lead_id", ""))
                st.write("按钮链接：", diagnostic_link)
                st.write("发件人显示：", f"{mailer.SENDER_DISPLAY_NAME} <{mailer.GMAIL_SENDER}>")
                st.write("标题：", subject)
                st.text_area("纯文本备用正文", text_body, height=310)

            with right:
                st.markdown("#### HTML 邮件预览")
                components.html(html_body, height=460, scrolling=True)

            action_col1, action_col2, action_col3 = st.columns([1, 1, 2])
            with action_col1:
                send_clicked = st.button("发送这封", type="primary")
            with action_col2:
                skip_clicked = st.button("标记跳过")

            if send_clicked:
                if not os.environ.get("GMAIL_SENDER") or not os.environ.get("GMAIL_APP_PASSWORD"):
                    st.error("未设置 GMAIL_SENDER 或 GMAIL_APP_PASSWORD。请检查 .env 后重启面板。")
                else:
                    with st.spinner("正在发送..."):
                        success = mailer.send_email(str(row.get("email", "")), subject, text_body, html_body)
                    if success:
                        send_df.loc[int(row_id), "status"] = "sent"
                        send_df.loc[int(row_id), "sent_at"] = datetime.now().isoformat(timespec="seconds")
                        save_csv(selected_csv_send, send_df)
                        st.success("已发送，并已写回 CSV。")
                        st.rerun()
                    else:
                        send_df.loc[int(row_id), "status"] = "failed"
                        save_csv(selected_csv_send, send_df)
                        st.error("发送失败，已标记 failed。优先检查网络是否能连 smtp.gmail.com:587/465。")

            if skip_clicked:
                send_df.loc[int(row_id), "status"] = "skipped"
                save_csv(selected_csv_send, send_df)
                st.success("已标记 skipped，并写回 CSV。")
                st.rerun()


# ------------------------------------------------------------
# Tab 4: lead_id 搜索
# ------------------------------------------------------------

with tab_search:
    st.subheader("通过 lead_id 找原始商家")
    st.write("当诊断工具邮件里出现 `Outreach Lead ID` 时，可以在这里反查对应 CSV 和商家。")

    lead_query = st.text_input("输入 lead_id 或部分关键词", value="")
    if lead_query.strip():
        query = lead_query.strip().lower()
        matches = []
        for csv_path in csv_files:
            df = load_csv(csv_path)
            joined = df.astype(str).agg(" ".join, axis=1).str.lower()
            matched = df[joined.str.contains(query, na=False)].copy()
            if not matched.empty:
                matched.insert(0, "csv_file", csv_path.name)
                matches.append(matched)

        if matches:
            result_df = pd.concat(matches, ignore_index=True)
            show_cols = [
                "csv_file", "lead_id", "business_name", "email", "status", "sent_at",
                "website", "phone", "address",
            ]
            show_cols = [c for c in show_cols if c in result_df.columns]
            st.dataframe(result_df[show_cols], use_container_width=True, height=420)
        else:
            st.warning("没有找到匹配记录。")
