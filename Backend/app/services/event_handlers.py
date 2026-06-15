from typing import Any, Dict

import gitlab
from pydantic_ai import (
    ModelRequest,
    ModelResponse,
    UserPromptPart,
    TextPart,
)
from pymongo.database import Database

from app.agents.smart_agent import SmartAgent
from app.core.config import settings
from app.core.log import logger
from app.db.models import Bot
from app.agents.command_agent import CommandAgent
from app.services.app_settings_service import get_app_settings


async def handle_merge_request_event(
    bot: Bot, payload: Dict[str, Any], mongo_db: Database
) -> None:
    """
    Handle a merge request event from GitLab.

    :param bot: The Bot instance associated with this webhook.
    :param payload: The JSON payload sent by GitLab.
    """
    logger.info(
        f"Handling merge request event for bot {bot.id} (project {bot.gitlab_project_path})"
    )

    trigger = False
    action = payload["object_attributes"]["action"]

    changes = payload.get("changes", {})
    # Trigger only when bot is newly added as reviewer
    if changes:
        reviewers_change = changes.get("reviewers")
        if reviewers_change:
            previous_reviewers = {
                reviewer["id"] for reviewer in reviewers_change.get("previous", [])
            }
            current_reviewers = {
                reviewer["id"] for reviewer in reviewers_change.get("current", [])
            }
            if (
                bot.gitlab_user_id in current_reviewers
                and bot.gitlab_user_id not in previous_reviewers
            ):
                trigger = True

    # Trigger if Re-request review is made
    if action == "update" and changes:
        reviewers = changes.get("reviewers")
        if reviewers and isinstance(reviewers, list):
            for reviewer in reviewers:
                if (
                    reviewer.get("id") == bot.gitlab_user_id
                    and reviewer.get("re_requested", False) is True
                ):
                    trigger = True
                    break

    if not trigger:
        logger.info("No action required for this merge request event.")
        return

    # Extract relevant information from the payload
    mr_iid = payload.get("object_attributes", {}).get("iid")
    gitlab_project_id = payload.get("project", {}).get("id")

    # Create GitLab client
    gitlab_client = gitlab.Gitlab(
        get_app_settings(mongo_db).gitlab_base,
        private_token=bot.gitlab_access_token,
    )

    # Create an instance of the SmartAgent
    smart_agent = SmartAgent(
        openrouter_api_key=settings.openrouter_api_key,
        gitlab_client=gitlab_client,
        bot=bot,
        mongo_db=mongo_db,
    )

    # Send a note that the bot is working on it
    project = gitlab_client.projects.get(gitlab_project_id, lazy=True)
    mr = project.mergerequests.get(mr_iid, lazy=True)
    wait_note = mr.notes.create({"body": "Analyzing the merge request..."})

    # Run the agent with the extracted information
    try:
        response = await smart_agent.run(
            mr_iid=mr_iid,
            project_id=gitlab_project_id,
        )
    except Exception as e:
        logger.exception(
            f"Error processing merge request {mr_iid} in project {gitlab_project_id}"
        )
        response = f"Error processing the merge request: {str(e)}"
    finally:
        # Remove the "Analyzing the merge request..." note
        wait_note.delete()

    # Create note as response
    project = gitlab_client.projects.get(gitlab_project_id, lazy=True)
    mr = project.mergerequests.get(mr_iid, lazy=True)
    mr.notes.create({"body": response})


async def handle_note_event(
    bot: Bot, payload: Dict[str, Any], mongo_db: Database
) -> None:
    """
    Handle a note event from GitLab.
    """
    logger.info(
        f"Handling note event for bot {bot.id} (project {bot.gitlab_project_path})"
    )

    attrs = payload.get("object_attributes", {})
    noteable_type = attrs.get("noteable_type")

    # Only reply to merge request notes
    if noteable_type != "MergeRequest":
        logger.info("Note is not on a merge request. No action taken.")
        return

    project_id = payload.get("project", {}).get("id")
    mr_iid = payload.get("merge_request", {}).get("iid")
    discussion_id = attrs.get("discussion_id")
    note_content = attrs.get("note", "") or ""

    note_lower = note_content.strip().lower()
    name_lower = bot.name.lower()
    username_lower = bot.gitlab_user_name.lower()

    # Check if bot is mentioned at all
    if f"@{name_lower}" not in note_lower and f"@{username_lower}" not in note_lower:
        logger.info("Bot not mentioned in the note. No action taken.")
        return

    gitlab_client = gitlab.Gitlab(
        get_app_settings(mongo_db).gitlab_base,
        private_token=bot.gitlab_access_token,
    )

    # Detect command syntax: @bot/command
    is_command = note_lower.startswith(f"@{name_lower}/") or note_lower.startswith(
        f"@{username_lower}/"
    )

    # Get MR discussion now (used by both flows)
    project = gitlab_client.projects.get(project_id, lazy=True)
    mr = project.mergerequests.get(mr_iid, lazy=True)
    discussion = mr.discussions.get(discussion_id)

    # Create a temporary "Processing..." note
    wait_note = discussion.notes.create({"body": "Processing your request..."})

    try:
        if is_command:
            logger.info("Command detected in the note. Handling via CommandAgent.")

            command_agent = CommandAgent(
                openrouter_api_key=settings.openrouter_api_key,
                gitlab_client=gitlab_client,
                mongo_db=mongo_db,
                bot=bot,
            )

            command = note_content.strip()
            # Remove bot mention
            if command.lower().startswith(f"@{name_lower}/"):
                command = command[len(f"@{bot.name}/") :].strip()
            elif command.lower().startswith(f"@{username_lower}/"):
                command = command[len(f"@{bot.gitlab_user_name}/") :].strip()

            reply = await command_agent.run(
                input_command=command, project_id=project_id, mr_iid=mr_iid
            )

        else:
            logger.info("No command detected. Handling via SmartAgent.")

            notes = discussion.attributes.get("notes", [])
            history: list[ModelRequest | ModelResponse] = []

            # Sort notes by creation time ascending
            notes.sort(key=lambda x: x.get("created_at", ""))

            # Build chat history
            for note in notes[:-1]:  # Exclude current note
                if len(history) > settings.max_chat_history:
                    break

                body = note.get("body", "")
                body_lower = body.lower()

                if f"@{name_lower}" in body_lower or f"@{username_lower}" in body_lower:
                    history.append(ModelRequest(parts=[UserPromptPart(content=body)]))
                else:
                    history.append(ModelResponse(parts=[TextPart(content=body)]))

            # Remove the last one (the current message)
            if history:
                history.pop(0)

            smart_agent = SmartAgent(
                openrouter_api_key=settings.openrouter_api_key,
                gitlab_client=gitlab_client,
                bot=bot,
                mongo_db=mongo_db,
            )

            reply = await smart_agent.run(
                user_prompt=note_content,
                mr_iid=mr_iid,
                project_id=project_id,
                message_history=history,
            )

    except Exception as e:
        logger.exception(
            f"Error generating reply for note event on MR {mr_iid} in project {project_id}"
        )
        reply = f"Error processing your request: {str(e)}"

    finally:
        wait_note.delete()

    # Post final reply
    discussion.notes.create({"body": reply})
