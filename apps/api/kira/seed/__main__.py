"""python -m kira.seed — load the demo user into the configured database."""

from __future__ import annotations

import asyncio

from kira.db.session import get_sessionmaker
from kira.seed.demo import DEMO_EMAIL, seed_demo_user


async def main() -> None:
    async with get_sessionmaker()() as session:
        await seed_demo_user(session)
        await session.commit()
    print(f"Seeded {DEMO_EMAIL}")


if __name__ == "__main__":
    asyncio.run(main())
