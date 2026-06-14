"""Tag → section title mapping for the explorer manifest.

FastAPI route 的 tags=["stocks"] 查这张表得到 sidebar 的中文 title。
section id 直接用 tag 名（不再有"4.1"这种编号）——id 仅作 DOM
锚点 / URL hash,无业务含义。这张表只管 title,id 由 tag 自给。

加新 tag 时必须在这里登记一行,否则 manifest 会回退到用 tag 名本身
作 title(mount() 启动期会打 warning,explorer 仍能渲染)。
"""
from __future__ import annotations

# explorer 不展示的 tag——manifest 过滤用 + mount() 启动期 sanity-check 用。
# 单一真相,explorer 任何地方需要 "这是内部 tag 吗" 都查这里。
_INTERNAL_TAGS: frozenset[str] = frozenset({"control"})


# tag -> 中文 title
TAG_TO_TITLE: dict[str, str] = {
    "health":        "健康检查",
    "stocks":        "股票 / 个股 API",
    "indices":       "指数 API",
    "calendar":      "股票 / 指数列表与日历",
    "boards":        "板块 (Boards)",
    "pools":         "涨跌停股池",
    "dragon-tiger":  "龙虎榜",
    "hot":           "热点题材",
    "north-flow":    "北向资金",
    "indicators":    "技术指标",
}


# Capability flag → {label, icon} 装饰性映射。
# 跟 server 端 DataCapability flag 一一对应,改 DataCapability 时这里同步。
CAPABILITY_LABELS: dict[str, dict[str, str]] = {
    "HISTORICAL_DWM":   {"label": "日/周/月 K线",     "icon": "📈"},
    "HISTORICAL_MIN":   {"label": "分钟 K线",         "icon": "⏱"},
    "REALTIME_QUOTE":   {"label": "实时行情",         "icon": "💹"},
    "STOCK_LIST":       {"label": "股票列表",         "icon": "📋"},
    "TRADE_CALENDAR":   {"label": "交易日历",         "icon": "📅"},
    "STOCK_BOARD":      {"label": "板块",             "icon": "🏷"},
    "INDEX_QUOTE":      {"label": "指数实时",         "icon": "📊"},
    "INDEX_HISTORICAL": {"label": "指数历史",         "icon": "📉"},
    "INDEX_INTRADAY":   {"label": "指数分时",         "icon": "⏰"},
    "STOCK_ZT_POOL":    {"label": "涨跌停股池",       "icon": "🚦"},
    "STOCK_INFO":       {"label": "公司画像",         "icon": "🏢"},
    "DRAGON_TIGER":     {"label": "龙虎榜",           "icon": "🐉"},
    "MARGIN_TRADING":   {"label": "融资融券",         "icon": "💰"},
    "BLOCK_TRADE":      {"label": "大宗交易",         "icon": "🤝"},
    "HOLDER_NUM":       {"label": "股东户数",         "icon": "👥"},
    "DIVIDEND":         {"label": "分红送转",         "icon": "🎁"},
    "FUND_FLOW":        {"label": "资金流",           "icon": "💸"},
    "HOT_TOPICS":       {"label": "热点题材",         "icon": "🔥"},
    "NORTH_FLOW":       {"label": "北向资金",         "icon": "🌏"},
    "RESEARCH_REPORT":  {"label": "研报",             "icon": "📑"},
    "ANNOUNCEMENT":     {"label": "公告",             "icon": "📢"},
}
