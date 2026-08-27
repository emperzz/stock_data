"""Computed K-line feature layer for the agent batch-profile endpoints.

Pure compute on top of the indicator layer — never touches the network
or the manager. ``build_features`` turns a K-line DataFrame into the
trend / pivots / volume blocks consumed by ``/agent/*/batch-profile``.
"""

from .build import build_features

__all__ = ["build_features"]
