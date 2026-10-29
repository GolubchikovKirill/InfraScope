"""Set the local admin's password to FIRST_SUPERUSER_PASSWORD from .env.

init_db only creates the admin when it is missing, so after a prod dump is
restored into a local stack the admin row carries the production hash and the
local password from .env does not work. Run inside the backend container:

    docker compose -p infrascope-local exec -T backend python - < scripts/dev_reset_admin.py
"""

import sys

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.security import get_password_hash
from app.domains.identity.models import User

if settings.ENVIRONMENT == "production":
    sys.exit("Refusing to reset the admin password on a production instance.")

with Session(engine) as session:
    user = session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)).first()
    if user is None:
        user = User(email=settings.FIRST_SUPERUSER_EMAIL, full_name="Admin")
    user.hashed_password = get_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
    user.is_active = True
    user.is_superuser = True
    session.add(user)
    session.commit()
    print(f"{settings.FIRST_SUPERUSER_EMAIL}: password set from FIRST_SUPERUSER_PASSWORD")
