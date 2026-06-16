import shlex
from typing import Callable
import gitlab
from pymongo.database import Database

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openrouter import OpenRouterProvider

from .commands import (
    CommandInterface,
    HelpCommand,
    ReviewCommand,
    SuggestCommand,
    DescribeCommand,
    AddDocsCommand,
    CommandParseError,
)
from app.db.models import Bot, MrAgentHistory


class CommandAgent:
    commands: dict[str, CommandInterface] = {
        "help": HelpCommand,
        "review": ReviewCommand,
        "describe": DescribeCommand,
        "suggest": SuggestCommand,
        "add_docs": AddDocsCommand,
    }

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
        self.openrouter_api_key = openrouter_api_key

    async def run(
        self,
        input_command: str,
        project_id: int,
        mr_iid: int,
    ) -> str:
        command_name, flags, args = self._parse_bot_command(input_command)

        if command_name not in self.commands:
            raise CommandParseError(f"Unknown command: {command_name}")

        command_class = self.commands[command_name]
        command_instance = command_class(
            gitlab_client=self.gitlab_client,
            mongo_db=self.mongo_db,
            bot=self.bot,
            model=self.model,
        )

        return await command_instance.run(
            project_id,
            mr_iid,
            flags,
            args,
        )

    def _init_agent(self, system_prompt: str) -> Agent:
        return Agent(
            model=self.model,
            tools=[],
            system_prompt=system_prompt,
        )

    @staticmethod
    def _parse_bot_command(text) -> tuple[str, dict[str, str | bool], list[str]]:
        """
        Parse commands of the form:

            /help --all
            /describe --note "here I am debugging"
            /run task1 task2 --force

        Returns:
            command: str                 (e.g. 'help', 'describe')
            flags: dict[str, str|bool]  (e.g. {'note': 'text', 'all': True})
            args: list[str]             (positional arguments)
        """
        # Tokenize safely
        try:
            tokens = shlex.split(text)
        except Exception as exc:
            raise CommandParseError(f"Failed to parse command: {exc}")

        if not tokens:
            raise CommandParseError("Empty command.")

        command = tokens[0]

        flags = {}
        args = []
        it = iter(tokens[1:])

        for token in it:
            if token.startswith("--"):
                key = token[2:]
                if not key:
                    raise CommandParseError("Empty flag name '--' detected.")

                # Check next token for value
                try:
                    nxt = next(it)
                except StopIteration:
                    # Flag without value → interpreted as True
                    flags[key] = True
                    continue

                if nxt.startswith("--"):
                    # No value → True, but push nxt back into iterator
                    flags[key] = True
                    it = iter([nxt] + list(it))
                else:
                    flags[key] = nxt
            else:
                args.append(token)

        return command, flags, args
