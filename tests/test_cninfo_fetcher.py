"""Unit tests for CninfoFetcher."""
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.cninfo_fetcher import CninfoFetcher


class TestCninfoFetcherBasics:
    def test_name(self):
        f = CninfoFetcher()
        assert f.name == "CninfoFetcher"

    def test_priority(self):
        f = CninfoFetcher()
        assert f.priority == 8

    def test_is_available(self):
        f = CninfoFetcher()
        assert f.is_available() is True

    def test_capabilities(self):
        f = CninfoFetcher()
        assert DataCapability.ANNOUNCEMENT in f.supported_data_types

    def test_org_id_sh(self):
        f = CninfoFetcher()
        assert f._org_id("600519") == "gssh0600519"

    def test_org_id_sz(self):
        f = CninfoFetcher()
        assert f._org_id("000001") == "gssz0000001"

    def test_org_id_bj(self):
        f = CninfoFetcher()
        assert f._org_id("832000") == "gsbj0832000"

    def test_org_id_gem(self):
        f = CninfoFetcher()
        result = f._org_id("300476")
        assert result.startswith("gssz0")

    def test_org_id_bj_920(self):
        """北交所 920xxx 必须路由到 gsbj 前缀, 不能落到 SZ 的 else 分支。

        920 系列是 normalize.py 声明的 A_SHARE_STOCK_PREFIXES 之一
        (`startswith("9")`)。若 _org_id 漏 9, 会给 ``gssz0920xxx``, 深交所
        orgId 查北交所股票 → 公告静默空。
        """
        f = CninfoFetcher()
        result = f._org_id("920001")
        assert result == "gsbj0920001"
        assert result.startswith("gsbj")

    def test_org_id_bj_830_legacy(self):
        """北交所老格式 8xxxxx 仍走 gsbj。"""
        f = CninfoFetcher()
        assert f._org_id("832000") == "gsbj0832000"

    def test_org_id_bj_430_legacy(self):
        """北交所老格式 4xxxxx 仍走 gsbj。"""
        f = CninfoFetcher()
        assert f._org_id("430017") == "gsbj0430017"


class TestAnnouncements:
    def setup_method(self):
        self.fetcher = CninfoFetcher()

    @patch("stock_data.data_provider.fetchers.cninfo_fetcher.requests.post")
    def test_returns_records(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "announcements": [
                {"announcementTitle": "年度报告", "announcementTypeName": "年报",
                 "announcementTime": 1716768000000, "announcementId": "123456"}
            ]
        }
        mock_post.return_value = mock_response
        result = self.fetcher.get_announcements("600519")
        assert len(result) == 1
        assert result[0]["title"] == "年度报告"
        assert result[0]["type"] == "年报"
        assert result[0]["date"] == "2024-05-27"


class TestHistoricalNotSupported:
    def test_fetch_raw_data_raises(self):
        from stock_data.data_provider.base import DataFetchError
        f = CninfoFetcher()
        with pytest.raises(DataFetchError):
            f._fetch_raw_data("600519", "", "")

    def test_normalize_data_raises(self):
        import pandas as pd

        from stock_data.data_provider.base import DataFetchError
        f = CninfoFetcher()
        with pytest.raises(DataFetchError):
            f._normalize_data(pd.DataFrame(), "600519")
