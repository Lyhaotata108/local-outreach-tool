"""
外联邮件模板
变量说明：
  {business_name}  - 商家名称，例如 "Yellowstone Spa Massage"
  {city}            - 城市，例如 "Concord"
  {diagnostic_url}  - 诊断工具链接，建议带 lead_id 参数方便追踪
"""

import html

# ============================================================
# 标题（Subject Line）— 决定打开率，必须具体、非推销语气
# 提供3个版本，建议轮换测试（A/B test），避免大量重复标题被Gmail判定群发/垃圾邮件
# ============================================================

SUBJECT_VARIANTS = [
    "Quick question about {business_name}",
    "Noticed something about {business_name}'s online presence",
    "Free 2-min check for {business_name} — worth a look?",
]


# ============================================================
# 纯文本正文模板 — 作为HTML邮件的备用版本
# 大多数邮箱客户端会优先显示HTML按钮版；少数不支持HTML的客户端才会看到这个版本
# ============================================================

BODY_TEMPLATE = """Hi there,

I came across {business_name} while looking at local {industry} businesses in {city}, and wanted to reach out.

A lot of local service businesses lose customers not because of marketing budget, but because of small gaps — things like a missing "Call Now" button on mobile, not enough recent Google reviews, or no clear reason for customers to choose them over nearby competitors.

I put together a free 2-minute diagnostic that checks exactly this — visibility, trust, website conversion, offers, repeat customers, and how you compare to nearby competitors. No signup, no strings attached:

{diagnostic_url}

If it's not useful, no worries at all — feel free to ignore this.

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
        A lot of local service businesses lose customers not because of marketing budget, but because of small gaps — things like a missing <strong>"Call Now"</strong> button on mobile, not enough recent Google reviews, or no clear reason for customers to choose them over nearby competitors.
      </p>

      <p style="margin:0 0 18px;">
        I put together a free 2-minute diagnostic that checks exactly this — visibility, trust, website conversion, offers, repeat customers, and how you compare to nearby competitors. No signup, no strings attached:
      </p>

      <p style="margin:24px 0;">
        <a href="{diagnostic_url}" style="display:inline-block; background:#1f6feb; color:#ffffff; text-decoration:none; padding:12px 20px; border-radius:8px; font-weight:700; font-size:15px;">
          View My Free Diagnostic
        </a>
      </p>

      <p style="margin:0 0 16px;">
        If it's not useful, no worries at all — feel free to ignore this.
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
