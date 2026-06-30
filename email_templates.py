"""
外联邮件模板
变量说明：
  {business_name}  - 商家名称，例如 "Yellowstone Spa Massage"
  {city}            - 城市，例如 "Concord"
  {diagnostic_url}  - 诊断工具链接，建议带 lead_id 参数方便追踪
"""

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
# 正文模板 — 核心逻辑：
# 1. 第一句必须具体到这家店，不能是模板感很重的开场白
# 2. 不自我推销、不提"我们公司"、不堆砌服务列表
# 3. 直接给一个免费、低门槛的行动（诊断工具），而不是要求回复或通话
# 4. 结尾保持轻量，不施压，留一个"不感兴趣可以忽略"的退路降低反感
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


def render_subject(business_name: str, variant_index: int = 0) -> str:
    """渲染标题，variant_index 用于轮换不同版本"""
    template = SUBJECT_VARIANTS[variant_index % len(SUBJECT_VARIANTS)]
    return template.format(business_name=business_name)


def render_body(business_name: str, city: str, diagnostic_url: str,
                 industry: str = "service", sender_name: str = "Foxiren") -> str:
    """渲染正文"""
    return BODY_TEMPLATE.format(
        business_name=business_name,
        city=city,
        diagnostic_url=diagnostic_url,
        industry=industry,
        sender_name=sender_name,
    )
