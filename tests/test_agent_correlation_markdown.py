"""Tests for the markdown renderer."""

from stock_data.api.routes.agent_correlation import render_correlation_matrix_as_md

SAMPLE = {
    "labels": [
        {"type": "stock", "code": "600519", "name": "贵州茅台", "source": None},
        {"type": "stock", "code": "000001", "name": "平安银行", "source": None},
        {"type": "board", "code": "885595", "name": "白酒",   "source": "ths"},
    ],
    "frequency": "d",
    "days": 90,
    "alignment": {"requested_days": 90, "common_bars": 87, "missing_after_join": 3},
    "matrices": {
        "pearson":  [[1.0, 0.87, 0.23], [0.87, 1.0, 0.41], [0.23, 0.41, 1.0]],
        "spearman": [[1.0, 0.79, 0.18], [0.79, 1.0, 0.39], [0.18, 0.39, 1.0]],
    },
    "errors": [],
}


def test_top_pairs_sorted_by_abs_rho():
    md = render_correlation_matrix_as_md(SAMPLE)
    # First data row in top-pairs table is the strongest correlation
    first_pair_line = next(
        (line for line in md.splitlines() if line.startswith("| 1 |")),
        None,
    )
    assert first_pair_line is not None
    # 600519 ↔ 000001 = 0.87 must be first; 0.41 second; 0.23 third
    assert "600519 ↔ 000001" in first_pair_line
    assert "0.87" in first_pair_line


def test_pearson_section_present():
    md = render_correlation_matrix_as_md(SAMPLE)
    assert "## 相关性矩阵 — pearson (d × 90d)" in md
    assert "## 相关性矩阵 — spearman (d × 90d)" in md


def test_full_matrix_table_has_diag_dash():
    md = render_correlation_matrix_as_md(SAMPLE)
    # Find the "完整矩阵 (pearson)" section
    idx = md.find("### 完整矩阵 (pearson)")
    assert idx > 0
    block = md[idx:]
    # The first row of the matrix table must have "—" at column 0 (diagonal entry)
    assert "600519 | — " in block


def test_methods_subset_omits_section():
    spec = {**SAMPLE, "matrices": {**SAMPLE["matrices"], "spearman": None}}
    md = render_correlation_matrix_as_md(spec)
    assert "## 相关性矩阵 — spearman" not in md
    assert "## 相关性矩阵 — pearson" in md


def test_errors_section_only_when_present():
    spec = {**SAMPLE, "errors": [
        {"type": "stock", "code": "000001", "source": None, "reason": "empty"}
    ]}
    md = render_correlation_matrix_as_md(spec)
    assert "### 数据缺失" in md
    assert "000001" in md


def test_no_errors_section_when_empty():
    md = render_correlation_matrix_as_md(SAMPLE)
    assert "### 数据缺失" not in md
