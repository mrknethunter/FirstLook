"""Async database engines for the application and identity vault roles."""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from firstlook.settings import get_settings, read_secret


@lru_cache
def app_engine() -> AsyncEngine:
    url = read_secret(get_settings().fl_secret_dir / "fl_db_app")
    return create_async_engine(
        url, pool_pre_ping=True, connect_args={"options": "-c statement_timeout=5000"}
    )


@lru_cache
def vault_engine() -> AsyncEngine:
    url = read_secret(get_settings().fl_secret_dir / "fl_db_vault")
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def worker_engine() -> AsyncEngine:
    url = read_secret(get_settings().fl_secret_dir / "fl_db_worker")
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def app_sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine(), expire_on_commit=False)


@lru_cache
def vault_sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(vault_engine(), expire_on_commit=False)


@lru_cache
def worker_sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(worker_engine(), expire_on_commit=False)


async def set_patient_scope(session: AsyncSession, patient_id: UUID) -> None:
    """Set the transaction-local RLS subject after application authorisation."""
    await session.execute(
        text("SELECT set_config('firstlook.patient_id', :patient_id, true)"),
        {"patient_id": str(patient_id)},
    )
