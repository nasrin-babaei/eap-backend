import logging
from datetime import datetime, timedelta, timezone
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(user_id: int, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }

    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

logger = logging.getLogger(__name__)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        logger.warning("Token decode failed: expired.")
        return None
    except JWTError as e:
        # IT35-332: this used to be a bare `except Exception: return None`,
        # which silently swallows every possible failure reason. When a user
        # reports an intermittent "session expired" that a bare except can't
        # explain, this is the only way to find out whether it was really an
        # expired token, a bad signature, a malformed token, or something else.
        logger.warning("Token decode failed: %s", e)
        return None
    except Exception as e:
        # Anything genuinely unexpected (not a JWT-shaped failure at all) —
        # keep the original behavior of returning None/401 rather than a
        # 500, but log it with full detail, since this path should be rare
        # enough that seeing it in the logs is itself useful signal.
        logger.exception("Unexpected error decoding token: %s", e)
        return None
