from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.domains.operations.schemas import GeneralSettingsPublic, GeneralSettingsUpdate
from app.services.app_settings import get_general_settings, update_general_settings

router = APIRouter(tags=["app-settings"])


@router.get("/general", response_model=GeneralSettingsPublic)
def read_general_settings(session: SessionDep, current_user: CurrentUser) -> GeneralSettingsPublic:
    del current_user
    return GeneralSettingsPublic(**get_general_settings(session))


@router.patch("/general", response_model=GeneralSettingsPublic, dependencies=[Depends(get_current_active_superuser)])
def patch_general_settings(session: SessionDep, payload: GeneralSettingsUpdate) -> GeneralSettingsPublic:
    values = payload.model_dump(exclude_unset=True)
    return GeneralSettingsPublic(**update_general_settings(session, values))
