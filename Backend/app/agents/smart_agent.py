import gitlab
import datetime as dt
from pydantic_ai import (
    Agent,
    UsageLimits,
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    AgentRunResult,
    ModelMessagesTypeAdapter,
)
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pymongo.database import Database
from bson import ObjectId

from app.agents.utils import token_counter
from app.core.config import settings
from app.core.log import logger
from app.db.models import Bot, MrAgentHistory
from app.prompts.smart_agent import SMART_AGENT_SYSTEM_PROMPT, SMART_AGENT_USER_PROMPT


# Tools
def tools_wrapper(
    gitlab_client: gitlab.Gitlab, mr_iid: int, project_id: int, source_branch: str
) -> list[callable]:
    """Return the list of tools available to the Smart Agent."""

    def approve_mr() -> str:
        """Tool to approve a GitLab Merge Request. Use this tool only one time per conversation. If you have already approved the merge request you might get an error (permission error)."""
        try:
            project = gitlab_client.projects.get(project_id, lazy=True)
            mr = project.mergerequests.get(mr_iid)
            mr.approve()
            return "Approved the merge request."
        except gitlab.GitlabError as e:
            logger.error(
                f"Failed to approve merge request {mr_iid} in project {project_id}, Error: {str(e)}"
            )
            return f"Failed to approve the merge request: {str(e)}"

    def unapprove_mr() -> str:
        """Tool to unapprove a GitLab Merge Request. You might get error if you have not approved it yet. Use this tool only one time per conversation."""
        try:
            project = gitlab_client.projects.get(project_id, lazy=True)
            mr = project.mergerequests.get(mr_iid)
            mr.unapprove()
            return "Unapproved the merge request."
        except gitlab.GitlabError as e:
            logger.error(
                f"Failed to unapprove merge request {mr_iid} in project {project_id}, Error: {str(e)}"
            )
            return f"Failed to unapprove the merge request: {str(e)}"

    def get_file(file_path: str) -> str:
        """Tool to get the content of a file in the GitLab repository. given its path. you can use this tool only 2 times per conversation."""
        project = gitlab_client.projects.get(project_id, lazy=True)
        try:
            file = project.files.get(file_path=file_path, ref=source_branch)
            file_content = file.decode().decode("utf-8")
            if token_counter(file_content) > settings.max_tokens_per_file:
                return f"Error: The file {file_path} is too large to retrieve."
            return file_content
        except gitlab.GitlabError as e:
            logger.error(
                f"Failed to retrieve file {file_path} from project {project_id} at branch {source_branch}, Error: {str(e)}"
            )
            return "Error: " + str(e)

    return [approve_mr, unapprove_mr, get_file]


class SmartAgent:
    def __init__(
        self,
        openrouter_api_key: str,
        gitlab_client: gitlab.Gitlab,
        mongo_db: Database,
        bot: Bot,
    ):
        temperature = bot.llm_temperature
        max_tokens = bot.llm_max_output_tokens
        top_p = bot.llm_top_p
        model_name = bot.llm_model
        extra_body = (
            bot.llm_additional_kwargs.copy() if bot.llm_additional_kwargs else {}
        )

        # Get usage every time
        extra_body["usage"] = {"include": True}

        # Model settings
        self.model_settings = OpenAIChatModelSettings(
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            extra_body=extra_body,
        )
        self.model = OpenAIChatModel(
            model_name=model_name,
            settings=self.model_settings,
            provider=OpenRouterProvider(api_key=openrouter_api_key),
        )
        self.gitlab_client = gitlab_client
        self.mongo_db = mongo_db
        self.bot = bot

    def gather_context(self, mr: "gitlab.v4.objects.ProjectMergeRequest") -> str:
        """Gather context for the merge request including diffs, title, and description."""
        # Fetch MR details from GitLab
        mr_diffs = mr.diffs.get(mr.diffs.list(page=1, per_page=1)[0].id).diffs

        # Build context string
        context_lines: list[str] = []
        context_lines.append(f"Merge Request Title: {mr.title}")
        context_lines.append(f"Merge Request Description: {mr.description}")
        context_lines.append("")

        ignored_files = []
        for diff in mr_diffs:
            # Skip diffs that are too large (token-based)
            if token_counter(diff.get("diff", "")) > settings.max_tokens_per_diff:
                ignored_files.append(
                    diff.get("new_path", "") or diff.get("old_path", "unknown")
                )
                continue

            # Determine status
            if diff.get("new_file"):
                status = "added"
            elif diff.get("deleted_file"):
                status = "deleted"
            elif diff.get("renamed_file"):
                status = "renamed"
            elif diff.get("generated_file"):
                status = "generated"
            else:
                status = "modified"

            # Determine diff availability
            can_review = (
                not getattr(diff, "too_large", False)
                and not getattr(diff, "collapsed", False)
                and bool(diff.get("diff", "").strip())
            )
            diff_text = diff.get("diff", "").strip() if can_review else None

            # Append file block
            context_lines.append("### File")
            context_lines.append(f"old_path: {diff.get('old_path')}")
            context_lines.append(f"new_path: {diff.get('new_path')}")
            context_lines.append(f"status: {status}")
            context_lines.append(f"can_review_diff: {str(can_review).lower()}")
            context_lines.append("")

            if can_review:
                context_lines.append("Diff:")
                context_lines.append(diff_text)
            else:
                context_lines.append("Diff unavailable")

            context_lines.append("")

        # Summary of skipped files
        if ignored_files:
            context_lines.append(
                f"Note: The following files were skipped due to size constraints: {', '.join(ignored_files)}"
            )

        return "\n".join(context_lines)

    async def run(
        self,
        mr_iid: int,
        project_id: int,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        message_history: list[ModelMessage] | None = None,
    ) -> AgentRunResult[str]:
        """Run the agent with a user prompt and optional message history. Posts the response as a comment on the MR.

        Args:
            user_prompt: The user's prompt/question
            message_history: Optional list of previous messages for context
        """
        if not user_prompt:
            user_prompt = SMART_AGENT_USER_PROMPT

        if system_prompt is None:
            system_prompt = self.bot.llm_system_prompt or SMART_AGENT_SYSTEM_PROMPT

        request_type = "note_reply" if message_history is not None else "mr_review"
        history_id: ObjectId | None = None
        project = None
        mr = None

        try:
            logger.info(
                f"Starting Smart Agent run for MR {mr_iid} in project {project_id}"
            )

            # Fetch MR details
            project = self.gitlab_client.projects.get(project_id)
            mr = project.mergerequests.get(mr_iid)

            # Initialize the history once MR and project data are available
            history_id = self._start_history(
                mr=mr,
                project=project,
                request_type=request_type,
            )

            # Gather context
            context = self.gather_context(mr=mr)

            # Append context to system prompt
            system_prompt = f"{system_prompt}\n\n### Merge Request Context:\n{context}"

            # Initialize the agent
            self.agent = Agent(
                model=self.model,
                tools=tools_wrapper(
                    gitlab_client=self.gitlab_client,
                    mr_iid=mr_iid,
                    project_id=project_id,
                    source_branch=mr.source_branch,
                ),
                system_prompt=system_prompt,
            )

            # Add system prompt as the first message of the history if history is provided
            if message_history is not None:
                message_history.insert(
                    0, ModelRequest(parts=[SystemPromptPart(content=system_prompt)])
                )

            # Run the agent
            response = await self.agent.run(
                user_prompt=user_prompt,
                message_history=message_history or [],
                usage_limits=UsageLimits(tool_calls_limit=3),
            )
        except Exception as e:
            logger.exception(
                f"Smart Agent run failed for MR {mr_iid} in project {project_id}"
            )
            # Update history with failure
            if history_id:
                self._update_history(
                    document_id=history_id,
                    status="failed",
                    error_message=str(e),
                )
            raise e

        # Gather info to save in history (It is okay if this process fails, we don't want to block the main flow)
        try:
            usage = response.usage() or {}
            input_tokens = usage.input_tokens or 0
            output_tokens = usage.output_tokens or 0
            cache_read_tokens = usage.cache_read_tokens or 0
            cache_write_tokens = usage.cache_write_tokens or 0
            messages_json_str = response.all_messages_json().decode("utf-8")
            if history_id:
                self._update_history(
                    document_id=history_id,
                    mr_title=mr.title if mr else None,
                    mr_web_url=mr.web_url if mr else None,
                    project_path_with_namespace=project.path_with_namespace
                    if project
                    else None,
                    project_web_url=project.web_url if project else None,
                    messages_json_str=messages_json_str,
                    request_type=request_type,
                    input_tokens=input_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    output_tokens=output_tokens,
                    status="completed",
                    error_message=None,
                )
            else:
                logger.error("History ID is missing; skipping history update.")
        except Exception as e:
            logger.error(f"Failed to update agent run history: {str(e)}")

        # Return the response
        return response.output

    def _start_history(
        self,
        mr: "gitlab.v4.objects.ProjectMergeRequest",
        project: "gitlab.v4.objects.Project",
        request_type: str,
    ) -> ObjectId:
        """Start a new history record for the agent run. Return the record id to chain further updates."""
        history_collection = self.mongo_db["mr_agent_history"]
        history_record = MrAgentHistory(
            botname=self.bot.name,
            mr_id=mr.iid,
            mr_title=mr.title,
            mr_web_url=mr.web_url,
            project_id=project.id,
            project_path_with_namespace=project.path_with_namespace,
            project_web_url=project.web_url,
            messages_json_str="",
            request_type=request_type,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            status="pending",
            error_message=None,
            updated_at=dt.datetime.now(dt.timezone.utc),
        )
        inserted_record = history_collection.insert_one(history_record.to_document())
        return inserted_record.inserted_id

    def _update_history(
        self,
        document_id: ObjectId,
        mr_title: str | None = None,
        mr_web_url: str | None = None,
        project_path_with_namespace: str | None = None,
        project_web_url: str | None = None,
        messages_json_str: str | None = None,
        request_type: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        status: str | None = None,
        error_message: str | None = None,
    ):
        """Update the existing history record fields given the document id."""
        if document_id is None:
            logger.error("Cannot update history without a document id.")
            return
        history_collection = self.mongo_db["mr_agent_history"]

        update_fields: dict[str, object] = {
            "updated_at": dt.datetime.now(dt.timezone.utc),
        }

        if mr_title is not None:
            update_fields["mr_title"] = mr_title
        if mr_web_url is not None:
            update_fields["mr_web_url"] = mr_web_url
        if project_path_with_namespace is not None:
            update_fields["project_path_with_namespace"] = project_path_with_namespace
        if project_web_url is not None:
            update_fields["project_web_url"] = project_web_url
        if messages_json_str is not None:
            update_fields["messages_json_str"] = messages_json_str
        if request_type is not None:
            update_fields["request_type"] = request_type
        if input_tokens is not None:
            update_fields["input_tokens"] = input_tokens
        if output_tokens is not None:
            update_fields["output_tokens"] = output_tokens
        if cache_read_tokens is not None:
            update_fields["cache_read_tokens"] = cache_read_tokens
        if cache_write_tokens is not None:
            update_fields["cache_write_tokens"] = cache_write_tokens
        if status is not None:
            update_fields["status"] = status
        # allow clearing/setting error message explicitly
        if error_message is not None or status is not None:
            update_fields["error_message"] = error_message

        history_collection.update_one(
            {"_id": document_id},
            {"$set": update_fields},
        )

    @staticmethod
    def get_history(
        project_id: int,
        mr_iid: int | None,
        mongo_db: Database,
        page: int = 1,
        limit: int = 10,
    ) -> list[MrAgentHistory]:
        """Retrieve agent run history for a given project and optional MR."""
        history_collection = mongo_db["mr_agent_history"]
        query: dict[str, object] = {"project_id": project_id}
        if mr_iid is not None:
            query["mr_id"] = mr_iid

        history_docs = (
            history_collection.find(query)
            .sort("updated_at", -1)
            .skip((page - 1) * limit)
            .limit(limit)
        )

        histories = [
            MrAgentHistory.from_document(doc) for doc in history_docs if doc is not None
        ]
        return histories

    @staticmethod
    def get_messages_adapter(messages_json_str: str) -> list[ModelMessage]:
        """Get list of ModelMessage from stored JSON string."""
        return ModelMessagesTypeAdapter.validate_json(messages_json_str)
