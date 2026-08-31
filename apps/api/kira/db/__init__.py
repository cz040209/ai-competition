"""Database models and session dependency."""

from kira.db import models as _models  # noqa: F401 -- register all tables on package import
from kira.db.base import Base
from kira.db.session import get_session

__all__ = ["Base", "get_session"]
