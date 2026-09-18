import asyncio
from app.database import engine, Base
import app.models  # Registers models with Base.metadata

async def init_tables():
    print("Syncing schema with Neon PostgreSQL...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables initialized successfully in Neon PostgreSQL!")

if __name__ == "__main__":
    asyncio.run(init_tables())