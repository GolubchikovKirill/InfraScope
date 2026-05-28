"""Backward-compatible ORM model exports.

Concrete model definitions live in `app.domains.*.models`. Keep this module as
the stable import surface for existing route, service, test, and Alembic code
while the codebase moves toward domain-local imports.
"""

from app.domains.identity.models import User
from app.domains.inventory.models import (
    CartridgeStock,
    CartridgeStockMovement,
    Computer,
    MediaPlayer,
    NetworkSwitch,
    Printer,
)
from app.domains.media_center.models import MediaAsset, MediaAssignment, MediaClientHeartbeat
from app.domains.ml.models import (
    MLFeatureSnapshot,
    MLModelRegistry,
    MLOfflineRiskPrediction,
    MLTonerPrediction,
)
from app.domains.operations.models import AppSetting, CashRegister, EventLog

__all__ = [
    "AppSetting",
    "CashRegister",
    "CartridgeStock",
    "CartridgeStockMovement",
    "Computer",
    "EventLog",
    "MediaPlayer",
    "MediaAsset",
    "MediaAssignment",
    "MediaClientHeartbeat",
    "MLFeatureSnapshot",
    "MLModelRegistry",
    "MLOfflineRiskPrediction",
    "MLTonerPrediction",
    "NetworkSwitch",
    "Printer",
    "User",
]
