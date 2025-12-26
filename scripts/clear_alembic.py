"""Clear agent_alembic_version table before fresh migration."""
import asyncio
from sqlalchemy import text
from src.db.session import get_session_context


async def clear_agent_alembic():
    async with get_session_context() as session:
        await session.execute(text("DELETE FROM agent_alembic_version"))
        print("✅ Cleared agent_alembic_version table")


if __name__ == "__main__":
    asyncio.run(clear_agent_alembic())
