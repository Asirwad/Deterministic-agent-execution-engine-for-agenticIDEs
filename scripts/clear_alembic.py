"""
Temporary script to clear stale alembic_version.
Run this once, then delete.
"""

import asyncio
from sqlalchemy import text
from src.db.session import get_session_context


async def clear_alembic_version():
    async with get_session_context() as session:
        await session.execute(text("DELETE FROM alembic_version"))
        print("✅ Cleared alembic_version table")


if __name__ == "__main__":
    asyncio.run(clear_alembic_version())
