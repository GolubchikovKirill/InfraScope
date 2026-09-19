"""Import every domain's ORM models so SQLModel's metadata knows all the tables.

Alembic autogenerate and `SQLModel.metadata.create_all` (the test database) only
see tables whose model module has been imported. Nothing else needs this module:
runtime code imports the models it uses straight from `app.domains.<domain>.models`.
"""

from app.domains.credentials import models as credentials
from app.domains.identity import models as identity
from app.domains.integrations import models as integrations
from app.domains.inventory import models as inventory
from app.domains.media_center import models as media_center
from app.domains.ml import models as ml
from app.domains.operations import models as operations
from app.domains.remote_access import models as remote_access

__all__ = [
    "credentials",
    "identity",
    "integrations",
    "inventory",
    "media_center",
    "ml",
    "operations",
    "remote_access",
]
