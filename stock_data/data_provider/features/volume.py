"""Volume block for the agent batch-profile feature layer.

Pure compute: takes a K-line DataFrame (STANDARD_COLUMNS) plus a
pre-sliced window frame and returns the volume facts an agent needs for
`market-principles` §5.2 volume-price judgment:
  - latest_volume: newest bar's volume
  - vol_ratio_5:   newest bar / mean of the previous 5 bars (excl. current)
  - z_anomalies:   bars in the window whose volume Z-score > 2.0
"""

from __future__ import annotations

import pandas as pd

_Z_THRESHOLD = 2.0
_MAX_ANOMALIES = 20


def _float(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def compute_volume(df: pd.DataFrame, window_df: pd.DataFrame) -> dict:
    """Compute the volume block. Returns a dict ready for Pydantic."""
    if df is None or df.empty:
        return {"latest_volume": None, "vol_ratio_5": None, "z_anomalies": []}

    latest_volume = _float(df["volume"].iloc[-1])

    vol_ratio_5: float | None = None
    if len(df) >= 6:
        prev5 = pd.to_numeric(df["volume"].iloc[-6:-1], errors="coerce").mean()
        if latest_volume is not None and prev5 and prev5 > 0:
            vol_ratio_5 = latest_volume / float(prev5)

    anomalies: list[dict] = []
    if window_df is not None and not window_df.empty:
        vols = pd.to_numeric(window_df["volume"], errors="coerce")
        mean, std = vols.mean(), vols.std(ddof=0)
        if std and not pd.isna(std) and std > 0:
            zs = (vols - mean) / std
            for idx in window_df.index[zs > _Z_THRESHOLD]:
                row = window_df.loc[idx]
                pos = df.index.get_loc(idx)
                prev_close = df["close"].iloc[pos - 1] if pos > 0 else None
                pc = _float(prev_close)
                close_v = _float(row["close"])
                open_v = _float(row["open"])
                change_pct = (
                    (close_v - pc) / pc * 100
                    if (close_v is not None and pc and pc != 0)
                    else None
                )
                anomalies.append(
                    {
                        "date": str(row["date"]),
                        "open": open_v,
                        "high": _float(row["high"]),
                        "low": _float(row["low"]),
                        "close": close_v,
                        "volume": _float(row["volume"]),
                        "z_score": round(float(zs.loc[idx]), 2),
                        "direction": "up" if close_v is not None and open_v is not None and close_v >= open_v else "down",
                        "change_pct": change_pct,
                    }
                )
    anomalies.sort(key=lambda a: a["z_score"], reverse=True)
    anomalies = anomalies[:_MAX_ANOMALIES]
    return {"latest_volume": latest_volume, "vol_ratio_5": vol_ratio_5, "z_anomalies": anomalies}
