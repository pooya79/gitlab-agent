import datetime as dt

import gitlab
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.auth.gitlab import GitlabAuthService
from app.auth.jwt import decode_token
from app.core.config import settings
from app.core.log import logger
from app.core.time import ensure_utc, utc_now
from app.db.database import get_mongo_database
from app.db.models import OAuthAccount, Users
from app.services.app_settings_service import get_app_settings

security = HTTPBearer(auto_error=True)


def _utcnow() -> dt.datetime:
    return utc_now()


async def get_current_user(
    mongo_db: Database = Depends(get_mongo_database),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Users:
    """
    Dependency to get the current user based on the provided JWT token.
    Usage: async def endpoint(current_user: Users = Depends(get_current_user))
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except Exception as exc:  # pragma: no cover - defensive
        logger.info(f"Error decoding token: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        ) from exc

    user_id = payload.get("sub")
    jti = payload.get("jti")
    if user_id is None or jti is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    refresh_session = mongo_db["refresh_sessions"].find_one({"jti": jti})
    expires_at = (
        ensure_utc(refresh_session.get("expires_at")) if refresh_session else None
    )
    if not refresh_session or not expires_at or expires_at <= _utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or revoked",
        )

    try:
        user_doc = mongo_db["users"].find_one({"id": int(user_id)})
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    user = Users.from_document(user_doc)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


async def get_current_admin(
    mongo_db: Database = Depends(get_mongo_database),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Users:
    """
    Dependency for admin-only endpoints. Validates the JWT and its session like
    ``get_current_user``, but additionally requires the ``is_admin`` token claim
    and a superuser account.
    Usage: async def endpoint(admin: Users = Depends(get_current_admin))
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except Exception as exc:
        logger.info(f"Error decoding admin token: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        ) from exc

    user_id = payload.get("sub")
    jti = payload.get("jti")
    if user_id is None or jti is None or payload.get("is_admin") is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    refresh_session = mongo_db["refresh_sessions"].find_one({"jti": jti})
    expires_at = (
        ensure_utc(refresh_session.get("expires_at")) if refresh_session else None
    )
    if not refresh_session or not expires_at or expires_at <= _utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or revoked",
        )

    try:
        user_doc = mongo_db["users"].find_one({"id": int(user_id)})
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    user = Users.from_document(user_doc)
    if user is None or not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


async def get_gitlab_client(
    mongo_db: Database = Depends(get_mongo_database),
    current_user: Users = Depends(get_current_user),
) -> gitlab.Gitlab:
    """
    Dependency to get the GitLab client for the current user.
    Usage: async def endpoint(gitlab_client: gitlab.Gitlab = Depends(get_gitlab_client))
    """
    account_doc = mongo_db["oauth_accounts"].find_one(
        {"user_id": current_user.id, "provider": "gitlab"}
    )
    oauth_account = OAuthAccount.from_document(account_doc)
    if oauth_account is None:
        # Remove user session since no OAuth account exists
        mongo_db["refresh_sessions"].delete_many({"user_id": current_user.id})

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitLab OAuth account not found",
        )

    account_expires_at = ensure_utc(oauth_account.expires_at)
    if account_expires_at and account_expires_at <= _utcnow():
        async with httpx.AsyncClient() as client:
            try:
                gitlab_oauth = GitlabAuthService.from_db(mongo_db)
                token_response = await gitlab_oauth.refresh_token(
                    client=client,
                    refresh_token=oauth_account.refresh_token,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to refresh GitLab OAuth token",
                ) from exc

        expires_in = token_response.get("expires_in")
        update_doc: dict[str, object] = {
            "access_token": token_response["access_token"],
            "refresh_token": token_response.get(
                "refresh_token", oauth_account.refresh_token
            ),
            "token_type": token_response.get("token_type", oauth_account.token_type),
            "scope": token_response.get("scope", oauth_account.scope),
            "last_refreshed_at": _utcnow(),
        }
        if expires_in:
            update_doc["expires_at"] = _utcnow() + dt.timedelta(seconds=expires_in)

        try:
            mongo_db["oauth_accounts"].update_one(
                {"id": oauth_account.id},
                {"$set": update_doc},
            )
        except PyMongoError as exc:  # pragma: no cover - defensive
            logger.error(f"Failed to persist refreshed token: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store refreshed GitLab OAuth token",
            ) from exc

        oauth_account.access_token = update_doc["access_token"]

    gitlab_base = get_app_settings(mongo_db).gitlab_base
    return gitlab.Gitlab(gitlab_base, oauth_token=oauth_account.access_token)
