import asyncio

from app.core.database import init_db


def main():
    asyncio.run(init_db())


if __name__ == "__main__":
    main()
