from typing import Optional

from pydantic import BaseModel


class AdminLoginIn(BaseModel):
    username: str
    password: str


class AdminTokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class AdminInfo(BaseModel):
    id: int
    email: str
    username: Optional[str]
    is_superuser: bool


class GitlabSettingsOut(BaseModel):
    gitlab_base: Optional[str]
    gitlab_client_id: Optional[str]
    # The secret value is never returned; this flag reports whether one is stored.
    gitlab_client_secret_set: bool
    gitlab_webhook_ssl_verify: bool


class GitlabSettingsUpdate(BaseModel):
    gitlab_base: Optional[str] = None
    gitlab_client_id: Optional[str] = None
    # Leave blank/omit to keep the existing secret.
    gitlab_client_secret: Optional[str] = None
    gitlab_webhook_ssl_verify: Optional[bool] = None
