"""
外联邮件模板
变量说明：
  {business_name}  - 已清洗后的商家名称，例如 "Orlando Spa Oasis"
  {city}            - 城市，例如 "Orlando"
  {diagnostic_url}  - 诊断工具链接，建议带 lead_id 参数方便追踪
"""

import html

# ============================================================
# 标题（Subject Line）— 具体、低压力、避免过度营销
# ============================================================

SUBJECT_VARIANTS = [
    "Quick local growth check for {business_name}",
    "Small online presence check for {business_name}",
    "Free 2-min local growth check for {business_name}",
]


# ============================================================
# 纯文本正文模板 — 作为HTML邮件的备用版本
# 定位不只说网站，而是 local growth / online presence：
# visibility、reviews/trust、conversion、offers、repeat customers、competition
# ============================================================

BODY_TEMPLATE = """Hi there,

I came across {business_name} while looking at local {industry} businesses in {city}, and wanted to reach out.

A lot of local service businesses lose customers not because of marketing budget, but because of small gaps — things like unclear mobile calls-to-action, weak recent reviews, confusing offers, missing trust signals, or no clear reason for customers to choose them over nearby competitors.

I put together a free 2-minute local growth check that looks at online visibility, trust and reviews, website conversion, offers, repeat-customer opportunities, and nearby competition. No signup, no strings attached:

{diagnostic_url}

If this is not relevant, just reply "no" and I won't follow up.

Best,
{sender_name}
"""


# ============================================================
# HTML正文模板 — 客户看到的是按钮，不直接露出长链接
# ============================================================

HTML_BODY_TEMPLATE = """<!doctype html>
<html>
  <body style="margin:0; padding:0; background:#ffffff; font-family:Arial, Helvetica, sans-serif; color:#1f2933;">
    <div style="max-width:640px; margin:0 auto; padding:24px 20px; line-height:1.6; font-size:15px;">
      <p style="margin:0 0 16px;">Hi there,</p>

      <p style="margin:0 0 16px;">
        I came across {business_name} while looking at local {industry} businesses in {city}, and wanted to reach out.
      </p>

      <p style="margin:0 0 16px;">
        A lot of local service businesses lose customers not because of marketing budget, but because of small gaps — things like unclear mobile calls-to-action, weak recent reviews, confusing offers, missing trust signals, or no clear reason for customers to choose them over nearby competitors.
      </p>

      <p style="margin:0 0 18px;">
        I put together a free 2-minute local growth check that looks at online visibility, trust and reviews, website conversion, offers, repeat-customer opportunities, and nearby competition. No signup, no strings attached:
      </p>

      <p style="margin:24px 0;">
        <a href="{diagnostic_url}" style="display:inline-block; background:#1f6feb; color:#ffffff; text-decoration:none; padding:12px 20px; border-radius:8px; font-weight:700; font-size:15px;">
          View My Free Growth Check
        </a>
      </p>

      <p style="margin:0 0 16px;">
        If this is not relevant, just reply <strong>"no"</strong> and I won't follow up.
      </p>

      <p style="margin:24px 0 0;">
        Best,<br>
        {sender_name}
      </p>
    </div>
  </body>
</html>
"""


def render_subject(business_name: str, variant_index: int = 0) -> str:
    """渲染标题，variant_index 用于轮换不同版本"""
    template = SUBJECT_VARIANTS[variant_index % len(SUBJECT_VARIANTS)]
    return template.format(business_name=business_name)


def render_body(business_name: str, city: str, diagnostic_url: str,
                 industry: str = "service", sender_name: str = "Foxiren") -> str:
    """渲染纯文本正文，作为HTML邮件的备用版本"""
    return BODY_TEMPLATE.format(
        business_name=business_name,
        city=city,
        diagnostic_url=diagnostic_url,
        industry=industry,
        sender_name=sender_name,
    )


def render_html_body(business_name: str, city: str, diagnostic_url: str,
                     industry: str = "service", sender_name: str = "Foxiren") -> str:
    """渲染HTML正文，客户在Gmail等主流邮箱里看到的是按钮版"""
    return HTML_BODY_TEMPLATE.format(
        business_name=html.escape(business_name or ""),
        city=html.escape(city or "your area"),
        diagnostic_url=html.escape(diagnostic_url or "", quote=True),
        industry=html.escape(industry or "service"),
        sender_name=html.escape(sender_name or "Foxiren"),
    )
