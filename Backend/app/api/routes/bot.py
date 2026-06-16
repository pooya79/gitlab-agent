import uuid

from pathlib import Path
import requests
import gitlab
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pymongo.database import Database

from app.api.deps import get_current_user, get_gitlab_client, get_mongo_database
from app.core.config import settings
from app.core.log import logger
from app.db.database import get_next_sequence
from app.db.models import Bot, Configs, Users
from app.core.time import parse_iso_datetime, utc_now
from app.services.app_settings_service import get_app_settings
from app.schemas.bot import (
    BotCreate,
    BotRead,
    BotReadList,
    BotUpdate,
    BotStatusResponse,
    BotCreateResponse,
    BotUpdateResponse,
    BotDeleteResponse,
    BotStatusToggleResponse,
)

router = APIRouter(
    prefix="/bots",
    tags=["bots"],
)


def _set_bot_avatar(gitlab_base, gitlab_token: str, avatar_name: str) -> str | None:
    """Set the avatar for the bot user associated with the given GitLab token."""
    try:
        avatar_path = (
            Path(__file__).parent.parent.parent
            / "assets"
            / "avatars"
            / f"{avatar_name}.png"
        )

        gitlab_base = gitlab_base.rstrip("/")

        endpoint = f"{gitlab_base}/api/v4/user/avatar"
        headers = {"PRIVATE-TOKEN": gitlab_token}

        with open(avatar_path, "rb") as avatar_file:
            # 'avatar' is the specific form field name GitLab expects
            files = {"avatar": avatar_file}

            # Use PUT
            avatar_response = requests.put(endpoint, headers=headers, files=files)

        if avatar_response.status_code == 200:
            avatar_data = avatar_response.json()
            return avatar_data.get("avatar_url")
        else:
            # Log the text to see why GitLab rejected it
            logger.error(f"Failed to upload avatar to GitLab: {avatar_response.text}")
            return None

    except FileNotFoundError:
        logger.error(f"Avatar file not found at: {avatar_path}")
        return None
    except Exception as e:
        logger.error(f"Failed to set bot avatar: {e}")
        return None


def _get_bot(mongo_db: Database, bot_id: int) -> Bot | None:
    return Bot.from_document(mongo_db["bots"].find_one({"id": bot_id}))


def _save_bot(mongo_db: Database, bot: Bot) -> Bot:
    if bot.id is None:
        bot.id = get_next_sequence("bots")
    mongo_db["bots"].replace_one({"id": bot.id}, bot.to_document(), upsert=True)
    return bot


@router.get("/{bot_id}/status", response_model=BotStatusResponse)
async def get_bot_status(
    bot_id: int,
    mongo_db: Database = Depends(get_mongo_database),
    gitlab_client: gitlab.Gitlab = Depends(get_gitlab_client),
):
    """
    Get the status of a bot by its ID.
    """
    bot = _get_bot(mongo_db, bot_id)

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found"
        )

    if not bot.is_active:
        return BotStatusResponse(status="STOPPED")

    # Check if bot access token is valid
    if bot.gitlab_access_token_id is None:
        return BotStatusResponse(
            status="ERROR",
            error_message="Bot's GitLab access token is not set.",
        )

    try:
        project_access_token = gitlab_client.projects.get(
            bot.gitlab_project_path, lazy=True
        ).access_tokens.get(bot.gitlab_access_token_id)

        if not project_access_token:
            return BotStatusResponse(
                status="ERROR",
                error_message="Bot's GitLab project is invalid or has been revoked.",
            )

        # Check if token is revoked
        if project_access_token.revoked:
            return BotStatusResponse(
                status="ERROR",
                error_message=f"Bot's GitLab access token ({project_access_token.name}) has been revoked.",
            )

        # Check its expiry
        token_expiry = parse_iso_datetime(project_access_token.expires_at)
        if token_expiry and token_expiry < utc_now():
            return BotStatusResponse(
                status="ERROR",
                error_message=f"Bot's GitLab access token ({project_access_token.name}) has expired.",
            )

        # Check its access level
        if project_access_token.access_level < 40:  # Minimum MAINTAINER level
            return BotStatusResponse(
                status="ERROR",
                error_message=f"Bot's GitLab access token ({project_access_token.name}) does not have sufficient access level (minimum MAINTAINER).",
            )

        # Check its scope
        required_scopes = {"api"}
        token_scopes = set(project_access_token.scopes)
        if not required_scopes.issubset(token_scopes):
            return BotStatusResponse(
                status="ERROR",
                error_message=f"Bot's GitLab access token ({project_access_token.name}) does not have required scopes: {', '.join(required_scopes)}.",
            )

    except Exception as e:
        logger.error(f"Could not get bot's GitLab access token information: {e}")
        return BotStatusResponse(
            status="ERROR",
            error_message="Could not get bot's GitLab access token information (Check if gitlab is connected or access token is working, maybe create a new one).",
        )

    # Check if bot webhook is valid
    if bot.gitlab_webhook_id is None:
        return BotStatusResponse(
            status="ERROR",
            error_message="Bot's GitLab webhook is not set up.",
        )
    try:
        webhook = gitlab_client.projects.get(
            bot.gitlab_project_path, lazy=True
        ).hooks.get(bot.gitlab_webhook_id)
        if not webhook:
            return BotStatusResponse(
                status="ERROR",
                error_message="Bot's GitLab webhook is invalid or has been removed.",
            )

        # Check its URL
        if webhook.url != bot.gitlab_webhook_url:
            return BotStatusResponse(
                status="ERROR",
                error_message="Bot's GitLab webhook URL is invalid.",
            )

        # Check if required events are enabled
        required_events = {"note_events", "merge_requests_events"}
        for event in required_events:
            if not getattr(webhook, event, False):
                return BotStatusResponse(
                    status="ERROR",
                    error_message=f"Bot's GitLab webhook is missing required event: {event}.",
                )

    except Exception as e:
        logger.error(f"Could not get bot's GitLab webhook information: {e}")
        return BotStatusResponse(
            status="ERROR",
            error_message="Bot's GitLab webhook is invalid or has been removed.",
        )

    return BotStatusResponse(status="ACTIVE")


@router.post("/", response_model=BotCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_bot(
    data: BotCreate,
    mongo_db: Database = Depends(get_mongo_database),
    gitlab_client: gitlab.Gitlab = Depends(get_gitlab_client),
):
    """
    Create a new bot for a GitLab project.
    """
    project = gitlab_client.projects.get(data.gitlab_project_path)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitLab project not found or access denied",
        )

    app_settings = get_app_settings(mongo_db)

    # Create project access token for the bot
    try:
        access_token_name = f"{data.name}"
        project_token = project.access_tokens.create(
            {
                "name": access_token_name,
                "scopes": ["api"],
                "expires_at": None,
            }
        )
    except Exception as e:
        logger.error(f"Error creating project access token for bot: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project access token for the bot. Check your connection with GitLab.",
        )

    # Get username associated with the token
    try:
        access_token_gitlab_client = gitlab.Gitlab(
            app_settings.gitlab_base,
            private_token=project_token.token,
        )
        access_token_gitlab_client.auth()
        bot_user = access_token_gitlab_client.user
        if not bot_user:
            raise Exception("Could not fetch user info with the created token.")
        project_token.user_name = bot_user.username
    except Exception as e:
        # Revoke the created project token in case of failure
        try:
            project.access_tokens.delete(project_token.id)
        except Exception as revoke_error:
            logger.error(
                f"Error revoking project token after user info fetch failure: {revoke_error}"
            )

        logger.error(f"Error fetching user info for bot token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user info for the bot's access token. Check your connection with GitLab.",
        )

    # Create project webhook for the bot
    try:
        webhook_url = f"{settings.host_url}/api/v1/webhooks/{project_token.user_id}"
        webhook_secret_token = uuid.uuid4().hex
        webhook = project.hooks.create(
            {
                "url": webhook_url,
                "note_events": True,
                "merge_requests_events": True,
                "enable_ssl_verification": app_settings.gitlab_webhook_ssl_verify,
                "token": webhook_secret_token,
            }
        )
    except Exception as e:
        # Revoke the created project token in case of webhook creation failure
        try:
            project.access_tokens.delete(project_token.id)
        except Exception as revoke_error:
            logger.error(
                f"Error revoking project token after webhook creation failure: {revoke_error}"
            )

        logger.error(f"Error creating project webhook for bot: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project webhook for the bot. Check your connection with GitLab.",
        )

    # Set bot avatar URL
    warning = None
    try:
        avatar_name = settings.avatar_default_name
        avatar_url = _set_bot_avatar(
            app_settings.gitlab_base, project_token.token, avatar_name
        )
        if avatar_url is None:
            avatar_name = None
            warning = "Failed to set bot avatar."
            logger.error(f"{warning} for bot {bot_user.username}: {data.name}")
    except Exception as e:
        avatar_name = None
        avatar_url = None
        warning = f"Failed to set bot avatar: {e}"
        logger.error(warning)

    # Get default llm model configs
    llm_model = settings.default_llm_model
    configs = mongo_db["configs"].find_one({})
    if configs:
        configs_obj = Configs.from_document(configs)
        if configs_obj and llm_model not in configs_obj.available_llms:
            llm_model = settings.default_llm_model

    llm_info = configs_obj.available_llms.get(llm_model) if configs_obj else None

    if llm_info is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch default LLM model configurations.",
        )

    try:
        bot = Bot(
            id=get_next_sequence("bots"),
            name=data.name,
            gitlab_access_token_id=project_token.id,
            gitlab_access_token=project_token.token,
            gitlab_user_id=project_token.user_id,
            gitlab_user_name=project_token.user_name,
            gitlab_project_path=project.path_with_namespace,
            gitlab_webhook_id=webhook.id,
            gitlab_webhook_secret=webhook_secret_token,
            gitlab_webhook_url=webhook_url,
            llm_model=llm_info.model_name,
            llm_context_window=llm_info.context_window,
            llm_max_output_tokens=llm_info.max_output_tokens,
            llm_temperature=llm_info.temperature,
            llm_top_p=llm_info.top_p,
            llm_additional_kwargs=llm_info.additional_kwargs_schema,
            avatar_name=avatar_name,
            avatar_url=avatar_url,
        )
        _save_bot(mongo_db, bot)
    except Exception as e:
        # Clean up created GitLab resources in case of DB failure
        try:
            project.hooks.delete(webhook.id)
        except Exception as webhook_error:
            logger.error(
                f"Error deleting webhook after bot DB creation failure: {webhook_error}"
            )
        try:
            project.access_tokens.delete(project_token.id)
        except Exception as token_error:
            logger.error(
                f"Error revoking project token after bot DB creation failure: {token_error}"
            )

        logger.error(f"Error saving bot to database: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save bot to the database.",
        )
    return BotCreateResponse(
        bot=BotRead.model_validate(bot),
        warning=warning,
    )


@router.get("/", response_model=BotReadList)
async def list_bots(
    mongo_db: Database = Depends(get_mongo_database),
    page: int = 1,
    per_page: int = 20,
    current_user: Users = Depends(get_current_user),
):
    """
    List all bots with pagination.
    """
    total = mongo_db["bots"].count_documents({})
    cursor = mongo_db["bots"].find().skip((page - 1) * per_page).limit(per_page)
    docs = list(cursor)
    bots = [Bot.from_document(doc) for doc in docs if doc]

    return BotReadList(
        total=total,
        items=[BotRead.model_validate(bot) for bot in bots if bot],
    )


@router.get("/{bot_id}", response_model=BotRead)
async def get_bot(
    bot_id: int,
    mongo_db: Database = Depends(get_mongo_database),
    current_user: Users = Depends(get_current_user),
):
    """
    Get a bot by its ID.
    """
    bot = _get_bot(mongo_db, bot_id)

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found"
        )

    return BotRead.model_validate(bot)


@router.delete("/{bot_id}", response_model=BotDeleteResponse)
async def delete_bot(
    bot_id: int,
    mongo_db: Database = Depends(get_mongo_database),
    gitlab_client: str = Depends(get_gitlab_client),
):
    """
    Delete a bot by its ID.
    """
    bot = _get_bot(mongo_db, bot_id)

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found"
        )

    warning_message = ""
    # Clean up GitLab resources
    try:
        if bot.gitlab_webhook_id:
            gitlab_client.projects.get(bot.gitlab_project_path, lazy=True).hooks.delete(
                bot.gitlab_webhook_id
            )
    except Exception as e:
        logger.error(f"Error deleting webhook for bot {bot_id}: {e}")
        warning_message += f"Failed to delete GitLab webhook for bot {bot.name}."

    try:
        if bot.gitlab_access_token_id:
            gitlab_client.projects.get(
                bot.gitlab_project_path, lazy=True
            ).access_tokens.delete(bot.gitlab_access_token_id)
    except Exception as e:
        logger.error(f"Error deleting project token for bot {bot_id}: {e}")
        if warning_message:
            warning_message += "\n"
        warning_message += f"Failed to revoke GitLab project token for bot {bot.name}."

    mongo_db["bots"].delete_one({"id": bot.id})
    if not warning_message:
        return BotDeleteResponse()
    return BotDeleteResponse(warning=warning_message)


@router.patch("/{bot_id}/new-access-token", response_model=BotUpdateResponse)
async def create_new_bot_access_token(
    bot_id: int,
    mongo_db: Database = Depends(get_mongo_database),
    gitlab_client: str = Depends(get_gitlab_client),
):
    """
    Create a new access token for a bot by its ID and revoke the old one.
    """
    bot = _get_bot(mongo_db, bot_id)

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found"
        )
    old_token_id = bot.gitlab_access_token_id

    # Create new project access token
    try:
        project_token = gitlab_client.projects.get(
            bot.gitlab_project_path, lazy=True
        ).access_tokens.create(
            {
                "name": bot.name,
                "scopes": ["api"],
                "expires_at": None,
            }
        )
    except Exception as e:
        logger.error(f"Error creating project token for bot {bot_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project token for the bot. Check your connection with GitLab.",
        )

    # Fetch username associated with the new token
    try:
        gitlab_client.auth()
        user_info = gitlab_client.user
        if not user_info:
            raise Exception("Could not fetch user info with the created token.")
        project_token.user_name = user_info.username
    except Exception as e:
        # Revoke the created project token in case of failure
        try:
            gitlab_client.projects.get(
                bot.gitlab_project_path, lazy=True
            ).access_tokens.delete(project_token.id)
        except Exception as revoke_error:
            logger.error(
                f"Error revoking project token after user info fetch failure: {revoke_error}"
            )

        logger.error(f"Error fetching user info for new bot token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user info for the new bot's access token. Check your connection with GitLab.",
        )

    # Revoke old token and update bot with new token info
    try:
        old_token = gitlab_client.projects.get(
            bot.gitlab_project_path, lazy=True
        ).access_tokens.get(old_token_id)
        if old_token_id and old_token and old_token.revoked is False:
            gitlab_client.projects.get(
                bot.gitlab_project_path, lazy=True
            ).access_tokens.delete(old_token_id)
        bot.gitlab_access_token_id = project_token.id
        bot.gitlab_access_token = project_token.token
        bot.gitlab_user_id = project_token.user_id
        bot.gitlab_user_name = project_token.user_name
        _save_bot(mongo_db, bot)
    except Exception as e:
        logger.error(f"Error updating bot with new token for bot {bot_id}: {e}")
        # Revoke the created project token in case of DB update failure
        try:
            gitlab_client.projects.get(
                bot.gitlab_project_path, lazy=True
            ).access_tokens.delete(project_token.id)
        except Exception as revoke_error:
            logger.error(
                f"Error revoking project token after bot DB update failure: {revoke_error}"
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update bot with new access token.",
        )

    return BotUpdateResponse(bot=BotRead.model_validate(bot))


@router.patch("/{bot_id}", response_model=BotUpdateResponse)
async def update_bot(
    bot_id: int,
    data: BotUpdate,
    mongo_db: Database = Depends(get_mongo_database),
    current_user: Users = Depends(get_current_user),
):
    """
    Update a bot by its ID.
    """
    bot = _get_bot(mongo_db, bot_id)

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found"
        )

    # If avatar_name is provided, update the avatar
    warning = None
    if data.avatar_name is not None:
        avatar_url = _set_bot_avatar(
            get_app_settings(mongo_db).gitlab_base,
            bot.gitlab_access_token,
            data.avatar_name,
        )
        if avatar_url:
            bot.avatar_name = data.avatar_name
            bot.avatar_url = avatar_url
        else:
            data.avatar_name = None
            logger.error(
                f"Failed to update avatar for bot {bot.id} with name {bot.name}"
            )
            warning = "Failed to update bot avatar."

    # If llm_model is provided, validate it
    if data.llm_model is not None:
        configs = mongo_db["configs"].find_one({})
        if configs:
            configs_obj = Configs.from_document(configs)
            if configs_obj:
                llm_info = configs_obj.available_llms.get(data.llm_model)
                if llm_info:
                    bot.llm_model = llm_info.model_name
                    bot.llm_context_window = llm_info.context_window
                    bot.llm_max_output_tokens = llm_info.max_output_tokens
                    bot.llm_temperature = llm_info.temperature
                    bot.llm_top_p = llm_info.top_p
                    bot.llm_additional_kwargs = llm_info.additional_kwargs_schema
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid LLM model specified.",
                    )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not fetch available LLM models from configurations.",
            )

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key not in {"avatar_name", "llm_model"}:
            setattr(bot, key, value)

    _save_bot(mongo_db, bot)
    return BotUpdateResponse(bot=BotRead.model_validate(bot), warning=warning)


@router.patch("/{bot_id}/toggle-active", response_model=BotStatusToggleResponse)
async def toggle_bot_active(
    bot_id: int,
    mongo_db: Database = Depends(get_mongo_database),
    current_user: Users = Depends(get_current_user),
):
    """
    Toggle a bot's active status by its ID.
    """
    bot = _get_bot(mongo_db, bot_id)

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found"
        )

    bot.is_active = not bot.is_active
    _save_bot(mongo_db, bot)
    return BotStatusToggleResponse(is_active=bot.is_active)


@router.delete("/{bot_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_bot_token(
    bot_id: int,
    mongo_db: Database = Depends(get_mongo_database),
    gitlab_client: gitlab.Gitlab = Depends(get_gitlab_client),
):
    """
    Revoke a bot's GitLab project access token.
    """
    bot = _get_bot(mongo_db, bot_id)

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found"
        )

    try:
        if bot.gitlab_access_token_id:
            gitlab_client.projects.get(
                bot.gitlab_project_path, lazy=True
            ).access_tokens.delete(bot.gitlab_access_token_id)
            bot.gitlab_access_token_id = None
            bot.gitlab_access_token = None
            _save_bot(mongo_db, bot)
    except Exception as e:
        logger.error(f"Error revoking project token for bot {bot_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke GitLab project token for the bot.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{bot_id}/rotate-token", response_model=BotRead)
async def rotate_bot_token(
    bot_id: int,
    mongo_db: Database = Depends(get_mongo_database),
    gitlab_client: gitlab.Gitlab = Depends(get_gitlab_client),
):
    """
    Rotate a bot's GitLab project access token.
    """
    bot = _get_bot(mongo_db, bot_id)

    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found"
        )

    try:
        if bot.gitlab_access_token_id:
            new_token = gitlab_client.projects.get(
                bot.gitlab_project_path, lazy=True
            ).access_tokens.rotate(bot.gitlab_access_token_id)
            bot.gitlab_access_token_id = new_token.id
            bot.gitlab_access_token = new_token.token
            _save_bot(mongo_db, bot)
            return BotRead.model_validate(bot)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bot does not have an existing GitLab access token to rotate.",
            )
    except Exception as e:
        logger.error(f"Error rotating project token for bot {bot_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to rotate GitLab project token for the bot.",
        )
