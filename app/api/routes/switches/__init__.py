from fastapi import APIRouter

from . import access_points, auto_reboot, crud, polling, ports

router = APIRouter()
router.include_router(crud.router)
router.include_router(polling.router)
router.include_router(access_points.router)
router.include_router(auto_reboot.router)
router.include_router(ports.router)
