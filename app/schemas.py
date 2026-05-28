"""Backward-compatible API schema exports.

Concrete schema definitions live in `app.domains.*.schemas`. This module keeps
existing imports stable while route and service modules migrate to domain-local
schema imports.
"""

from app.domains.identity.schemas import *  # noqa: F403
from app.domains.integrations.schemas import *  # noqa: F403
from app.domains.inventory.schemas import *  # noqa: F403
from app.domains.ml.schemas import *  # noqa: F403
from app.domains.operations.schemas import *  # noqa: F403
from app.domains.shared.schemas import *  # noqa: F403
