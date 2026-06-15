import datetime as dt
import json
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_current_user
from app.auth.gitlab import GitlabAuthService
from app.auth.jwt import create_access_token, create_jti, hash_token, new_refresh_token
from app.core.config import settings
from app.core.log import logger
from app.core.time import utc_now
from app.db.database import get_mongo_database, get_next_sequence
from app.db.models import OAuthAccount, RefreshSession, Users
from app.schemas.auth import GitlabAuthUrl, RefreshTokenIn, RefreshTokenOut, UserInfo
from app.services.cache_service import CacheService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/refresh", response_model=RefreshTokenOut)
async def refresh_token(
    rf_in: RefreshTokenIn, mongo_db: Database = Depends(get_mongo_database)
):
    """
    Refresh access and refresh tokens using a valid refresh token.
    """
    rf_token_hash = hash_token(rf_in.refresh_token)
    refresh_sessions = mongo_db["refresh_sessions"]
    users = mongo_db["users"]

    user_session_doc = refresh_sessions.find_one(
        {
            "refresh_token_hash": rf_token_hash,
            "expires_at": {"$gt": utc_now()},
        }
    )
    if not user_session_doc:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = Users.from_document(users.find_one({"_id": user_session_doc["user_id"]}))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    for _ in range(3):
        new_rf_token, new_rf_token_hash = new_refresh_token()
        new_jti = create_jti()
        access_token = create_access_token(user_id=str(user.id), jti=new_jti)
        expires_at = utc_now() + dt.timedelta(days=settings.refresh_token_expire_days)
        try:
            refresh_sessions.update_one(
                {"_id": user_session_doc["_id"]},
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

        return RefreshTokenOut(
            access_token=access_token,
            refresh_token=new_rf_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    raise HTTPException(
        status_code=500, detail="Failed to refresh token, please try again."
    )


@router.post("/logout")
async def logout(rf_in: RefreshTokenIn, mongo_db: Database = Depends(get_mongo_database)):
    """
    Log out the currently authenticated user.
    """
    rf_token_hash = hash_token(rf_in.refresh_token)
    mongo_db["refresh_sessions"].delete_many({"refresh_token_hash": rf_token_hash})
    return {"detail": "Logged out successfully"}


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(current_user: Users = Depends(get_current_user)):
    """
    Get information about the currently authenticated user.
    """
    return UserInfo(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        avatar_url=current_user.avatar_url,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
    )


@router.get("/gitlab/login", response_model=GitlabAuthUrl)
async def gitlab_login(request: Request, mongo_db: Database = Depends(get_mongo_database)):
    """
    Redirect to GitLab for authentication.
    """
    redirect_uri = settings.host_url + "/api/v1/auth/gitlab/callback"
    gitlab_oauth = GitlabAuthService.from_db(mongo_db)
    state = gitlab_oauth.new_state()
    code_verifier, code_challenge = gitlab_oauth.new_pkce()

    authorization_url = gitlab_oauth.build_authorize_url(
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        scope="api",
    )

    # Save state and code_verifier in cache for later verification
    cache_service = CacheService(mongo_db)
    cache_data = json.dumps(
        {"code_verifier": code_verifier, "redirect_uri": redirect_uri}
    )
    cache_service.set(f"oauth_state:{state}", cache_data, ttl_seconds=600)

    return GitlabAuthUrl(url=authorization_url)


@router.get("/gitlab/callback")
async def gitlab_auth(code: str, state: str, mongo_db: Database = Depends(get_mongo_database)):
    """
    Handle the callback from GitLab after user authentication.
    """
    logger.info("GitLab callback received")

    if not code or not state:
        logger.error("Missing code or state in GitLab callback")
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    # Retrieve and validate state and code_verifier from cache
    cache_service = CacheService(mongo_db)
    cache_value = cache_service.get(f"oauth_state:{state}")

    if not cache_value:
        logger.error("Invalid or expired state in GitLab callback")
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    cache_data = json.loads(cache_value)
    code_verifier = cache_data["code_verifier"]
    redirect_uri = cache_data["redirect_uri"]

    # Delete the used cache entry
    cache_service.delete(f"oauth_state:{state}")

    # Exchange code for token
    gitlab_oauth = GitlabAuthService.from_db(mongo_db)
    async with httpx.AsyncClient() as client:
        token_response = await gitlab_oauth.exchange_code_for_token(
            client=client,
            redirect_uri=redirect_uri,
            code=code,
            code_verifier=code_verifier,
        )

        # Get user info from GitLab
        access_token = token_response["access_token"]
        gitlab_user = await gitlab_oauth.get_userinfo(
            client=client, access_token=access_token
        )

    users_collection = mongo_db["users"]
    user = Users.from_document(
        users_collection.find_one({"email": gitlab_user["email"]})
    )

    if not user:
        user = Users(
            id=get_next_sequence("users"),
            email=gitlab_user["email"],
            username=gitlab_user["username"],
            name=gitlab_user.get("name"),
            avatar_url=gitlab_user.get("avatar_url"),
            is_active=True,
            is_superuser=False,
        )
        users_collection.insert_one(user.to_document())

    oauth_collection = mongo_db["oauth_accounts"]
    oauth_account_doc = oauth_collection.find_one(
        {"user_id": user.id, "provider": "gitlab"}
    )
    oauth_account = OAuthAccount.from_document(oauth_account_doc)

    expires_in = token_response.get("expires_in")
    expires_at = utc_now() + dt.timedelta(seconds=expires_in) if expires_in else None
    update_doc = {
        "access_token": access_token,
        "refresh_token": token_response.get("refresh_token"),
        "token_type": token_response.get("token_type"),
        "scope": token_response.get("scope"),
        "expires_at": expires_at,
        "profile_json": gitlab_user,
        "last_refreshed_at": utc_now(),
        "provider_account_id": str(gitlab_user["id"]),
    }

    if oauth_account:
        oauth_collection.update_one(
            {"id": oauth_account.id},
            {"$set": update_doc},
        )
    else:
        oauth_account = OAuthAccount(
            id=get_next_sequence("oauth_accounts"),
            user_id=user.id,
            provider="gitlab",
            **update_doc,
        )
        oauth_collection.insert_one(oauth_account.to_document())

    # Create a session id for the user
    session_id = uuid.uuid4().hex
    cache_service = CacheService(mongo_db)
    cache_service.set(
        f"session_id:{session_id}", str(user.id), ttl_seconds=60 * 5
    )  # only 5 minutes

    # Redirect user to frontend with session id
    frontend_redirect_url = (
        f"{settings.frontend_url}/login/success?session_id={session_id}"
    )
    return RedirectResponse(url=frontend_redirect_url)


@router.get("/token/{session_id}", response_model=RefreshTokenOut)
async def get_access_token(session_id: str, mongo_db: Database = Depends(get_mongo_database)):
    """
    Fetch access and refresh tokens using session ID.
    """
    # Fetch user ID from cache using session ID
    cache_service = CacheService(mongo_db)
    user_id = cache_service.get(f"session_id:{session_id}")

    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired session ID")

    user_id = int(user_id)

    # Create refresh session for our app
    new_rf_token, new_rf_token_hash = new_refresh_token()
    new_jti = create_jti()
    new_access_token = create_access_token(user_id=str(user_id), jti=new_jti)

    refresh_session = RefreshSession(
        id=get_next_sequence("refresh_sessions"),
        user_id=user_id,
        jti=new_jti,
        refresh_token_hash=new_rf_token_hash,
        expires_at=utc_now() + dt.timedelta(days=settings.refresh_token_expire_days),
    )
    mongo_db["refresh_sessions"].insert_one(refresh_session.to_document())

    # Delete the used cache entry
    cache_service.delete(f"session_id:{session_id}")

    # Return tokens to the client
    return RefreshTokenOut(
        access_token=new_access_token,
        refresh_token=new_rf_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )
