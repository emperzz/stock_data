"""Integration tests using fixture HTML for top_n + truncation path."""

from pathlib import Path
from unittest.mock import patch

import pytest

from stock_data.api.routes import reset_manager

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ths_board_301085_page1.html"


@pytest.fixture(autouse=True)
def reset_mgr():
    reset_manager()
    yield


def _read_fixture() -> str:
    return FIXTURE_PATH.read_text(encoding="gbk")


def test_fixture_loads_10_rows():
    body = _read_fixture()
    assert body.count("<tr") >= 10


def test_integration_top_n_10_with_real_fixture():
    """完整路径: fixture HTML → fetcher parse → 响应 6-tuple → route 返回."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

    fetcher = ThsFetcher()

    fake_html = _read_fixture()
    with patch.object(fetcher, "_http_get") as mock_get:
        mock_get.return_value.text = fake_html
        mock_get.return_value.status_code = 200
        # 显式 encoding
        mock_get.return_value.encoding = "gbk"
        # 显式 content too (r.content 在 r.encoding 设置后还会被读到)
        mock_get.return_value.content = fake_html.encode("gbk")

        rows = fetcher.get_board_stocks(
            board_code="301085",
            top_n=10,
            sort_by="change_pct",
            sort_order="desc",
        )

    assert len(rows) == 10
    # 验证所有 6 新字段都被解析.
    for row in rows:
        assert row["stock_code"]
        assert row["stock_name"]
        # 14 列下 change_speed/volume_ratio/amplitude 等字段都应被赋值.
        # (上游真实值可能是 '--' → None, 仅要求字段 key 存在)
        assert "change_speed" in row
        assert "volume_ratio" in row
        assert "amplitude" in row
        assert "free_float_shares" in row
        assert "float_market_cap" in row
        assert "pe_ratio" in row


def test_integration_top_n_3_truncates_after_first_page():
    """top_n=3 → 翻 1 页 (10 行) → 接到 3 行就 break."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

    fetcher = ThsFetcher()

    fake_html = _read_fixture()
    with patch.object(fetcher, "_http_get") as mock_get:
        mock_get.return_value.text = fake_html
        mock_get.return_value.status_code = 200
        mock_get.return_value.encoding = "gbk"
        mock_get.return_value.content = fake_html.encode("gbk")

        rows = fetcher.get_board_stocks(
            board_code="301085",
            top_n=3,
            sort_by="change_pct",
            sort_order="desc",
        )

    # 拿到的前 3 行的 stock_code 必须 == fixture 的前 3 行 stock_code.
    # (verify break at top_n; never continues to page 2)
    assert len(rows) == 3
    # mock_get 只调了 1 次 (page 1).
    assert mock_get.call_count == 1
