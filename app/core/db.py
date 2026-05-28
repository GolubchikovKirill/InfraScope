from sqlmodel import Session, create_engine

from app.core.config import settings
from app.domains.identity.models import User

engine = create_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)


def init_db(session: Session) -> None:
    from sqlmodel import select

    from app.core.security import get_password_hash

    if settings.ENVIRONMENT == "production" and settings._is_weak_bootstrap_password(settings.FIRST_SUPERUSER_PASSWORD):
        raise RuntimeError("Refusing to bootstrap admin user with a weak production password")

    user = session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)).first()

    if not user:
        user = User(
            email=settings.FIRST_SUPERUSER_EMAIL,
            hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
            full_name="Admin",
            is_superuser=True,
            is_active=True,
        )
        session.add(user)
        session.commit()
