from fastapi import APIRouter

from app.api import websockets
from app.api.routes import (
    app_settings,
    auth,
    boarding_pass,
    cash_registers,
    computers,
    honest_sign,
    logs,
    media_center,
    media_players,
    ml,
    observability,
    onec_exchange,
    printers,
    qr_generator,
    scanner,
    switches,
    tasks,
    users,
)

api_router = APIRouter()
api_router.include_router(websockets.router, prefix="/realtime")
api_router.include_router(auth.router, prefix="/auth")
api_router.include_router(users.router, prefix="/users")
api_router.include_router(printers.router, prefix="/printers")
api_router.include_router(scanner.router, prefix="/scanner")
api_router.include_router(media_players.router, prefix="/media-players")
api_router.include_router(media_center.router, prefix="/media-center")
api_router.include_router(switches.router, prefix="/switches")
api_router.include_router(cash_registers.router, prefix="/cash-registers")
api_router.include_router(computers.router, prefix="/computers")
api_router.include_router(honest_sign.router, prefix="/honest-sign")
api_router.include_router(ml.router, prefix="/ml")
api_router.include_router(logs.router, prefix="/logs")
api_router.include_router(app_settings.router, prefix="/app-settings")
api_router.include_router(onec_exchange.router, prefix="/1c-exchange")
api_router.include_router(qr_generator.router, prefix="/qr-generator")
api_router.include_router(boarding_pass.router, prefix="/boarding-pass")
api_router.include_router(observability.router, prefix="/observability")
api_router.include_router(tasks.router, prefix="/tasks")
