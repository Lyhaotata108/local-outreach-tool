# Implementation Notes

## 任务A：稳定 lead_id

`scrape_leads.py` 使用 Python 标准库 `hashlib`，基于：

```text
business_name + normalized website
```

生成稳定ID：

```text
lead_<sha256前16位>
```

这样同一家商家重复抓取时，`lead_id` 不会因为CSV行号变化而改变。

## 任务B：诊断工具邮件标注 lead_id

`local-business-test/server.ts` 的 `/api/leads` 路由需要：

1. 从 `req.body` 中读取 `lead_id`
2. 在通知邮件 `Contact Details` 区域增加：

```text
Outreach Lead ID: ${lead_id || 'N/A (direct visit)'}
```

本仓库的 `docs/server-route-snippet.ts` 保留了对应路由片段，方便对照。

## 任务C：sent_at

`send_emails.py` 发送成功后，会写入：

```text
status=sent
sent_at=<ISO时间戳>
```

未发送、跳过或失败的记录不会写入 `sent_at`。
