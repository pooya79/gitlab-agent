from fastapi import APIRouter, Depends, HTTPException, Response, status
from pymongo.database import Database

from app.api.deps import get_current_user
from app.db.database import get_mongo_database
from app.db.models import (
    Configs as ConfigsModel,
    LLMModelInfo as LLMModelInfoModel,
    Users,
)
from app.schemas.config import (
    LLMModelInfo as LLMModelInfoSchema,
    ConfigsUpdate,
    Configs as ConfigsSchema,
)
from app.core.config import settings

router = APIRouter(
    prefix="/config",
    tags=["config"],
)

AVAILABLE_BOT_AVATARS: dict[str, str] = {
    "8-bit_bot": f"{settings.host_url}/api/static/avatars/8-bit_bot.png",
    "analyst": f"{settings.host_url}/api/static/avatars/analyst.png",
    "cyber_samurai": f"{settings.host_url}/api/static/avatars/cyber_samurai.png",
    "default": f"{settings.host_url}/api/static/avatars/default.png",
    "galactic_bot": f"{settings.host_url}/api/static/avatars/galactic_bot.png",
    "hacker": f"{settings.host_url}/api/static/avatars/hacker.png",
    "khosro": f"{settings.host_url}/api/static/avatars/khosro.png",
    "librarian": f"{settings.host_url}/api/static/avatars/librarian.png",
    "steampunk": f"{settings.host_url}/api/static/avatars/steampunk.png",
}


@router.get("/available-avatars", response_model=dict[str, str])
async def get_available_avatars():
    """
    Get a list of available bot avatars.
    """
    return AVAILABLE_BOT_AVATARS


@router.get("/available-llms", response_model=dict[str, LLMModelInfoSchema])
async def get_available_llms(mongo_db: Database = Depends(get_mongo_database)):
    """
    Get a list of available LLM models.
    """
    configs_collection = mongo_db["configs"]
    configs_doc = configs_collection.find_one({})
    available_llms: dict[str, LLMModelInfoSchema] = {}
    if configs_doc:
        configs_obj = ConfigsModel.from_document(configs_doc)
        if configs_obj:
            for model_name, llm_info in configs_obj.available_llms.items():
                available_llms[model_name] = LLMModelInfoSchema(
                    model_name=llm_info.model_name,
                    context_window=llm_info.context_window,
                    max_output_tokens=llm_info.max_output_tokens,
                    temperature=llm_info.temperature,
                    additional_kwargs_schema=llm_info.additional_kwargs_schema,
                )
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch available LLM model configurations.",
        )
    return available_llms


@router.post("/available-llms", response_model=LLMModelInfoSchema)
def add_update_available_llm(
    llm_info: LLMModelInfoSchema,
    mongo_db: Database = Depends(get_mongo_database),
    current_user: Users = Depends(get_current_user),
):
    """
    Add a new LLM model configuration to the available models. Or update an existing one.
    """
    configs_collection = mongo_db["configs"]
    configs_doc = configs_collection.find_one({})
    if not configs_doc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch available LLM model configurations.",
        )

    configs_obj = ConfigsModel.from_document(configs_doc)
    if not configs_obj:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not parse existing LLM model configurations.",
        )

    configs_obj.available_llms[llm_info.model_name] = llm_info

    configs_collection.update_one(
        {"_id": configs_obj._id},
        {
            "$set": {
                "available_llms": {
                    model_name: info.to_document()
                    for model_name, info in configs_obj.available_llms.items()
                }
            }
        },
    )

    return llm_info


@router.delete("/available-llms/{model_name}")
def delete_available_llm(
    model_name: str,
    mongo_db: Database = Depends(get_mongo_database),
    current_user: Users = Depends(get_current_user),
):
    """
    Delete an LLM model configuration from the available models.
    """
    configs_collection = mongo_db["configs"]
    configs_doc = configs_collection.find_one({})
    if not configs_doc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch available LLM model configurations.",
        )

    configs_obj = ConfigsModel.from_document(configs_doc)
    if not configs_obj:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not parse existing LLM model configurations.",
        )

    if model_name not in configs_obj.available_llms:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM model '{model_name}' not found in available models.",
        )

    del configs_obj.available_llms[model_name]

    configs_collection.update_one(
        {"_id": configs_obj._id},
        {
            "$set": {
                "available_llms": {
                    model_name: info.to_document()
                    for model_name, info in configs_obj.available_llms.items()
                }
            }
        },
    )

    # Return no content response
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/", response_model=ConfigsSchema)
def get_configs(mongo_db: Database = Depends(get_mongo_database)):
    """
    Get the current configuration settings.
    """
    configs_collection = mongo_db["configs"]
    configs_doc = configs_collection.find_one({})
    if not configs_doc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch configuration settings.",
        )

    configs_obj = ConfigsModel.from_document(configs_doc)
    if not configs_obj:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not parse configuration settings.",
        )

    return ConfigsSchema(
        max_chat_history=configs_obj.max_chat_history,
        max_tokens_per_diff=configs_obj.max_tokens_per_diff,
        max_tokens_per_context=configs_obj.max_tokens_per_context,
        default_llm_model=configs_obj.default_llm_model,
        avatar_default_name=configs_obj.avatar_default_name,
        available_llms={
            model_name: LLMModelInfoSchema(
                model_name=llm_info.model_name,
                context_window=llm_info.context_window,
                max_output_tokens=llm_info.max_output_tokens,
                temperature=llm_info.temperature,
                additional_kwargs_schema=llm_info.additional_kwargs_schema,
            )
            for model_name, llm_info in configs_obj.available_llms.items()
        },
    )


@router.patch("/", response_model=ConfigsSchema)
def update_configs(
    updated_configs: ConfigsUpdate,
    mongo_db: Database = Depends(get_mongo_database),
    current_user: Users = Depends(get_current_user),
):
    """
    Update the configuration settings.
    """
    configs_collection = mongo_db["configs"]
    configs_doc = configs_collection.find_one({})
    if not configs_doc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch configuration settings.",
        )

    configs_obj = ConfigsModel.from_document(configs_doc)
    if not configs_obj:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not parse configuration settings.",
        )

    # Update fields
    update_configs_dict = updated_configs.model_dump(exclude_unset=True)
    for key, value in update_configs_dict.items():
        setattr(configs_obj, key, value)
    configs_collection.update_one(
        {"_id": configs_obj._id},
        {
            "$set": {
                "max_chat_history": configs_obj.max_chat_history,
                "max_tokens_per_diff": configs_obj.max_tokens_per_diff,
                "max_tokens_per_context": configs_obj.max_tokens_per_context,
                "default_llm_model": configs_obj.default_llm_model,
                "avatar_default_name": configs_obj.avatar_default_name,
            }
        },
    )

    return updated_configs
