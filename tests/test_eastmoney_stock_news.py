"""Tests for EastMoneyFetcher.get_stock_news (np-listapi getListInfo direct HTTP)."""
from unittest.mock import MagicMock, patch

from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher


SAMPLE_RESPONSE = {
    "code": 1, "message": "success",
    "data": {
        "page_index": 1, "totle_hits": 5000, "page_size": 2,
        "list": [
            {
                "Art_Code": "202607023791611310",
                "Art_ShowTime": "2026-07-02 10:46:27",
                "Art_Title": "茅台酒扫码核验新功能上线试点",
                "Art_Url": "http://finance.eastmoney.com/a/202607023791611310.html",
                "Art_OriginUrl": "http://finance.eastmoney.com/news/1354,202607023791611310.html",
                "Np_dst": "CMS",
            },
            {
                "Art_Code": "20260702101113747001360",
                "Art_ShowTime": "2026-07-02 10:08:26",
                "Art_Title": "和讯投顾李梦琪：趁着科技吸血 布局红利高股息",
                "Art_Url": "http://caifuhao.eastmoney.com/news/20260702101113747001360",
                "Np_dst": "CFH",
                "Author": "和讯投资",
                "RelatedUid": "5257356418010938",
            },
        ],
    },
}


def _mock_resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def test_returns_normalized_list():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)):
        result = fetcher.get_stock_news("600519", limit=2)
    assert len(result) == 2
    first = result[0]
    assert first["title"] == "茅台酒扫码核验新功能上线试点"
    assert first["url"] == "http://finance.eastmoney.com/a/202607023791611310.html"
    assert first["publish_date"] == "2026-07-02"
    assert first["source_domain"] == "finance.eastmoney.com"
    assert first["media_name"] == "CMS"


def test_uses_mTypeAndCode_for_secid():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)) as m:
        fetcher.get_stock_news("600519", limit=5)
    called_kwargs = m.call_args.kwargs
    assert called_kwargs["params"]["mTypeAndCode"] == "1.600519"
    assert called_kwargs["params"]["pageSize"] == 5


def test_limit_clamped_to_100():
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get", return_value=_mock_resp(SAMPLE_RESPONSE)) as m:
        fetcher.get_stock_news("600519", limit=500)
    params = m.call_args.kwargs["params"]
    assert params["pageSize"] == 100


def test_returns_empty_list_on_no_data():
    fetcher = EastMoneyFetcher()
    empty = {"code": 1, "data": {"totle_hits": 0, "list": []}}
    with patch.object(fetcher._session, "get", return_value=_mock_resp(empty)):
        result = fetcher.get_stock_news("600519", limit=10)
    assert result == []


def test_invalid_code_returns_empty_list():
    """Invalid/empty code → return empty list (not None, not raise)."""
    fetcher = EastMoneyFetcher()
    with patch.object(fetcher._session, "get") as m:
        result = fetcher.get_stock_news("", limit=10)
    assert result == []
    m.assert_not_called()
