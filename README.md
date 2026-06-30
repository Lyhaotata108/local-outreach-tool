# Local Outreach Tool

本项目用于本地实体服务店铺外联获客：

```text
抓取本地商家（有网站）→ 抓取网站邮箱 → 人工确认发送外联邮件 → 商家点击诊断链接 → 通过 lead_id 对照CSV追踪
```

配套诊断工具：`https://local-business-test.vercel.app/`

## 文件结构

```text
local-outreach-tool/
├── email_templates.py    # 邮件标题与正文模板
├── scrape_leads.py       # Step 1：抓商家 + 抓邮箱 + 生成CSV
├── send_emails.py        # Step 2：读取CSV + 人工确认 + Gmail发送
├── requirements.txt
├── .env.example
└── README.md
```

## 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 配置环境变量

```bash
export GOOGLE_PLACES_API_KEY='你的Google Places API Key'
export GMAIL_SENDER='youraccount@gmail.com'
export GMAIL_APP_PASSWORD='xxxx xxxx xxxx xxxx'
```

> `GMAIL_APP_PASSWORD` 是 Gmail App Password，不是 Gmail 登录密码。

## 3. 抓取线索

```bash
python scrape_leads.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20
```

输出文件示例：

```text
leads_output/leads_Orlando_20260630_143000.csv
```

CSV 会包含这些关键字段：

```text
lead_id,business_name,address,website,phone,google_rating,review_count,email,email_quality,all_emails_found,status,sent_at,scraped_at
```

## 4. 发送邮件

```bash
python send_emails.py --file leads_output/leads_Orlando_20260630_143000.csv --industry "massage spa"
```

如果想自动跳过 `info@` / `support@` 等通用邮箱：

```bash
python send_emails.py --file leads_output/leads_Orlando_20260630_143000.csv --industry "massage spa" --auto-skip-generic
```

## 5. lead_id 追踪逻辑

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
https://local-business-test.vercel.app/?lead_id=lead_2b8fb8456fd68193
```

这样即使CSV重新生成，行号变化，也可以通过 `lead_id` 对照原始商家信息。

## 6. sent_at 转化统计

`send_emails.py` 发送成功后会写入：

```text
status=sent
sent_at=2026-06-30T15:30:00
```

后续你收到诊断工具邮件时，可以用邮件里的 `Outreach Lead ID` 回到CSV里查：

```bash
grep 'lead_2b8fb8456fd68193' leads_output/*.csv
```
