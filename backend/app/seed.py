from app.db.session import SessionLocal
from app.models import User
from app.core.security import hash_password
from app.core.config import settings

if not settings.BOOTSTRAP_ADMIN_EMAIL or not settings.BOOTSTRAP_ADMIN_PASSWORD:
    raise SystemExit("Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD to create an admin user.")

db = SessionLocal()
try:
    email = settings.BOOTSTRAP_ADMIN_EMAIL.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        print(f"User already exists: {email}")
    else:
        db.add(User(email=email, password_hash=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD)))
        db.commit()
        print(f"Created user: {email}")
finally:
    db.close()
