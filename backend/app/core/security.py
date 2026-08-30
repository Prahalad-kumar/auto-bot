from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Keep bcrypt available so users created by the existing 0002 migration can
# still authenticate, while using PBKDF2-SHA256 for newly created passwords.
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(subject: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": subject, "exp": exp},
        settings.JWT_SECRET,
        algorithm=ALGORITHM,
    )
