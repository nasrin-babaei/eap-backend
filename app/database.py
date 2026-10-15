from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    # IT35-332: the default pool (5 + 10 overflow) had no headroom under a
    # burst of concurrent logins/requests during automated testing. Raising
    # this is a reasonable mitigation for that trigger, but is not a
    # confirmed root-cause fix — the logging added to decode_access_token
    # and get_current_user is what will tell us, if this recurs, whether
    # pool exhaustion was actually the cause.
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()