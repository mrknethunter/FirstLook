"""Declarative metadata shared by repository-owned table mappings."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
