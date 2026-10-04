"""Account and server-side session use cases."""

from __future__ import annotations

import asyncio
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from firstlook.audit.service import AuditInput, append_event
from firstlook.crypto import (
    encrypt_system_field,
    lookup_hmac,
    new_dek,
    secret_key_from_hex,
    token_hash,
    wrap_dek,
)
from firstlook.db import app_sessions, set_patient_scope
from firstlook.identity.models import (
    LoginAttempt,
    Membership,
    MfaRecoveryCode,
    Organisation,
    Session,
    User,
)
from firstlook.identity.security import (
    hash_password,
    new_session_token,
    new_totp_secret,
    verify_password,
    verify_totp,
)
from firstlook.profile.models import Consent, Patient
from firstlook.settings import get_settings, read_secret


class AuthenticationError(PermissionError):
    pass


class LoginThrottled(AuthenticationError):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant: str
    role: str
    org_id: UUID | None
    org_active: bool
    mfa_passed: bool
    locale: str
    theme: str
    session_hash: bytes


@dataclass(frozen=True)
class LoginResult:
    token: str
    principal: Principal
    mfa_required: bool
    mfa_setup_required: bool
    recovery_codes: tuple[str, ...] = ()


def _keys() -> tuple[bytes, bytes]:
    settings = get_settings()
    kek = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_kek"))
    pepper = secret_key_from_hex(read_secret(settings.fl_secret_dir / "fl_pepper"))
    return kek, pepper


def _now() -> datetime:
    return datetime.now(UTC)


def _email_lookup(pepper: bytes, email: str) -> bytes:
    return lookup_hmac(pepper, "email", email.strip().casefold())


def login_is_throttled(account_failures: int, ip_failures: int) -> bool:
    """Block at ten account or fifty source-IP failures in ten minutes."""
    return account_failures >= 10 or ip_failures >= 50


async def register_patient(email: str, password: str, locale: str, consent: bool) -> UUID:
    """Create an empty encrypted patient profile in one app-role transaction."""
    if not consent:
        raise ValueError("profile storage consent is required")
    settings = get_settings()
    kek, pepper = _keys()
    user_id, patient_id = uuid4(), uuid4()
    hashed_password = await asyncio.to_thread(hash_password, password)
    user = User(
        id=user_id,
        email_hmac=_email_lookup(pepper, email),
        email_enc=encrypt_system_field(kek, user_id, "email", email.strip().encode("utf-8")),
        password_hash=hashed_password,
        locale=locale,
        theme="system",
        kind="patient",
        tenant=settings.fl_env,
        status="active" if settings.fl_env == "demo" else "pending_email",
        created_at=_now(),
    )
    patient = Patient(
        id=patient_id,
        owner_user_id=user_id,
        dek_wrapped=wrap_dek(kek, new_dek(), patient_id, 1, "file-v1"),
        dek_version=1,
        kek_id="file-v1",
        created_at=_now(),
    )
    async with app_sessions()() as session:
        try:
            async with session.begin():
                session.add(user)
                await session.flush()
                await set_patient_scope(session, patient_id)
                session.add(patient)
                await session.flush()
                session.add(
                    Consent(
                        id=uuid4(),
                        patient_id=patient_id,
                        type="profile_storage",
                        granted=True,
                        policy_version="1",
                        ts=_now(),
                    )
                )
                await append_event(
                    session,
                    AuditInput(
                        patient_id=patient_id,
                        actor_type="patient",
                        actor_id=user_id,
                        org_id=None,
                        role="patient",
                        tier="owner",
                        action="account.create",
                        purpose="profile_storage",
                        categories=("consent",),
                        session_ref=None,
                        outcome="allowed",
                    ),
                )
        except IntegrityError as exc:
            raise ValueError("registration could not be completed") from exc
    return user_id


async def _membership(
    session: AsyncSession,
    user: User,
    selected_org: UUID | None,
) -> tuple[str, UUID | None, bool]:
    query = (
        select(Membership, Organisation)
        .join(Organisation, Membership.org_id == Organisation.id)
        .where(
            Membership.user_id == user.id,
            Membership.active.is_(True),
            Organisation.active.is_(True),
        )
    )
    if selected_org is not None:
        query = query.where(Membership.org_id == selected_org)
    result = await session.execute(query)
    rows = [(membership, org) for membership, org in result.tuples() if org.tenant == user.tenant]
    if selected_org is not None and not rows:
        raise AuthenticationError("invalid credentials")
    if len(rows) > 1:
        raise AuthenticationError("select an organisation")
    if rows:
        membership, org = rows[0]
        return membership.role, org.id, org.active
    if user.kind != "patient":
        raise AuthenticationError("invalid credentials")
    return "patient", None, False


async def _issue_session(
    session: AsyncSession,
    user: User,
    role: str,
    org_id: UUID | None,
    mfa_passed: bool,
    ip: str,
    user_agent: str,
    pepper: bytes,
) -> tuple[str, Session]:
    settings = get_settings()
    token = new_session_token()
    now = _now()
    lifetime = (
        timedelta(hours=settings.fl_session_ttl_professional_hours)
        if role != "patient"
        else timedelta(hours=12)
    )
    record = Session(
        id_hash=token_hash(token),
        user_id=user.id,
        org_id=org_id,
        kind="professional" if role != "patient" else "patient",
        mfa_passed=mfa_passed,
        created_at=now,
        last_seen_at=now,
        expires_at=now + lifetime,
        revoked_at=None,
        ip_hash=lookup_hmac(pepper, f"session-ip:{now.date()}", ip),
        ua_hash=lookup_hmac(pepper, "session-ua", user_agent),
    )
    session.add(record)
    await session.flush()
    return token, record


async def login(
    email: str, password: str, ip: str, user_agent: str, org_id: UUID | None
) -> LoginResult:
    """Throttle, verify Argon2id and issue a revocable opaque session."""
    settings = get_settings()
    _, pepper = _keys()
    email_hash = _email_lookup(pepper, email)
    ip_hash = lookup_hmac(pepper, f"login-ip:{_now().date()}", ip)
    since = _now() - timedelta(minutes=10)
    failed_count = 0
    result: LoginResult | None = None
    async with app_sessions()() as session:
        async with session.begin():
            account_failures = (
                await session.scalar(
                    select(func.count())
                    .select_from(LoginAttempt)
                    .where(
                        LoginAttempt.email_hmac == email_hash,
                        LoginAttempt.failed.is_(True),
                        LoginAttempt.ts >= since,
                    )
                )
                or 0
            )
            ip_failures = (
                await session.scalar(
                    select(func.count())
                    .select_from(LoginAttempt)
                    .where(
                        LoginAttempt.ip_hash == ip_hash,
                        LoginAttempt.failed.is_(True),
                        LoginAttempt.ts >= since,
                    )
                )
                or 0
            )
            if login_is_throttled(account_failures, ip_failures):
                raise LoginThrottled("login temporarily unavailable")
            user = await session.scalar(select(User).where(User.email_hmac == email_hash))
            valid_password = await asyncio.to_thread(
                verify_password, user.password_hash if user else None, password
            )
            account_ok = bool(
                user
                and valid_password
                and user.status == "active"
                and user.tenant == settings.fl_env
            )
            if not account_ok:
                failed_count = max(account_failures, ip_failures) + 1
                session.add(
                    LoginAttempt(
                        id=uuid4(), email_hmac=email_hash, ip_hash=ip_hash, failed=True, ts=_now()
                    )
                )
            else:
                assert user is not None
                role, selected_org, org_active = await _membership(session, user, org_id)
                requires_mfa = (
                    role != "patient" and user.tenant != "demo"
                ) or user.mfa_secret_enc is not None
                token, record = await _issue_session(
                    session, user, role, selected_org, not requires_mfa, ip, user_agent, pepper
                )
                result = LoginResult(
                    token=token,
                    principal=Principal(
                        user_id=user.id,
                        tenant=user.tenant,
                        role=role,
                        org_id=selected_org,
                        org_active=org_active,
                        mfa_passed=record.mfa_passed,
                        locale=user.locale,
                        theme=user.theme,
                        session_hash=record.id_hash,
                    ),
                    mfa_required=requires_mfa,
                    mfa_setup_required=requires_mfa and user.mfa_secret_enc is None,
                )
    if result is None:
        await asyncio.sleep(min(0.1 * 2 ** min(failed_count, 4), 1.6))
        raise AuthenticationError("invalid credentials")
    return result


async def load_principal(token: str | None, *, allow_pending_mfa: bool = False) -> Principal:
    """Validate revocation, idle/absolute expiry, membership and current tenant."""
    if not token:
        raise AuthenticationError("authentication required")
    settings = get_settings()
    hashed = token_hash(token)
    now = _now()
    async with app_sessions()() as session:
        async with session.begin():
            record = await session.scalar(
                select(Session).where(Session.id_hash == hashed).with_for_update()
            )
            if record is None or record.revoked_at is not None or record.user_id is None:
                raise AuthenticationError("authentication required")
            idle_ttl = (
                timedelta(minutes=settings.fl_session_ttl_patient_minutes)
                if record.kind == "patient"
                else timedelta(hours=settings.fl_session_ttl_professional_hours)
            )
            if now >= record.expires_at or now - record.last_seen_at >= idle_ttl:
                record.revoked_at = now
                return_failure = True
            else:
                return_failure = False
            if return_failure:
                # Commit revocation before returning a generic error.
                principal = None
            else:
                user = await session.get(User, record.user_id)
                if user is None or user.status != "active" or user.tenant != settings.fl_env:
                    raise AuthenticationError("authentication required")
                role, org_id, org_active = await _membership(session, user, record.org_id)
                if record.kind == "professional" and (org_id is None or not org_active):
                    raise AuthenticationError("authentication required")
                if not record.mfa_passed and not allow_pending_mfa:
                    raise AuthenticationError("MFA required")
                record.last_seen_at = now
                principal = Principal(
                    user_id=user.id,
                    tenant=user.tenant,
                    role=role,
                    org_id=org_id,
                    org_active=org_active,
                    mfa_passed=record.mfa_passed,
                    locale=user.locale,
                    theme=user.theme,
                    session_hash=record.id_hash,
                )
    if principal is None:
        raise AuthenticationError("authentication required")
    return principal


async def setup_mfa(token: str, principal: Principal) -> str:
    """Stage a TOTP secret for a password-verified pending-MFA session."""
    if principal.mfa_passed:
        raise AuthenticationError("MFA is already active")
    kek, _ = _keys()
    secret = new_totp_secret()
    async with app_sessions()() as session:
        async with session.begin():
            record = await session.get(Session, token_hash(token))
            user = await session.get(User, principal.user_id)
            if record is None or user is None or record.mfa_passed or user.mfa_secret_enc:
                raise AuthenticationError("MFA setup unavailable")
            user.mfa_pending_secret_enc = encrypt_system_field(
                kek, user.id, "mfa-pending", secret.encode("ascii")
            )
    return secret


async def verify_mfa_login(
    token: str,
    code: str,
    ip: str,
    user_agent: str,
) -> LoginResult:
    """Verify TOTP, activate a staged secret, and rotate the session token."""
    from firstlook.crypto import decrypt_system_field

    principal = await load_principal(token, allow_pending_mfa=True)
    if principal.mfa_passed:
        raise AuthenticationError("MFA is already complete")
    kek, pepper = _keys()
    async with app_sessions()() as session:
        async with session.begin():
            record = await session.get(Session, token_hash(token), with_for_update=True)
            user = await session.get(User, principal.user_id, with_for_update=True)
            if record is None or user is None or record.revoked_at is not None:
                raise AuthenticationError("authentication required")
            pending = user.mfa_pending_secret_enc is not None
            encrypted = user.mfa_pending_secret_enc if pending else user.mfa_secret_enc
            if encrypted is None:
                raise AuthenticationError("MFA setup required")
            field = "mfa-pending" if pending else "mfa"
            secret = decrypt_system_field(kek, user.id, field, encrypted).decode("ascii")
            valid_code = verify_totp(secret, code)
            if not valid_code and not pending and re.fullmatch(r"[A-Za-z0-9_-]{22}", code):
                recovery = await session.scalar(
                    select(MfaRecoveryCode)
                    .where(
                        MfaRecoveryCode.user_id == user.id,
                        MfaRecoveryCode.code_hash == token_hash(code),
                        MfaRecoveryCode.used_at.is_(None),
                    )
                    .with_for_update()
                )
                if recovery is not None:
                    recovery.used_at = _now()
                    valid_code = True
            if not valid_code:
                raise AuthenticationError("invalid verification code")
            recovery_codes: tuple[str, ...] = ()
            if pending:
                user.mfa_secret_enc = encrypt_system_field(
                    kek, user.id, "mfa", secret.encode("ascii")
                )
                user.mfa_pending_secret_enc = None
                recovery_codes = tuple(secrets.token_urlsafe(16) for _ in range(10))
                session.add_all(
                    MfaRecoveryCode(user_id=user.id, code_hash=token_hash(value))
                    for value in recovery_codes
                )
            record.revoked_at = _now()
            new_token, new_record = await _issue_session(
                session, user, principal.role, principal.org_id, True, ip, user_agent, pepper
            )
            return LoginResult(
                token=new_token,
                principal=Principal(
                    user_id=user.id,
                    tenant=user.tenant,
                    role=principal.role,
                    org_id=principal.org_id,
                    org_active=principal.org_active,
                    mfa_passed=True,
                    locale=user.locale,
                    theme=user.theme,
                    session_hash=new_record.id_hash,
                ),
                mfa_required=False,
                mfa_setup_required=False,
                recovery_codes=recovery_codes,
            )


async def logout(token: str) -> None:
    async with app_sessions()() as session:
        async with session.begin():
            record = await session.get(Session, token_hash(token), with_for_update=True)
            if record is not None:
                record.revoked_at = _now()


async def revoke_user_sessions(session: AsyncSession, user_id: UUID) -> None:
    """Call after a role change so old privileges end in the same transaction."""
    rows = (
        await session.scalars(
            select(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
        )
    ).all()
    for row in rows:
        row.revoked_at = _now()
