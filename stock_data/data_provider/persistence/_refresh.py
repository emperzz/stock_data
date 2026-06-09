"""
Daily-refresh tracker shared by persistence submodules.

``DailyRefreshTracker`` replaces the duplicated ``_is_first_call_of_day``
functions that previously lived in ``stock_list.py`` and ``board.py``.
"""

from datetime import datetime
from threading import Lock


class DailyRefreshTracker:
    """Track whether a logical key has already been refreshed today.

    Usage::

        _tracker = DailyRefreshTracker()

        def get_data():
            if _tracker.is_first_call("my_key"):
                fetch_from_upstream()
    """

    def __init__(self) -> None:
        self._dates: dict[str, str] = {}
        self._lock = Lock()

    def is_first_call(self, key: str) -> bool:
        """Return True if this is the first call today for *key*, and
        record today's date so subsequent calls return False.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if self._dates.get(key) != today:
                self._dates[key] = today
                return True
            return False
