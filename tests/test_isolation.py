from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def test_committed_user_is_visible_inside_test(db_session: AsyncSession) -> None:
    db_session.add(User(email="isolation@example.com", password_hash="x"))
    await db_session.commit()

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 1


async def test_previous_test_left_no_trace(db_session: AsyncSession) -> None:
    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 0
