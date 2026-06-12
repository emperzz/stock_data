"""Tag → section_id/title mapping for the explorer manifest.

FastAPI route 的 tags=["stocks"] 查这张表得到 sidebar 的 section_id 和
中文 title。这张表是 explorer 端的 UI 关注点,放在 explorer 子包而不是
api/ 路由层——业务路由不该知道"我的 tag 叫 stocks 会被 explorer 分到
4.2 节"这种 UI 决策。

第一期:硬编码。第二期:可改为允许每个 route 用 @endpoint_meta(section_id=...)
显式覆盖,用于"某个 endpoint 应该被分到'健康检查'节而不是'stocks'节"的
edge case(目前没有,但留口子——见 EndpointMeta.section_id)。
"""
from __future__ import annotations

# tag -> {id, title}
TAG_TO_SECTION: dict[str, dict[str, str]] = {
    "health":        {"id": "4.1",  "title": "健康检查"},
    "stocks":        {"id": "4.2",  "title": "股票 / 个股 API"},
    "indices":       {"id": "4.3",  "title": "指数 API"},
    "calendar":      {"id": "4.4",  "title": "股票 / 指数列表与日历"},
    "boards":        {"id": "4.5",  "title": "板块 (Boards)"},
    "pools":         {"id": "4.6",  "title": "涨跌停股池"},
    "dragon-tiger":  {"id": "4.7",  "title": "龙虎榜"},
    "hot":           {"id": "4.8",  "title": "热点题材"},
    "north-flow":    {"id": "4.9",  "title": "北向资金"},
    "indicators":    {"id": "4.10", "title": "技术指标"},
    # 未来新 tag 在这里加一行
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
