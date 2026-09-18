import os
import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "")

# Initialize decoded text client
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

async def get_redis():
    return redis_client