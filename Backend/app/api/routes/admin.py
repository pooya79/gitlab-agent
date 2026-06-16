import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_current_admin
from app.auth.jwt import create_access_token, create_jti, hash_token, new_refresh_token
from app.auth.password import verify_password
from app.core.config import settings
from app.core.time import utc_now
from app.db.database import get_mongo_database, get_next_sequence
from app.db.models import (
    Configs as ConfigsModel,
    LLMModelInfo as LLMModelInfoModel,
    RefreshSession,
    Users,
)
from app.schemas.admin import (
    AdminInfo,
    AdminLoginIn,
    AdminTokenOut,
    GitlabSettingsOut,
    GitlabSettingsUpdate,
)
from app.schemas.auth import RefreshTokenIn
from app.schemas.config import LLMModelInfo as LLMModelInfoSchema
from app.services.app_settings_service import get_app_settings, update_gitlab_settings

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/login", response_model=AdminTokenOut)
def admin_login(data: AdminLoginIn, mongo_db: Database = Depends(get_mongo_database)):
    """Authenticate an admin with username + password."""
    user = Users.from_document(mongo_db["users"].find_one({"username": data.username}))
    if (
        user is None
        or not user.is_superuser
        or not user.is_active
        or not verify_password(data.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    new_rf_token, new_rf_token_hash = new_refresh_token()
    new_jti = create_jti()
    access_token = create_access_token(user_id=str(user.id), jti=new_jti, is_admin=True)

    refresh_session = RefreshSession(
        id=get_next_sequence("refresh_sessions"),
        user_id=user.id,
        jti=new_jti,
        refresh_token_hash=new_rf_token_hash,
        expires_at=utc_now() + dt.timedelta(days=settings.refresh_token_expire_days),
    )
    mongo_db["refresh_sessions"].insert_one(refresh_session.to_document())

    return AdminTokenOut(
        access_token=access_token,
        refresh_token=new_rf_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=AdminTokenOut)
def admin_refresh(rf_in: RefreshTokenIn, mongo_db: Database = Depends(get_mongo_database)):
    """Refresh an admin session, re-minting an admin-scoped access token."""
    rf_token_hash = hash_token(rf_in.refresh_token)
    refresh_sessions = mongo_db["refresh_sessions"]

    session_doc = refresh_sessions.find_one(
        {"refresh_token_hash": rf_token_hash, "expires_at": {"$gt": utc_now()}}
    )
    if not session_doc:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = Users.from_document(mongo_db["users"].find_one({"id": session_doc["user_id"]}))
    if user is None or not user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    for _ in range(3):
        new_rf_token, new_rf_token_hash = new_refresh_token()
        new_jti = create_jti()
        access_token = create_access_token(
            user_id=str(user.id), jti=new_jti, is_admin=True
        )
        expires_at = utc_now() + dt.timedelta(days=settings.refresh_token_expire_days)
        try:
            refresh_sessions.update_one(
                {"_id": session_doc["_id"]},
                {
                    "$set": {
                        "jti": new_jti,
                        "refresh_token_hash": new_rf_token_hash,
                        "expires_at": expires_at,
                    }
                },
            )
        except DuplicateKeyError:
            continue

        return AdminTokenOut(
            access_token=access_token,
            refresh_token=new_rf_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    raise HTTPException(status_code=500, detail="Failed to refresh token, please try again.")


@router.post("/logout")
def admin_logout(rf_in: RefreshTokenIn, mongo_db: Database = Depends(get_mongo_database)):
    """Revoke the admin's refresh session."""
    rf_token_hash = hash_token(rf_in.refresh_token)
    mongo_db["refresh_sessions"].delete_many({"refresh_token_hash": rf_token_hash})
    return {"detail": "Logged out successfully"}


@router.get("/me", response_model=AdminInfo)
def admin_me(admin: Users = Depends(get_current_admin)):
    return AdminInfo(
        id=admin.id,
        email=admin.email,
        username=admin.username,
        is_superuser=admin.is_superuser,
    )


@router.get("/settings/gitlab", response_model=GitlabSettingsOut)
def get_gitlab_settings(
    mongo_db: Database = Depends(get_mongo_database),
    admin: Users = Depends(get_current_admin),
):
    s = get_app_settings(mongo_db)
    return GitlabSettingsOut(
        gitlab_base=s.gitlab_base,
        gitlab_client_id=s.gitlab_client_id,
        gitlab_client_secret_set=bool(s.gitlab_client_secret),
        gitlab_webhook_ssl_verify=s.gitlab_webhook_ssl_verify,
    )


@router.patch("/settings/gitlab", response_model=GitlabSettingsOut)
def patch_gitlab_settings(
    data: GitlabSettingsUpdate,
    mongo_db: Database = Depends(get_mongo_database),
    admin: Users = Depends(get_current_admin),
):
    fields = data.model_dump(exclude_unset=True)
    # A blank secret means "keep the existing one" — don't overwrite with empty.
    if not fields.get("gitlab_client_secret"):
        fields.pop("gitlab_client_secret", None)
    # webhook_ssl_verify is a bool and may legitimately be False; update_gitlab_settings
    # drops None values, so an explicit False still applies.
    s = update_gitlab_settings(mongo_db, **fields)
    return GitlabSettingsOut(
        gitlab_base=s.gitlab_base,
        gitlab_client_id=s.gitlab_client_id,
        gitlab_client_secret_set=bool(s.gitlab_client_secret),
        gitlab_webhook_ssl_verify=s.gitlab_webhook_ssl_verify,
    )


def _load_configs(mongo_db: Database) -> ConfigsModel:
    """Load the singleton Configs document or fail with a 500."""
    configs_doc = mongo_db["configs"].find_one({})
    configs_obj = ConfigsModel.from_document(configs_doc) if configs_doc else None
    if not configs_obj:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch LLM model configurations.",
        )
    return configs_obj


def _persist_available_llms(mongo_db: Database, configs_obj: ConfigsModel) -> None:
    mongo_db["configs"].update_one(
        {"_id": configs_obj._id},
        {
            "$set": {
                "available_llms": {
                    name: info.to_document()
                    for name, info in configs_obj.available_llms.items()
                }
            }
        },
    )


@router.get("/settings/llms", response_model=dict[str, LLMModelInfoSchema])
def list_llm_configs(
    mongo_db: Database = Depends(get_mongo_database),
    admin: Users = Depends(get_current_admin),
):
    """List the available LLM model configurations (admin)."""
    configs_obj = _load_configs(mongo_db)
    return {
        name: LLMModelInfoSchema.model_validate(info, from_attributes=True)
        for name, info in configs_obj.available_llms.items()
    }


@router.post("/settings/llms", response_model=LLMModelInfoSchema)
def add_update_llm_config(
    llm_info: LLMModelInfoSchema,
    mongo_db: Database = Depends(get_mongo_database),
    admin: Users = Depends(get_current_admin),
):
    """Add a new LLM model configuration or update an existing one (admin)."""
    configs_obj = _load_configs(mongo_db)
    configs_obj.available_llms[llm_info.model_name] = LLMModelInfoModel(
        **llm_info.model_dump()
    )
    _persist_available_llms(mongo_db, configs_obj)
    return llm_info


@router.delete("/settings/llms/{model_name:path}")
def delete_llm_config(
    model_name: str,
    mongo_db: Database = Depends(get_mongo_database),
    admin: Users = Depends(get_current_admin),
):
    """Delete an LLM model configuration (admin)."""
    configs_obj = _load_configs(mongo_db)
    if model_name not in configs_obj.available_llms:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM model '{model_name}' not found in available models.",
        )
    del configs_obj.available_llms[model_name]
    _persist_available_llms(mongo_db, configs_obj)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
