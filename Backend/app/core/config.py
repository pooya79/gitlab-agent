from typing import Any

from pydantic import model_validator, BaseModel
from pydantic_settings import SettingsConfigDict, BaseSettings


class MongoDBSettings(BaseModel):
    """MongoDB connection settings."""

    host: str = "127.0.0.1"
    port: int = 27017
    database: str = "gitlab_agent"
    root_username: str | None = None
    root_password: str | None = None


class GitlabSettings(BaseModel):
    # All optional: the authoritative values live in the `app_settings` DB
    # collection (editable in the /admin panel). These env vars only seed the
    # DB once on first startup. See app/db/database.py:init_db.
    base: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    webhook_ssl_verify: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="_", env_nested_max_split=1)

    # --- grouped sub-settings ---
    mongodb: MongoDBSettings
    gitlab: GitlabSettings = GitlabSettings()

    # --- individual settings ---
    project_name: str = "Gitlab Agent"
    api_version: int = 1

    host: str = "http://"
    port: int = 8000
    host_url: str

    frontend_url: str = "http://localhost:3000"

    log_dir: str = "logs"

    @model_validator(mode="after")
    def _fill_host_url(self):
        if not self.host_url:
            object.__setattr__(self, "host_url", f"{self.host}:{self.port}")
        return self

    ## Security settings
    secret_key: str = "test"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    ## Admin User — seed defaults for the `make create-admin` script (not required to boot)
    admin_username: str | None = None
    admin_email: str | None = None
    admin_password: str | None = None

    ## External services
    openrouter_api_base: str = "https://openrouter.ai"
    openrouter_api_key: str | None = None
    logfire_token: str | None = None

    ## Default Agents Configs (some can be overridden in DB using /admin panel)
    max_chat_history: int = 10
    default_llm_model: str = "openai/gpt-4o-mini"
    avatar_default_name: str = "default"
    max_tokens_per_diff: int = 4000
    max_tokens_per_context: int = 20000


settings = Settings()
