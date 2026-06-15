"""
批量抓取 AKShare 数据字典的所有分类页, 转为 innerText 格式落盘.

输入: 分类 URL 列表
输出: docs/akshare/raw/<name>.txt
"""

import urllib.request
import urllib.error
import re
import sys
import time
from pathlib import Path
import html as htmlmod

RAW_DIR = Path(__file__).resolve().parent.parent / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# (name, url, 中文标签, out_subdir)
CATEGORIES = [
    ("stock",         "https://akshare.akfamily.xyz/data/stock/stock.html",                   "股票",   "stock"),
    ("index",         "https://akshare.akfamily.xyz/data/index/index.html",                   "指数",   "index"),
    ("futures",       "https://akshare.akfamily.xyz/data/futures/futures.html",               "期货",   "futures"),
    ("bond",          "https://akshare.akfamily.xyz/data/bond/bond.html",                     "债券",   "bond"),
    ("option",        "https://akshare.akfamily.xyz/data/option/option.html",                 "期权",   "option"),
    ("fx",            "https://akshare.akfamily.xyz/data/fx/fx.html",                         "外汇",   "fx"),
    ("currency",      "https://akshare.akfamily.xyz/data/currency/currency.html",             "货币",   "currency"),
    ("spot",          "https://akshare.akfamily.xyz/data/spot/spot.html",                     "现货",   "spot"),
    ("interest_rate", "https://akshare.akfamily.xyz/data/interest_rate/interest_rate.html",   "利率",   "interest_rate"),
    ("fund_private",  "https://akshare.akfamily.xyz/data/fund/fund_private.html",             "私募基金", "fund_private"),
    ("fund_public",   "https://akshare.akfamily.xyz/data/fund/fund_public.html",              "公募基金", "fund_public"),
    ("macro",         "https://akshare.akfamily.xyz/data/macro/macro.html",                   "宏观",   "macro"),
    ("dc",            "https://akshare.akfamily.xyz/data/dc/dc.html",                         "加密货币", "dc"),
    ("bank",          "https://akshare.akfamily.xyz/data/bank/bank.html",                     "银行",   "bank"),
    ("article",       "https://akshare.akfamily.xyz/data/article/article.html",               "波动率", "article"),
    ("energy",        "https://akshare.akfamily.xyz/data/energy/energy.html",                 "能源",   "energy"),
    ("event",         "https://akshare.akfamily.xyz/data/event/event.html",                   "迁徙",   "event"),
    ("hf",            "https://akshare.akfamily.xyz/data/hf/hf.html",                         "高频",   "hf"),
    ("nlp",           "https://akshare.akfamily.xyz/data/nlp/nlp.html",                       "自然语言处理", "nlp"),
    ("qdii",          "https://akshare.akfamily.xyz/data/qdii/qdii.html",                     "QDII",  "qdii"),
    ("others",        "https://akshare.akfamily.xyz/data/others/others.html",                 "另类",   "others"),
    ("tool",          "https://akshare.akfamily.xyz/data/tool/tool.html",                     "工具箱", "tool"),
    ("qhkc_index",    "https://akshare.akfamily.xyz/data/qhkc/index.html",                    "奇货首页", "qhkc_index"),
    ("qhkc_commodity","https://akshare.akfamily.xyz/data/qhkc/commodity.html",                "奇货商品", "qhkc_commodity"),
    ("qhkc_broker",   "https://akshare.akfamily.xyz/data/qhkc/broker.html",                   "奇货席位", "qhkc_broker"),
    ("qhkc_index_data","https://akshare.akfamily.xyz/data/qhkc/index_data.html",              "奇货指数", "qhkc_index_data"),
    ("qhkc_fundamental","https://akshare.akfamily.xyz/data/qhkc/fundamental.html",            "奇货基本面", "qhkc_fundamental"),
    ("qhkc_tools",    "https://akshare.akfamily.xyz/data/qhkc/tools.html",                    "奇货工具", "qhkc_tools"),
    ("qhkc_fund",     "https://akshare.akfamily.xyz/data/qhkc/fund.html",                     "奇货资金", "qhkc_fund"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def html_to_innertext(html):
    """模仿 browser innerText: 提取 [role=main], block 标签换行, td→tab, 去 tag."""
    # 去 script/style
    html = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # 找 [role=main]
    m = re.search(
        r'<div[^>]+role\s*=\s*["\']main["\'][^>]*>(.*?)(?=<div[^>]+class=["\'][^"\']*sphinxsidebar|<footer|<div[^>]+class=["\'][^"\']*footer|$)',
        html, flags=re.DOTALL | re.IGNORECASE
    )
    if m:
        content = m.group(1)
    else:
        m = re.search(r'<body[^>]*>(.*?)</body>', html, flags=re.DOTALL | re.IGNORECASE)
        content = m.group(1) if m else html

    # 把每个 <tr>...</tr> 内部压平成一行 (去掉所有空白+换行), 保留 <tr> 边界
    def flatten_tr(m):
        inner = m.group(1)
        inner = re.sub(r'[\n\r\t\xa0]+', ' ', inner)
        inner = re.sub(r'  +', ' ', inner)
        return '<tr>' + inner.strip() + '</tr>'

    content = re.sub(r'<tr[^>]*>(.*?)</tr>', flatten_tr, content, flags=re.DOTALL | re.IGNORECASE)

    # th/td → \x1f, tr → \n
    content = re.sub(r'</th>', '\x1f', content, flags=re.IGNORECASE)
    content = re.sub(r'</td>', '\x1f', content, flags=re.IGNORECASE)
    content = re.sub(r'</tr>', '\n', content, flags=re.IGNORECASE)

    # block 标签 → \n (不含 <p>)
    content = re.sub(
        r'</?(div|li|h[1-6]|br|hr|section|article|table|thead|tbody|tfoot|colgroup|col|caption)[^>]*>',
        '\n', content, flags=re.IGNORECASE
    )

    # 删剩余 tag
    content = re.sub(r'<[^>]+>', '', content)

    # 解码 HTML 实体
    content = htmlmod.unescape(content)

    # 折叠空白 (保留 \t 和 \x1f)
    content = re.sub(r'[ \xc2\xa0]+', ' ', content)
    content = re.sub(r'\n[ \t]*\n+', '\n\n', content)

    # \x1f → \t
    content = content.replace('\x1f', '\t')
    # 单元格后的空格(原始 HTML 中的美化空格)去掉
    content = re.sub(r'\t[ \xa0]+', '\t', content)

    # 多余空行 → 单换行
    content = re.sub(r'\n+', '\n', content)

    return content.strip()


def fetch(name, url, retries=3):
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
            # 检测编码: 优先看 content-type
            ct = resp.headers.get_content_charset() or "utf-8"
            try:
                html = raw.decode(ct)
            except UnicodeDecodeError:
                html = raw.decode("utf-8", errors="replace")
            text = html_to_innertext(html)
            out = RAW_DIR / f"{name}.txt"
            out.write_text(text, encoding="utf-8")
            return f"{name}=OK {len(text):>7}B"
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            last_err = e
            time.sleep(1 + i * 2)
    return f"{name}=ERR {last_err}"


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None  # 可选: 只抓某个 name
    print(f"Fetching {len(CATEGORIES) if not only else 1} categories to {RAW_DIR}")
    for name, url, label, sub in CATEGORIES:
        if only and name != only:
            continue
        result = fetch(name, url)
        print(result, flush=True)


if __name__ == "__main__":
    main()
