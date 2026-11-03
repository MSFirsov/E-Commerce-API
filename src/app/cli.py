import argparse
import asyncio
import getpass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import engine, session_factory
from app.core.security import hash_password_async
from app.models import RefreshToken, RevokeReason, User, UserRole


async def create_admin(session: AsyncSession, email: str, password: str) -> tuple[User, bool]:
    normalized_email = email.lower()
    user = await session.scalar(select(User).where(User.email == normalized_email))

    if user is None:
        user = User(
            email=normalized_email,
            password_hash=await hash_password_async(password),
            role=UserRole.ADMIN,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user, True

    user.role = UserRole.ADMIN
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revoked_reason=RevokeReason.ADMIN)
    )
    await session.commit()
    return user, False


async def _run(email: str) -> None:
    password = getpass.getpass("Password for the admin account: ")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters long")

    async with session_factory() as session:
        user, created = await create_admin(session, email, password)

    await engine.dispose()
    action = "created" if created else "promoted, existing sessions revoked"
    print(f"Admin {user.email} {action}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create_admin_parser = subcommands.add_parser("create-admin")
    create_admin_parser.add_argument("--email", required=True)

    args = parser.parse_args()
    if args.command == "create-admin":
        asyncio.run(_run(args.email))


if __name__ == "__main__":
    main()
