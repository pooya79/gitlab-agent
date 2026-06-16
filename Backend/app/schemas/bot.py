from typing import Optional, List, Any, Dict, Literal
from pydantic import BaseModel


# ---- Create ----
class BotCreate(BaseModel):
    name: str
    gitlab_project_path: str


# ---- Read ----
class BotRead(BaseModel):
    id: int
    is_active: bool
    gitlab_project_path: str
    gitlab_access_token_id: Optional[int] = None
    gitlab_user_id: Optional[int] = None
    gitlab_user_name: Optional[str] = None
    gitlab_webhook_id: Optional[int] = None
    gitlab_webhook_secret: Optional[str] = None
    avatar_name: Optional[str] = None
    avatar_url: Optional[str] = None
    llm_model: str
    llm_max_output_tokens: int
    llm_temperature: float
    llm_top_p: float = 0.95
    llm_system_prompt: Optional[str] = None
    llm_additional_kwargs: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


# ---- Create (response) ----
class BotCreateResponse(BaseModel):
    bot: BotRead
    warning: Optional[str] = None


# ---- Update (can change everything it can) ----
class BotUpdate(BaseModel):
    is_active: Optional[bool] = None
    avatar_name: Optional[str] = None
    llm_model: Optional[str] = None
    llm_system_prompt: Optional[str] = None


# ---- Update (response) ----
class BotUpdateResponse(BaseModel):
    bot: BotRead
    warning: Optional[str] = None


# ---- List wrapper ----
class BotReadList(BaseModel):
    total: int
    items: List[BotRead]


class BotStatusResponse(BaseModel):
    status: Literal["ACTIVE", "STOPPED", "ERROR"]
    error_message: Optional[str] = None


class BotDeleteResponse(BaseModel):
    warning: Optional[str] = None


class BotStatusToggleResponse(BaseModel):
    is_active: bool
