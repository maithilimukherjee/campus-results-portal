import os
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv
 
load_dotenv()
 
RAW_DB_URL = os.getenv("DATABASE_URL", "")
 
def sanitize_db_url(url: str) -> str:
    """Sanitizes Neon connection URLs for compatibility with asyncpg."""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    # Strip libpq-only parameters incompatible with asyncpg
    query_params.pop("channel_binding", None)
    query_params.pop("gssencmode", None)
    # Normalize sslmode to ssl
    if "sslmode" in query_params:
        ssl_val = query_params.pop("sslmode")[0]
        if ssl_val in ["require", "verify-ca", "verify-full"]:
            query_params["ssl"] = ["require"]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
 
DATABASE_URL = sanitize_db_url(RAW_DB_URL)
 
# High-Concurrency Async Engine with Connection Pooling
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,         # Persistent connections per worker
    max_overflow=10,      # Maximum burst connections during traffic spikes
    pool_timeout=30,      # Seconds to wait before throwing a pool exhaustion error
    pool_recycle=1800,    # Recycle connections every 30 mins to drop stale links
    pool_pre_ping=True    # Health-check connection before executing queries
)
 
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
 
class Base(DeclarativeBase):
    pass
 
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()