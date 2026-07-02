# Local Outreach Tool

本项目用于本地实体服务店铺外联获客：

```text
抓取本地商家 → 抓取网站邮箱 → 自动去重 → 增长机会评分 → 网站成熟度判断 → 动态邮件话术 → 人工确认发送 → 通过 lead_id 追踪
```

配套诊断工具：`https://local-business-test.vercel.app/`

## 文件结构

```text
local-outreach-tool/
├── outreach_panel.py     # 本地可视化操作面板（推荐使用）
├── run_scrape.py         # 自动读取 .env，运行抓取，并做增长机会评分/筛选
├── scrape_leads.py       # Step 1：抓商家 + 抓邮箱 + 历史去重 + 生成CSV
├── send_emails.py        # Step 2：读取CSV + 人工确认 + Gmail发送
├── email_templates.py    # 邮件标题与正文模板，支持动态开场白
├── blocklist_utils.py    # 本地 blocklist 工具，避免继续联系拒绝商户
├── requirements.txt
├── .env.example
└── README.md
```

## 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

如果你的 Mac 没有 `pip` 命令，用：

```bash
python3 -m pip install -r requirements.txt
```

## 2. 配置本地 `.env`

推荐在项目目录创建 `.env`：

```bash
nano .env
```

写入以下内容，每个变量一行：

```bash
export GOOGLE_PLACES_API_KEY="你的Google Places API Key"
export GMAIL_SENDER="youraccount@gmail.com"
export GMAIL_APP_PASSWORD="你的Gmail应用专用密码"
export SENDER_DISPLAY_NAME="Foxiren Growth Check"
export DIAGNOSTIC_BASE_URL="https://local-business-test.vercel.app/"
```

> `.env` 会被程序自动读取，不需要每次 `source .env`。  
> `GMAIL_APP_PASSWORD` 是 Gmail App Password，不是 Gmail 登录密码。  
> `.env` 不要上传到 GitHub，仓库已经通过 `.gitignore` 忽略它。

## 3. 推荐方式：启动可视化面板

```bash
python3 -m streamlit run outreach_panel.py
```

启动后浏览器会打开一个本地页面，包含五个功能区：

```text
① 抓取线索：选择城市池，填写行业、数量，运行 run_scrape.py
② 查看CSV：查看 leads_output 里的所有线索，筛选状态、增长等级、外联角度
③ 预览/发送邮件：选择单条线索，预览动态HTML邮件，点击发送并自动回写CSV状态
④ lead_id 搜索：收到诊断提交后，用 Outreach Lead ID 反查原始商家
⑤ Blocklist：管理不要再联系的邮箱/网站
```

面板已经内置城市池：

```text
第一轮测试：按摩/SPA 10城
Florida：按摩/SPA 城市池
Texas：按摩/SPA 城市池
California：按摩/SPA 城市池
Northeast / Midwest：补充测试城市池
West / Mountain：补充测试城市池
```

你可以单独选择一个城市，也可以勾选“批量抓取整个城市池”。面板运行在你自己的 Mac 本地，密钥仍然只在本机 `.env` 里，不会上传到服务器。

## 4. 增长机会评分

`run_scrape.py` 会对新 CSV 自动新增这些字段：

```text
growth_score
growth_tier
growth_reason
website_maturity_score
website_maturity_tier
outreach_angle
dynamic_email_intro
website_has_booking
website_has_phone_cta
website_has_reviews
website_has_offer
website_has_gift_or_membership
website_has_local_seo_signals
website_has_multi_page_structure
is_likely_chain
website_scan_status
```

核心逻辑：

```text
评分不错 + 评论还有增长空间 + 有网站 + 能联系到 + 像独立商户 = 加分
网站缺少预约/电话/评价/优惠/复购入口 = 加分
网站成熟且评论很多 = 降权或跳过
疑似连锁/企业品牌 = 降权或跳过
blocklist 中的邮箱/网站 = 直接跳过
```

常见外联角度：

```text
review_growth
website_conversion
repeat_booking
local_seo
general_growth
skip_mature_business
skip_chain_or_corporate
```

## 5. Blocklist / 不要再联系

当商户回复 `no`、明确拒绝、或你手动判断不该再联系时，在面板里点“不要再联系”。工具会：

```text
1. 把当前线索状态改成 do_not_contact
2. 写入本地 blocklist.csv
3. 后续抓取和发送时自动跳过同邮箱或同网站
```

`blocklist.csv` 是本地文件，不上传 GitHub。

## 6. 命令行方式：抓取线索

推荐用 `run_scrape.py`，它会自动读取 `.env`，并做增长机会评分：

```bash
python3 run_scrape.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20 --min-rating 4.0 --min-reviews 10 --min-growth-score 60
```

如果你确实想重新抓旧线索，可以加：

```bash
python3 run_scrape.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20 --no-dedupe-existing
```

输出文件示例：

```text
leads_output/leads_Orlando_20260630_143000.csv
```

## 7. 命令行方式：发送邮件

```bash
python3 send_emails.py --file leads_output/leads_Orlando_20260630_143000.csv --industry "massage spa"
```

如果想自动跳过 `info@` / `support@` 等通用邮箱：

```bash
python3 send_emails.py --file leads_output/leads_Orlando_20260630_143000.csv --industry "massage spa" --auto-skip-generic
```

`send_emails.py` 会读取 CSV 里的：

```text
outreach_angle
dynamic_email_intro
```

然后自动生成更贴合该商户情况的邮件开场白。

## 8. lead_id 追踪逻辑

`scrape_leads.py` 会基于：

```text
business_name + website
```

生成稳定唯一ID，例如：

```text
lead_2b8fb8456fd68193
```

发出的诊断链接会变成：

```text
https://local-business-test.vercel.app/?lead_id=lead_2b8fb8456fd68193&angle=review_growth
```

这样即使CSV重新生成，行号变化，也可以通过 `lead_id` 对照原始商家信息。

## 9. 状态字段

发送和筛选过程中常见状态：

```text
pending
sent
skipped
failed
do_not_contact
not_interested
replied
converted
```

`send_emails.py` 或 `outreach_panel.py` 发送成功后会写入：

```text
status=sent
sent_at=2026-06-30T15:30:00
```

后续你收到诊断工具邮件时，可以用邮件里的 `Outreach Lead ID` 回到面板第 ④ 个功能区搜索，也可以用命令行查：

```bash
grep 'lead_2b8fb8456fd68193' leads_output/*.csv
```
