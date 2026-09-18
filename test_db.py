import asyncio
from app.database import engine
from app.redis_client import redis_client

async def test_cloud_connections():
    print("Testing Cloud Database Connections...")
    
    # 1. Test Neon PostgreSQL
    try:
        async with engine.connect() as conn:
            print("PostgreSQL (Neon) Connected Successfully!")
    except Exception as e:
        print(f"PostgreSQL Connection Failed: {e}")

    # 2. Test Upstash Redis
    try:
        await redis_client.set("hackathon_test", "active")
        status = await redis_client.get("hackathon_test")
        print(f"Redis (Upstash) Connected Successfully! Status: {status}")
    except Exception as e:
        print(f"Redis Connection Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_cloud_connections())