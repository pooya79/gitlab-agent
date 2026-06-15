from fastapi import APIRouter

from app.api.routes import admin, auth, gitlab, bot, config, webhooks
from app.core.config import settings

api_router = APIRouter(prefix=f"/api/v{settings.api_version}")
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(gitlab.router)
api_router.include_router(bot.router)
api_router.include_router(config.router)
api_router.include_router(webhooks.router)
