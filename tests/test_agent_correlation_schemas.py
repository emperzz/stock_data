"""Schema validation tests for POST /api/v1/agent/correlation/matrix."""
import pytest
from pydantic import ValidationError

from stock_data.api.schemas import (
    CorrelationAlignment,
    CorrelationErrorItem,
    CorrelationFrequency,
    CorrelationLabel,
    CorrelationMatrices,
    CorrelationMatrixRequest,
    CorrelationMatrixResponse,
    CorrelationMethod,
)


def test_frequency_enum_values():
    assert CorrelationFrequency("d").value == "d"
    assert CorrelationFrequency("60m").value == "60m"
    with pytest.raises(ValueError):
        CorrelationFrequency("2m")  # not in enum


def test_method_enum_values():
    assert CorrelationMethod("pearson").value == "pearson"
    assert CorrelationMethod("spearman").value == "spearman"


def test_label_stock_round_trip():
    label = CorrelationLabel(type="stock", code="600519", name="贵州茅台")
    assert label.model_dump() == {
        "type": "stock", "code": "600519", "name": "贵州茅台", "source": None
    }


def test_label_board_carries_source():
    label = CorrelationLabel(type="board", code="885595", name="白酒", source="ths")
    assert label.source == "ths"


def test_error_item_reason_in_set():
    err = CorrelationErrorItem(type="stock", code="600519", reason="data_unavailable")
    assert err.model_dump()["reason"] == "data_unavailable"


def test_alignment_round_trip():
    align = CorrelationAlignment(requested_days=90, common_bars=87, missing_after_join=3)
    assert align.requested_days == 90


def test_matrices_pearson_only():
    mat = CorrelationMatrices(pearson=[[1.0, 0.5], [0.5, 1.0]])
    assert mat.pearson == [[1.0, 0.5], [0.5, 1.0]]
    assert mat.spearman is None


def test_request_defaults_are_pearson_spearman_both():
    res = CorrelationMatrixRequest(stocks=["600519"], boards=[])
    assert res.frequency == CorrelationFrequency.d
    assert res.days == 90
    assert CorrelationMethod.pearson in res.methods
    assert CorrelationMethod.spearman in res.methods


def test_request_rejects_both_empty():
    with pytest.raises(ValidationError):
        CorrelationMatrixRequest(stocks=[], boards=[])


def test_response_serialization_omits_none_matrices():
    res = CorrelationMatrixResponse(
        labels=[CorrelationLabel(type="stock", code="600519")],
        frequency=CorrelationFrequency.d,
        days=90,
        alignment=CorrelationAlignment(requested_days=90, common_bars=90, missing_after_join=0),
        matrices=CorrelationMatrices(pearson=[[1.0]]),
        errors=[],
    )
    d = res.model_dump()
    assert d["matrices"]["pearson"] == [[1.0]]
    # matrices.spearman is None — value MUST appear as None in JSON (do not omit)
    assert "spearman" in d["matrices"]
