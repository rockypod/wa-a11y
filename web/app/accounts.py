# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import getpass
import hashlib
import secrets
import sys
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlmodel import Session, delete, select

from app.store.db import get_engine
from app.store.models import AuthSession, Role, User

SESSION_HOURS = 12  # WCAG 2.2 SC 2.2.6: session length is stated on the sign-in page
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 12  # NIST SP 800-63B: length over composition rules
MAX_PASSWORD = 256

_hasher = PasswordHasher()
_DUMMY = _hasher.hash("timing-equaliser-not-a-password")  # hide whether an email exists


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters. A short sentence works well."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    return None


def create_user(
    session: Session, email: str, password: str, role: Role = Role.USER, name: str = ""
) -> User:
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    user = User(
        email=normalise_email(email), name=name, role=role, password_hash=_hasher.hash(password)
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def set_password(session: Session, user: User, password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    user.password_hash = _hasher.hash(password)
    user.failed_logins, user.locked_until = 0, None
    session.add(user)
    session.exec(delete(AuthSession).where(AuthSession.user_id == user.id))  # sign out everywhere
    session.commit()


def authenticate(session: Session, email: str, password: str) -> User | None:
    # One generic failure path: never reveal whether an email exists, is locked or is disabled
    user = session.exec(select(User).where(User.email == normalise_email(email))).first()
    if user is None:
        _verify(_DUMMY, password)  # same cost as a real check
        return None
    locked = _aware(user.locked_until)
    if locked and locked > _now():
        _verify(_DUMMY, password)
        return None
    if not user.is_active or not _verify(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until, user.failed_logins = _now() + timedelta(minutes=LOCK_MINUTES), 0
        session.add(user)
        session.commit()
        return None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, _now()
    session.add(user)
    session.commit()
    return user


def _verify(hashed: str, password: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User) -> str:
    # Only the token's hash is stored
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=_now() + timedelta(hours=SESSION_HOURS),
        )
    )
    session.exec(delete(AuthSession).where(AuthSession.expires_at < _now()))
    session.commit()
    return token


def user_for_token(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = session.exec(
        select(AuthSession).where(AuthSession.token_hash == _token_hash(token))
    ).first()
    if row is None or _aware(row.expires_at) <= _now():
        return None
    user = session.get(User, row.user_id)
    return user if user is not None and user.is_active else None


def end_session(session: Session, token: str | None) -> None:
    if token:
        session.exec(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        session.commit()


def any_users(session: Session) -> bool:
    return session.exec(select(User.id).limit(1)).first() is not None


def _ask_password() -> str:
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords did not match.")
    return first


USAGE = """Usage:
    python -m app.accounts create <email> [--admin] [--name "Full Name"]   (prompts for password)
    python -m app.accounts reset-password <email>
    python -m app.accounts disable <email> | enable <email> | list"""


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"create", "reset-password", "disable", "enable", "list"}:
        raise SystemExit(USAGE)
    with Session(get_engine()) as s:
        if argv[0] == "list":
            for u in s.exec(select(User).order_by(User.email)):
                state = "active" if u.is_active else "disabled"
                print(f"{u.email}\t{u.role.value}\t{state}\tlast sign-in: {u.last_login_at or '-'}")
            return 0
        email = normalise_email(argv[1]) if len(argv) > 1 else ""
        if not email:
            raise SystemExit("Give an email address.")
        user = s.exec(select(User).where(User.email == email)).first()
        if argv[0] == "create":
            if user:
                raise SystemExit("That account already exists.")
            name = argv[argv.index("--name") + 1] if "--name" in argv else ""
            role = Role.ADMIN if "--admin" in argv else Role.USER
            try:
                create_user(s, email, _ask_password(), role, name)
            except ValueError as err:
                raise SystemExit(str(err)) from err
            print(f"created {email} ({role.value})")
            return 0
        if user is None:
            raise SystemExit("No such account.")
        if argv[0] == "reset-password":
            try:
                set_password(s, user, _ask_password())
            except ValueError as err:
                raise SystemExit(str(err)) from err
            print("password changed; all sessions signed out")
        else:
            user.is_active = argv[0] == "enable"
            s.add(user)
            if not user.is_active:
                s.exec(delete(AuthSession).where(AuthSession.user_id == user.id))
            s.commit()
            print(f"{email} {'enabled' if user.is_active else 'disabled'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
