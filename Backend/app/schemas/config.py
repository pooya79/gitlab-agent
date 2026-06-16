from typing import Any
from pydantic import BaseModel, Field


class LLMModelInfo(BaseModel):
    model_name: str
    context_window: int
    max_output_tokens: int
    temperature: float
    top_p: float = 0.95
    # Per 1M tokens.
    input_token_cost: float = 0.0
    output_token_cost: float = 0.0
    additional_kwargs_schema: dict[str, Any] = Field(default_factory=dict)

class Configs(BaseModel):
    max_chat_history: int
    max_tokens_per_diff: int
    max_tokens_per_context: int

    default_llm_model: str
    avatar_default_name: str

    available_llms: dict[str, LLMModelInfo] = Field(default_factory=dict)

class ConfigsUpdate(BaseModel):
    max_chat_history: int | None = None
    max_tokens_per_diff: int | None = None
    max_tokens_per_context: int | None = None

    default_llm_model: str | None = None
    avatar_default_name: str | None = None