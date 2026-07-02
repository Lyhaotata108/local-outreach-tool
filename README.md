# Local Outreach Tool

本项目用于本地实体服务店铺外联获客：

```text
抓取本地商家（有网站）→ 抓取网站邮箱 → 自动去重 → 人工确认发送外联邮件 → 商家点击诊断链接 → 通过 lead_id 对照CSV追踪
```

配套诊断工具：`https://local-business-test.vercel.app/`

## 文件结构

```text
local-outreach-tool/
├── outreach_panel.py     # 本地可视化操作面板（推荐使用）
├── email_templates.py    # 邮件标题与正文模板
├── scrape_leads.py       # Step 1：抓商家 + 抓邮箱 + 历史去重 + 生成CSV
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
```

保存后，命令行模式可以执行：

```bash
source .env
```

> `GMAIL_APP_PASSWORD` 是 Gmail App Password，不是 Gmail 登录密码。  
> `.env` 不要上传到 GitHub，仓库已经通过 `.gitignore` 忽略它。

## 3. 推荐方式：启动可视化面板

```bash
streamlit run outreach_panel.py
```

如果提示 `streamlit: command not found`，用：

```bash
python3 -m streamlit run outreach_panel.py
```

启动后浏览器会打开一个本地页面，包含四个功能区：

```text
① 抓取线索：选择城市池，填写行业、数量，点击按钮运行 scrape_leads.py
② 查看CSV：查看 leads_output 里的所有线索，筛选 pending/sent/skipped/failed
③ 预览/发送邮件：选择单条线索，预览HTML按钮邮件，点击发送并自动回写CSV状态
④ lead_id 搜索：收到诊断提交后，用 Outreach Lead ID 反查原始商家
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

## 4. 去重逻辑

`scrape_leads.py` 默认会读取 `leads_output/` 下所有历史 CSV，并按三层去重：

```text
lead_id
website
email
```

这样你第二天继续抓同一个城市时，已经抓过的商家会自动跳过，不会反复出现在新 CSV 里。

如果你确实想重新抓旧线索，可以加：

```bash
python scrape_leads.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20 --no-dedupe-existing
```

## 5. 命令行方式：抓取线索

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

## 6. 命令行方式：发送邮件

```bash
python send_emails.py --file leads_output/leads_Orlando_20260630_143000.csv --industry "massage spa"
```

如果想自动跳过 `info@` / `support@` 等通用邮箱：

```bash
python send_emails.py --file leads_output/leads_Orlando_20260630_143000.csv --industry "massage spa" --auto-skip-generic
```

## 7. lead_id 追踪逻辑

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

## 8. sent_at 转化统计

`send_emails.py` 或 `outreach_panel.py` 发送成功后会写入：

```text
status=sent
sent_at=2026-06-30T15:30:00
```

后续你收到诊断工具邮件时，可以用邮件里的 `Outreach Lead ID` 回到面板第 ④ 个功能区搜索，也可以用命令行查：

```bash
grep 'lead_2b8fb8456fd68193' leads_output/*.csv
```
