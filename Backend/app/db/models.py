"""Lightweight data models used by the MongoDB layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime as dt
from typing import Any, Literal, Mapping, Type, TypeVar
from bson import ObjectId

from app.prompts.smart_agent import SMART_AGENT_SYSTEM_PROMPT
from app.core.config import settings

T = TypeVar("T", bound="MongoModel")


@dataclass
class MongoModel:
    """Base class for MongoDB models with both _id (ObjectId) and numeric id."""

    _id: ObjectId | None = None  # MongoDB primary key
    id: int | None = None  # Your readable numeric ID

    def to_document(self) -> dict[str, Any]:
        data = asdict(self)

        mongo_id = data.pop("_id", None)
        if mongo_id is None:
            data["_id"] = ObjectId()
        else:
            data["_id"] = mongo_id

        return data

    @classmethod
    def from_document(cls: Type[T], doc: Mapping[str, Any] | None) -> T | None:
        if doc is None:
            return None

        data = dict(doc)

        if "_id" in data:
            data["_id"] = data["_id"]  # keep ObjectId
        return cls(**data)


@dataclass
class LLMModelInfo(MongoModel):
    model_name: str = ""
    context_window: int = 0
    max_output_tokens: int = 0
    temperature: float = 0.2
    top_p: float = 0.95
    # Costs are per 1M tokens, in whatever currency the operator tracks (USD by convention).
    input_token_cost: float = 0.0
    output_token_cost: float = 0.0
    additional_kwargs_schema: dict[str, Any] = field(default_factory=dict)


from app.core.llm_configs import llm_model_infos  # noqa: E402


@dataclass
class Configs(MongoModel):
    max_chat_history: int = settings.max_chat_history
    max_tokens_per_diff: int = settings.max_tokens_per_diff
    max_tokens_per_context: int = settings.max_tokens_per_context

    default_llm_model: str = settings.default_llm_model
    avatar_default_name: str = settings.avatar_default_name

    available_llms: dict[str, LLMModelInfo] = field(
        default_factory=lambda: {info.model_name: info for info in llm_model_infos}
    )

    @classmethod
    def from_document(cls, doc):
        if doc is None:
            return None

        data = dict(doc)

        # Convert nested model entries
        raw_llms = data.get("available_llms", {})
        fixed_llms = {
            name: LLMModelInfo.from_document(llm_dict)
            for name, llm_dict in raw_llms.items()
        }
        data["available_llms"] = fixed_llms

        return cls(**data)


@dataclass
class Bot(MongoModel):
    name: str = ""
    is_active: bool = True
    gitlab_project_path: str = ""
    gitlab_access_token_id: int | None = None
    gitlab_access_token: str | None = None
    gitlab_user_id: int | None = None
    gitlab_user_name: str | None = None
    gitlab_webhook_id: int | None = None
    gitlab_webhook_secret: str | None = None
    gitlab_webhook_url: str | None = None
    avatar_name: str | None = None
    avatar_url: str | None = None
    llm_model: str = ""
    llm_context_window: int = 0
    llm_max_output_tokens: int = 0
    llm_temperature: float = 0.0
    llm_top_p: float = 0.95
    llm_additional_kwargs: dict[str, Any] = field(default_factory=dict)
    llm_system_prompt: str = SMART_AGENT_SYSTEM_PROMPT


@dataclass
class MrAgentHistory(MongoModel):
    botname: str = ""
    mr_id: int = 0
    mr_title: str = ""
    mr_web_url: str = ""
    project_id: int = 0
    project_path_with_namespace: str = ""
    project_web_url: str = ""
    messages_json_str: str = ""
    request_type: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    status: Literal["pending", "completed", "failed"] = "pending"
    error_message: str | None = None
    updated_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc)
    )


@dataclass
class OAuthAccount(MongoModel):
    user_id: int | None = None
    provider: str = ""
    provider_account_id: str = ""
    access_token: str = ""
    refresh_token: str | None = None
    token_type: str | None = None
    scope: str | None = None
    expires_at: dt.datetime | None = None
    profile_json: dict[str, Any] | None = None
    last_refreshed_at: dt.datetime | None = None


@dataclass
class RefreshSession(MongoModel):
    user_id: int | None = None
    jti: str = ""
    refresh_token_hash: str = ""
    expires_at: dt.datetime | None = None


@dataclass
class Users(MongoModel):
    email: str = ""
    username: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    is_active: bool = True
    is_superuser: bool = False
    password_hash: str | None = None


@dataclass
class AppSettings(MongoModel):
    """Singleton document holding runtime-editable app-wide settings.

    Unlike `Configs`, this collection is seeded once and never reset on startup,
    so values changed via the /admin panel persist across restarts.
    """

    gitlab_base: str | None = None
    gitlab_client_id: str | None = None
    gitlab_client_secret: str | None = None
    gitlab_webhook_ssl_verify: bool = True


@dataclass
class CacheEntry:
    key: str
    value: str
    expires_at: dt.datetime | None = None

    def to_document(self) -> dict[str, Any]:
        doc = {
            "_id": self.key,
            "key": self.key,
            "value": self.value,
        }
        if self.expires_at:
            doc["expires_at"] = self.expires_at
        return doc
