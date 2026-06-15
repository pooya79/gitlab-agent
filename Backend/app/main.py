import os
from fastapi.responses import JSONResponse
import logfire
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.log import logger  # noqa: F401
from app.schemas import GeneralErrorResponses
from app.core.config import settings
from app.db.database import init_db, close_client
from app.api.main import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure indexes exist
    init_db()
    yield

    # Shutdown: close the Mongo client
    close_client()


app = FastAPI(
    title=settings.project_name,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Setup logfire for monitoring (optional — only when a token is provided)
if settings.logfire_token:
    try:
        logfire.configure(token=settings.logfire_token)
        logfire.instrument_pydantic_ai()
        logfire.instrument_fastapi(app, capture_headers=True)
    except Exception as exc:  # pragma: no cover - defensive, monitoring is optional
        logger.warning(f"Logfire configuration failed; monitoring disabled: {exc}")
else:
    # Don't let logfire/OpenTelemetry attempt to export anything without a token.
    logger.warning("LOGFIRE_TOKEN not set; Logfire monitoring is disabled.")
    logfire.configure(send_to_logfire=False)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
AVATARS_DIR = ASSETS_DIR / "avatars"
AVATARS_URL_PREFIX = "/api/static/avatars"

app.mount(AVATARS_URL_PREFIX, StaticFiles(directory=str(AVATARS_DIR)), name="avatars")

origins = [
    "http://localhost:3000",
    settings.frontend_url,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
        )


app.include_router(
    api_router,
    responses={
        400: GeneralErrorResponses.BAD_REQUEST,
        401: GeneralErrorResponses.UNAUTHORIZED,
        403: GeneralErrorResponses.FORBIDDEN,
        404: GeneralErrorResponses.NOT_FOUND,
        500: GeneralErrorResponses.INTERNAL_SERVER_ERROR,
        502: GeneralErrorResponses.BAD_GATEWAY,
    },
)
