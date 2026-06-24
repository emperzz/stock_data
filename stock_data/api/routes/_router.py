"""Shared APIRouter for the routes package.

Lives in its own module (with a leading underscore so it's clearly internal)
so domain modules can ``from ._router import router`` without triggering a
circular import back through ``__init__.py``.
"""

from fastapi import APIRouter

router = APIRouter()
