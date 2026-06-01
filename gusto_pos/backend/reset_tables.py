"""
Reset table_sessions: truncate and reseed N-1..N-10 (normal) + A-1..A-4 (ac).
Run from the backend/ folder: python reset_tables.py
"""
import asyncio
import random
import string
import uuid
from datetime import datetime, timedelta

import asyncpg

DSN = "postgresql://neondb_owner:npg_FNVST1qQshi6@ep-frosty-fire-aobvdei1.c-2.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
OUTLET_ID = "0b8a8349-6144-41a8-b028-b9089bd8eaea"
TTL_HOURS = 24

TABLES = (
    [(f"N-{i}", "normal") for i in range(1, 11)] +
    [(f"A-{i}", "ac")     for i in range(1, 5)]
)


def make_token(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute("TRUNCATE TABLE table_sessions")
        print("Truncated table_sessions.")

        expires_at = datetime.utcnow() + timedelta(hours=TTL_HOURS)
        n1_token = None

        for table_id, zone in TABLES:
            token = make_token()
            await conn.execute(
                """
                INSERT INTO table_sessions
                    (id, token, outlet_id, table_id, zone, is_active, expires_at)
                VALUES ($1, $2, $3, $4, $5, true, $6)
                """,
                str(uuid.uuid4()), token, OUTLET_ID, table_id, zone, expires_at,
            )
            print(f"  {table_id:<6} {zone:<8} token={token}  /menu/{token}")
            if table_id == "N-1":
                n1_token = token

        print()
        print(f"Sessions expire: {expires_at.strftime('%Y-%m-%d %H:%M')} UTC ({TTL_HOURS}h)")
        print()
        print(f"Table N-1 URL:  http://localhost:3000/menu/{n1_token}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
