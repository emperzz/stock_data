"""
AKShare 数据字典解析器

输入: docs/akshare/raw/<category>.txt (Playwright 抓取的 [role="main"].innerText)
输出: docs/akshare/<category>/<interface>.md (一个接口一个 md)
      docs/akshare/<category>.md (分类总览)
      docs/akshare/README.md (索引)

数据格式 (从 innerText 看到):
  A股
  股票市场总貌
  上海证券交易所

  接口: stock_sse_summary

  目标地址: http://...

  描述: ...

  限量: ...

  输入参数
  名称\t类型\t描述
  -\t-\t-
  (或 name\tstr\tdescription)

  输出参数[-<variant>]
  名称\t类型\t描述
  ...表格行

  接口示例
  import akshare as ak
  ...code...

  数据示例
  ...dataframe table...
"""

import re
import json
from pathlib import Path
from collections import OrderedDict

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
OUT_DIR = ROOT


def _clean_sphinx_tail(s):
    """移除 Sphinx 标题末尾的特殊字符 (U+F0C1 PUA 锚点标记 + 零宽/控制字符)."""
    if not s:
        return s
    # U+F0C1 是 Sphinx 在 heading 末尾加的 anchor 符号
    s = s.replace("", "")
    # 零宽字符 / 双向控制符 / 连接符
    s = re.sub(r"[​-‍﻿⁠-⁩‌‍⁪-⁯‎‏‪-‮]", "", s)
    return s.strip()

# ---------- 解析单个接口块 ----------

METADATA_LABELS = ("目标地址:", "描述:", "限量:")


def _read_table(lines, start):
    """从 start 开始读取一个表格, 返回 (table_rows, end_idx).
    表头固定为 `名称\\t类型\\t描述` (或 4 列场景: 名称\\t类型\\t描述\\t...).
    表格结束条件: 遇到空行 + 紧随的非表格行 (如 '接口示例'/'数据示例' 或下一段元数据).
    """
    rows = []
    i = start
    header = None
    # 必须先看到表头
    while i < len(lines):
        line = lines[i].rstrip("\n")
        if not line.strip():
            i += 1
            continue
        if line.startswith("名称\t"):
            header = line.split("\t")
            i += 1
            break
        # 没有表头, 直接是数据行 (罕见)
        if "\t" in line:
            header = ["名称", "类型", "描述"]
            break
        i += 1
    if header is None:
        return [], i
    ncol = len(header)
    # 读取数据行
    while i < len(lines):
        line = lines[i].rstrip("\n")
        if not line.strip():
            # 表格结束, 空行
            i += 1
            break
        cols = line.split("\t")
        # 如果列数对齐, 视为表格行
        if len(cols) >= ncol:
            rows.append(cols[:ncol])
            i += 1
            continue
        # 否则视为非表格, 结束
        break
    return rows, i


def _read_contiguous(lines, start, hard_end=None,
                     stop_markers=("接口:", "数据示例", "输入参数", "输出参数", "接口示例")):
    """从 start 跳过前导空行, 读取连续非空行 (dataframe 风格) 直到空行/stop_marker/hard_end.
    与 _read_block_until_blank 的区别: 遇到空行就停, 不保留内部空行.
    """
    # 跳过前导空行
    i = start
    end = hard_end if hard_end is not None else len(lines)
    while i < end and not lines[i].strip():
        i += 1
    buf = []
    while i < end:
        line = lines[i]
        stripped = line.lstrip()
        if not stripped:
            break
        if any(stripped.startswith(m) for m in stop_markers):
            break
        buf.append(line.rstrip())
        i += 1
    return "\n".join(buf), i


def _read_block_until_blank(lines, start, hard_end=None,
                            stop_markers=("接口:", "数据示例", "输入参数", "输出参数", "接口示例")):
    """从 start 读取直到遇到 stop_marker 或 hard_end.
    与 _read_block_until_blank 不同: 保留空行 (代码块内部有合法空行).
    到达 hard_end 时强制停止 (用于 data_example 这种可能在末尾掺杂下一节标题的情况).
    """
    buf = []
    i = start
    end = hard_end if hard_end is not None else len(lines)
    while i < end:
        line = lines[i]
        stripped = line.lstrip()
        if any(stripped.startswith(m) for m in stop_markers):
            break
        buf.append(line.rstrip())
        i += 1
    # 去掉首尾空行
    while buf and not buf[0].strip():
        buf.pop(0)
    while buf and not buf[-1].strip():
        buf.pop()
    return "\n".join(buf), i


def parse_interface(name, lines, i, hard_end):
    """从 lines[i] 之后开始解析一个接口, 返回 (iface_dict, end_idx).
    i 指向 '接口: <name>' 那一行.
    hard_end 是本块的硬边界 (下一个接口的 start 或 len(lines)).
    """
    iface = OrderedDict()
    iface["name"] = name
    iface["target_url"] = ""
    iface["description"] = ""
    iface["limit"] = ""
    iface["input_params"] = []          # list of (header, rows)
    iface["output_params"] = []         # list of (variant, header, rows)
    iface["example_code"] = ""
    iface["data_example"] = ""

    i += 1  # 跳过 '接口: ...'

    # ---- 1. 解析元数据 ----
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith(METADATA_LABELS):
            if line.startswith("目标地址:"):
                iface["target_url"] = line[len("目标地址:"):].strip()
            elif line.startswith("描述:"):
                iface["description"] = line[len("描述:"):].strip()
            elif line.startswith("限量:"):
                iface["limit"] = line[len("限量:"):].strip()
            i += 1
            continue
        break  # 离开元数据区

    # ---- 2. 解析 输入参数 / 输出参数 / 接口示例 / 数据示例 ----
    while i < hard_end:
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if line.startswith("输入参数"):
            rows, i = _read_table(lines, i + 1)
            iface["input_params"] = rows
            continue
        if line.startswith("输出参数"):
            variant = line[len("输出参数"):].lstrip("-").strip()
            rows, i = _read_table(lines, i + 1)
            iface["output_params"].append((variant, rows))
            continue
        if line.startswith("接口示例"):
            code, i = _read_block_until_blank(lines, i + 1, hard_end=hard_end,
                                              stop_markers=("接口:", "数据示例", "输入参数", "输出参数"))
            iface["example_code"] = code
            continue
        if line.startswith("数据示例"):
            # data_example 是一个 dataframe 文本表, 连续非空行, 遇到空行就停
            data, i = _read_contiguous(lines, i + 1, hard_end=hard_end,
                                       stop_markers=("接口:", "输入参数", "输出参数"))
            iface["data_example"] = data
            continue
        i += 1

    return iface, i


# ---------- 提取章节上下文 (heading tracking) ----------


def _is_heading(line):
    """简单判断: 短行 (<40 字符) 且不含 tab/冒号/句号/特殊符号, 且不是已知标签行."""
    if not line or not line.strip():
        return False
    s = _clean_sphinx_tail(line)
    if not s:
        return False
    if len(s) > 40:
        return False
    if "\t" in s or s.endswith(":"):
        return False
    if s.startswith(("接口", "目标地址", "描述", "限量", "输入参数", "输出参数",
                     "接口示例", "数据示例", "名称")):
        return False
    if s.startswith(("import", "print", "ak.", "stock_", "bond_", "futures_",
                     "index_", "option_", "macro_", "currency_", "fx_", "spot_",
                     "interest_rate_", "fund_", "qhkc_", "tool_", "dc_", "bank_",
                     "article_", "energy_", "event_", "hf_", "nlp_", "qdii_",
                     "others_", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
        return False
    # 排除 dataframe 数据行 (有数字或 NaN)
    if re.search(r"\d", s):
        return False
    return True


def extract_sections(text):
    """扫描全文, 返回 list of (start_idx, end_idx, name, context_dict).
    context_dict 记录: { 'top', 'category', 'sub', 'section' } (heading stack).
    """
    lines = text.split("\n")
    # 找所有 接口: 起点
    iface_starts = [i for i, ln in enumerate(lines) if ln.strip().startswith("接口:")]
    blocks = []
    for idx, start in enumerate(iface_starts):
        end = iface_starts[idx + 1] if idx + 1 < len(iface_starts) else len(lines)
        # 收集 start 之前的最近几行 heading
        ctx = {"section": "", "sub": "", "category": "", "top": ""}
        # 倒序找最近的 heading
        headings = []
        for j in range(start - 1, -1, -1):
            ln = lines[j]
            if not ln.strip():
                if headings:
                    break
                continue
            if _is_heading(ln):
                clean = _clean_sphinx_tail(ln)
                if clean:
                    headings.append(clean)
                if len(headings) >= 4:
                    break
            else:
                # 遇到非 heading 非空行, 停止
                if headings:
                    break
        headings = list(reversed(headings))
        if len(headings) >= 1:
            ctx["top"] = headings[0]
        if len(headings) >= 2:
            ctx["category"] = headings[1]
        if len(headings) >= 3:
            ctx["sub"] = headings[2]
        if len(headings) >= 4:
            ctx["section"] = headings[3]
        name = lines[start].strip()[len("接口:"):].strip()
        blocks.append((start, end, name, ctx))
    return blocks, lines


# ---------- 渲染 MD ----------


def _md_table(header, rows):
    if not rows:
        return ""
    # 去掉尾部空列 (table 末尾的 trailing tab 产生的)
    header = [h for h in header if h.strip()]
    rows = [[c for c in r if c is not None] for r in rows]
    # 如果每行末尾都有空字符串, 全部去掉
    while rows and all(r[-1].strip() == "" for r in rows if r):
        rows = [r[:-1] for r in rows]
    if not header:
        return ""
    out = "| " + " | ".join(header) + " |\n"
    out += "| " + " | ".join("---" for _ in header) + " |\n"
    for r in rows:
        # 转义 | 符号
        cells = [c.replace("|", "\\|").replace("\n", " ") for c in r]
        # pad to header length
        while len(cells) < len(header):
            cells.append("")
        cells = cells[:len(header)]
        out += "| " + " | ".join(cells) + " |\n"
    return out


def _wrap_code(code, lang="python"):
    if not code.strip():
        return ""
    return f"```{lang}\n{code.rstrip()}\n```\n"


def render_iface_md(iface):
    md = []
    md.append(f"# `{iface['name']}`\n")
    desc = _clean_sphinx_tail(iface.get("description", ""))
    if desc:
        md.append(f"**描述**: {desc}\n")
    url = _clean_sphinx_tail(iface.get("target_url", ""))
    if url:
        md.append(f"**目标地址**: <{url}>\n")
    limit = _clean_sphinx_tail(iface.get("limit", ""))
    if limit:
        md.append(f"**限量**: {limit}\n")
    md.append("")

    # 输入参数
    if iface["input_params"]:
        md.append("## 输入参数\n")
        # 表头固定 3 列
        md.append(_md_table(["名称", "类型", "描述"], iface["input_params"]))
    else:
        md.append("## 输入参数\n\n无\n")

    # 输出参数 (可能多组 variant)
    if iface["output_params"]:
        for variant, rows in iface["output_params"]:
            if variant:
                md.append(f"## 输出参数 - {variant}\n")
            else:
                md.append("## 输出参数\n")
            if rows:
                md.append(_md_table(["名称", "类型", "描述"], rows))
            else:
                md.append("无\n")
    else:
        md.append("## 输出参数\n\n无\n")

    # 接口示例
    if iface["example_code"]:
        md.append("## 接口示例\n")
        md.append(_wrap_code(iface["example_code"]))

    # 数据示例
    if iface["data_example"]:
        md.append("## 数据示例\n")
        # 数据示例本身可能是 dataframe 的文本输出, 包裹在 plain code 块里
        md.append(_wrap_code(iface["data_example"], lang="text"))

    return "\n".join(md).rstrip() + "\n"


def render_category_overview(category_label, out_subdir, iface_list):
    md = []
    md.append(f"# AKShare {category_label} 数据字典\n")
    md.append(f"共 **{len(iface_list)}** 个接口。\n")
    md.append("## 接口索引\n")
    for iface in iface_list:
        sub = _clean_sphinx_tail(iface.get("_sub", ""))
        sec = _clean_sphinx_tail(iface.get("_section", ""))
        loc = " / ".join(x for x in [sub, sec] if x)
        line = f"- [`{iface['name']}`](./{out_subdir}/{iface['name']}.md)"
        if loc:
            line += f" — {loc}"
        desc = _clean_sphinx_tail(iface.get("description", ""))
        if desc:
            line += f": {desc[:60]}"
            if len(desc) > 60:
                line += "…"
        md.append(line)
    md.append("")
    return "\n".join(md)


# ---------- 主流程 ----------


def process_category(label, raw_file, out_subdir):
    raw_path = RAW_DIR / raw_file
    if not raw_path.exists():
        print(f"!! missing: {raw_path}")
        return []
    text = raw_path.read_text(encoding="utf-8", errors="replace")
    # 处理 innerText 自带的引号包裹
    if text.startswith('"') and text.endswith('"\n'):
        text = text[1:-2]  # 去掉首尾的 \"
    elif text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    text = text.replace('\\n', '\n').replace('\\t', '\t')

    blocks, lines = extract_sections(text)
    interfaces = []
    for start, end, name, ctx in blocks:
        iface, _ = parse_interface(name, lines, start, hard_end=end)
        iface["_sub"] = ctx.get("sub", "")
        iface["_section"] = ctx.get("section", "")
        iface["_category"] = ctx.get("category", "")
        interfaces.append(iface)

    # 写出每接口一个 md
    out_dir = OUT_DIR / out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    for iface in interfaces:
        out_file = out_dir / f"{iface['name']}.md"
        out_file.write_text(render_iface_md(iface), encoding="utf-8")

    # 写分类总览
    overview = render_category_overview(label, out_subdir, interfaces)
    (OUT_DIR / f"{out_subdir}.md").write_text(overview, encoding="utf-8")

    print(f"[{label}] {len(interfaces)} interfaces, "
          f"{len(list(out_dir.iterdir()))} md files written to {out_dir}/")
    return interfaces


def main():
    # (label, raw_file, out_subdir)
    cats = [
        ("股票",       "stock.txt",          "stock"),
        ("指数",       "index.txt",          "index"),
        ("期货",       "futures.txt",        "futures"),
        ("债券",       "bond.txt",           "bond"),
        ("期权",       "option.txt",         "option"),
        ("外汇",       "fx.txt",             "fx"),
        ("货币",       "currency.txt",       "currency"),
        ("现货",       "spot.txt",           "spot"),
        ("利率",       "interest_rate.txt",  "interest_rate"),
        ("私募基金",   "fund_private.txt",   "fund_private"),
        ("公募基金",   "fund_public.txt",    "fund_public"),
        ("宏观",       "macro.txt",          "macro"),
        ("加密货币",   "dc.txt",             "dc"),
        ("银行",       "bank.txt",           "bank"),
        ("波动率",     "article.txt",        "article"),
        ("能源",       "energy.txt",         "energy"),
        ("迁徙",       "event.txt",          "event"),
        ("高频",       "hf.txt",             "hf"),
        ("自然语言处理", "nlp.txt",           "nlp"),
        ("QDII",      "qdii.txt",           "qdii"),
        ("另类",       "others.txt",         "others"),
        ("工具箱",     "tool.txt",           "tool"),
        ("奇货首页",   "qhkc_index.txt",     "qhkc_index"),
        ("奇货商品",   "qhkc_commodity.txt", "qhkc_commodity"),
        ("奇货席位",   "qhkc_broker.txt",    "qhkc_broker"),
        ("奇货指数",   "qhkc_index_data.txt","qhkc_index_data"),
        ("奇货基本面", "qhkc_fundamental.txt","qhkc_fundamental"),
        ("奇货工具",   "qhkc_tools.txt",     "qhkc_tools"),
        ("奇货资金",   "qhkc_fund.txt",      "qhkc_fund"),
    ]

    results = {}
    for label, raw, sub in cats:
        results[sub] = process_category(label, raw, sub)

    # 写 README
    total = sum(len(v) for v in results.values())
    readme = ["# AKShare 数据字典\n"]
    readme.append("本目录收录 AKShare 官方数据字典(原始文档: <https://akshare.akfamily.xyz/data/index.html>)。\n")
    readme.append(f"**总计 {sum(1 for v in results.values() if v)} 个分类, {total} 个接口。**\n")
    readme.append("## 分类索引\n")
    for label, raw, sub in cats:
        cnt = len(results.get(sub, []))
        readme.append(f"- **{label}** ([`{sub}.md`](./{sub}.md), [`{sub}/`](./{sub}/)): 共 {cnt} 个接口")
    readme.append("")
    readme.append("## 目录结构\n")
    readme.append("```\ndocs/akshare/\n├── README.md           # 本文件\n")
    for label, raw, sub in cats:
        readme.append(f"├── {sub}.md          # {label}分类总览\n")
        readme.append(f"└── {sub}/            # 每接口一个 md\n")
    readme.append("├── raw/                # urllib 抓取的 innerText (供 reparse)\n")
    readme.append("└── scripts/            # 解析脚本\n")
    readme.append("```\n")
    readme.append("## 重新生成\n")
    readme.append("```bash\n"
                  "# 1. 抓 raw (urllib 批量, 不经 LLM 上下文)\n"
                  "python docs/akshare/scripts/fetch_categories.py\n\n"
                  "# 2. 跑解析脚本\n"
                  "python docs/akshare/scripts/parse_akshare.py\n"
                  "```\n")
    (OUT_DIR / "README.md").write_text("\n".join(readme), encoding="utf-8")
    print(f"README.md written. Total: {total} interfaces across {sum(1 for v in results.values() if v)} categories.")


if __name__ == "__main__":
    main()
