from typing import List, Optional
from pydantic import BaseModel, create_model
from pydantic_ai import AgentRunResult

from .command_interface import CommandInterface, RelatedIssue
from app.agents.utils import emphasize_header, fetch_file, get_line_link
from app.prompts.review import system_template, user_template
from app.core.config import settings
from app.core.log import logger


class ReviewInput(BaseModel):
    title: str
    branch: str
    diff: str
    description: Optional[str] = None
    extra_instructions: Optional[str] = None
    related_issues: Optional[List[RelatedIssue]] = None
    require_estimate_effort_to_review: bool = False
    require_score: bool = False
    require_tests: bool = False
    require_security_review: bool = False
    require_prompt_suggestion: bool = False
    num_max_findings: int = 5
    is_ai_metadata: bool = False
    duplicate_prompt_examples: bool = False


class KeyIssuesComponentLink(BaseModel):
    relevant_file: str
    issue_header: str
    issue_content: str
    start_line: int
    end_line: int


class IssueCompliance(BaseModel):
    issue_id: str
    issue_title: str
    issue_description: str
    fully_compliant_points: str
    not_compliant_points: str
    requires_further_human_verification: str


class ReviewCommand(CommandInterface):
    emojis = {
        "Can be split": "🔀",
        "Key issues to review": "⚡",
        "Recommended focus areas for review": "⚡",
        "Score": "🏅",
        "Relevant tests": "🧪",
        "Focused PR": "✨",
        "Relevant issue": "🎫",
        "Security concerns": "🔒",
        "Insights from user's answers": "📝",
        "Code feedback": "🤖",
        "Estimated effort to review": "⏱️",
        "Issue compliance check": "🎫",
        "Prompt suggestion for agent": "🤖",
    }

    async def run(
        self,
        project_id: int,
        mr_iid: int,
        flags: dict[str, str | bool],
        args: list[str],
    ) -> str:
        # Gather gitlab data
        gitlab_data = await self.gether_gitlab_data(project_id, mr_iid)

        # Prepare input data for the review command
        input_data = ReviewInput(
            title=gitlab_data.get("title", ""),
            branch=gitlab_data.get("branch", ""),
            diff=gitlab_data.get("diff", ""),
            description=gitlab_data.get("description"),
            related_issues=gitlab_data.get("related_issues"),
            require_estimate_effort_to_review=flags.get(
                "require_estimate_effort_to_review", True
            ),
            require_score=flags.get("require_score", True),
            require_tests=flags.get("require_tests", True),
            require_security_review=flags.get("require_security_review", True),
            require_prompt_suggestion=flags.get("require_prompt_suggestion", True),
        )

        # Render prompts
        system_prompt = self._render_system_prompt(input_data)
        user_prompt = self._render_input(input_data)

        # Build MR review output base model dynamically
        model_fields = {
            # FIX: Removed the [] brackets around List[...]
            "issue_compliance_check": (List[IssueCompliance], None)
            if input_data.related_issues
            else (None, ...),
            "estimated_effort_to_review": (Optional[int], None)
            if input_data.require_estimate_effort_to_review
            else (None, ...),
            "score": (Optional[str], None) if input_data.require_score else (None, ...),
            "relevant_tests": (Optional[str], None)
            if input_data.require_tests
            else (None, ...),
            "security_concerns": (Optional[str], None)
            if input_data.require_security_review
            else (None, ...),
            "prompt_suggestion_for_agent": (Optional[str], None)
            if input_data.require_prompt_suggestion
            else (None, ...),
            "key_issues_to_review": (List[KeyIssuesComponentLink], ...),
        }
        # Remove None fields
        model_fields = {k: v for k, v in model_fields.items() if v[0] is not None}
        ReviewOutput = create_model(
            "ReviewOutput",
            **model_fields,
        )

        # Build agent
        self.build_agent(system_prompt, ReviewOutput)

        # Get response from agent
        response: AgentRunResult = await self.agent.run(
            user_prompt=user_prompt,
        )
        output_data = response.output

        # Convert to markdown
        markdown_text = self._convert_to_markdown(
            output_data, project_id, input_data.branch
        )

        return markdown_text

    def _convert_to_markdown(
        self, output_data: BaseModel, project_id: int, source_branch: str
    ) -> str:
        """Convert the model output to the legacy markdown guide."""

        def _is_value_no(value: object) -> bool:
            return isinstance(value, str) and value.strip().lower() == "no"

        def _issue_markdown_logic(emoji: str, markdown_text: str, value: object) -> str:
            markdown_text += "<tr><td>"
            markdown_text += f"{emoji}&nbsp;<strong>Issue compliance check</strong>"

            if not value:
                markdown_text += "</td></tr>\n"
                return markdown_text

            markdown_text += "<br><br>\n"
            issues = value if isinstance(value, list) else []
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                id_str = issue.get("issue_id", "") or ""
                if not id_str.startswith("#"):
                    id_str = f"#{id_str}"
                title = issue.get("issue_title", "") or ""
                description = issue.get("issue_description", "")
                compliant = issue.get("fully_compliant_points", "")
                not_compliant = issue.get("not_compliant_points", "")
                verify = issue.get("requires_further_human_verification", "")

                if title:
                    markdown_text += f"<strong>{id_str} - {title}</strong><br>"
                if description:
                    markdown_text += f"Issue Description: {description}<br><br>"
                if compliant:
                    markdown_text += (
                        emphasize_header(f"Fully compliant: {compliant}") + "<br><br>"
                    )
                if not_compliant:
                    markdown_text += (
                        emphasize_header(f"Not compliant: {not_compliant}") + "<br><br>"
                    )
                if verify:
                    markdown_text += (
                        emphasize_header(f"Needs verification: {verify}") + "<br><br>"
                    )
                markdown_text += "<br>"

            markdown_text += "</td></tr>\n"
            return markdown_text

        def _get_snippet(file_path: str, start: int, end: int) -> str:
            if not file_path:
                return ""
            content = fetch_file(
                gitlab_client=self.gitlab_client,
                project_id=project_id,
                file_path=file_path,
                ref=source_branch,
            )
            if not content:
                return ""
            lines = content.splitlines()
            if start <= 0:
                start_idx = 0
            else:
                start_idx = max(start - 1, 0)
            end_idx = end if end and end > 0 else start_idx + 1
            end_idx = min(end_idx, len(lines))
            snippet_lines = []
            for idx in range(start_idx, end_idx):
                snippet_lines.append(f"{idx + 1:5} {lines[idx]}")
            return "\n".join(snippet_lines)

        markdown_text = "## MR Reviewer Guide 🔍\n\n"
        markdown_text += "Here are some key observations to aid the review process:\n\n"
        markdown_text += "<table>\n"

        raw_output = (
            output_data.model_dump()
            if isinstance(output_data, BaseModel)
            else dict(output_data)
        )
        review_payload = raw_output.get("review", raw_output)

        try:
            project = self.gitlab_client.projects.get(project_id)
            project_path = project.path_with_namespace
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to fetch project for markdown links: %s", str(exc))
            project_path = ""

        for key, value in review_payload.items():
            if value is None or value == "" or value == {} or value == []:
                if key.lower() != "key_issues_to_review":
                    continue

            key_nice = key.replace("_", " ").capitalize()
            emoji = self.emojis.get(key_nice, "")

            if "estimated effort to review" in key_nice.lower():
                value_str = str(value).strip()
                try:
                    value_int = int(value_str.split(",")[0])
                except Exception:
                    continue
                value_int = max(1, min(5, value_int))
                bars = "🔵" * value_int + "⚪" * (5 - value_int)
                markdown_text += (
                    f"<tr><td>{emoji}&nbsp;<strong>Estimated effort to review</strong>: "
                    f"{value_int} {bars}</td></tr>\n"
                )
            elif "relevant tests" in key_nice.lower():
                value_str = str(value).strip().lower()
                markdown_text += "<tr><td>"
                if _is_value_no(value_str):
                    markdown_text += f"{emoji}&nbsp;<strong>No relevant tests</strong>"
                else:
                    markdown_text += f"{emoji}&nbsp;<strong>MR contains tests</strong>"
                markdown_text += "</td></tr>\n"
            elif "issue compliance check" in key_nice.lower():
                markdown_text = _issue_markdown_logic(emoji, markdown_text, value)
            elif "security concerns" in key_nice.lower():
                markdown_text += "<tr><td>"
                if _is_value_no(value):
                    markdown_text += (
                        f"{emoji}&nbsp;<strong>No security concerns identified</strong>"
                    )
                else:
                    markdown_text += (
                        f"{emoji}&nbsp;<strong>Security concerns</strong><br><br>\n\n"
                    )
                    markdown_text += emphasize_header(str(value).strip())
                markdown_text += "</td></tr>\n"
            elif "key issues to review" in key_nice.lower():
                markdown_text += "<tr><td>"
                if _is_value_no(value) or not value:
                    markdown_text += (
                        f"{emoji}&nbsp;<strong>No major issues detected</strong>"
                    )
                    markdown_text += "</td></tr>\n"
                    continue

                markdown_text += (
                    f"{emoji}&nbsp;<strong>Recommended focus areas for review</strong>"
                    "<br><br>\n\n"
                )
                issues = value if isinstance(value, list) else []
                for issue in issues:
                    if not isinstance(issue, dict):
                        continue
                    relevant_file = issue.get("relevant_file", "").strip()
                    issue_header = issue.get("issue_header", "").strip()
                    if issue_header.lower() == "possible bug":
                        issue_header = "Possible Issue"
                    issue_content = issue.get("issue_content", "").strip()
                    start_line = int(str(issue.get("start_line", 0) or 0))
                    end_line = int(str(issue.get("end_line", 0) or 0))

                    snippet = _get_snippet(relevant_file, start_line, end_line)
                    reference_link = ""
                    if project_path:
                        try:
                            reference_link = get_line_link(
                                self.gitlab_client.url,
                                project_path,
                                source_branch,
                                relevant_file,
                                start_line,
                                end_line if end_line else None,
                            )
                        except Exception as exc:  # pragma: no cover - defensive
                            logger.error("Failed to build line link: %s", str(exc))

                    if reference_link:
                        header_str = f"<a href='{reference_link}'><strong>{issue_header}</strong></a>"
                    else:
                        header_str = f"<strong>{issue_header}</strong>"

                    if snippet:
                        issue_str = (
                            f"<details><summary>{header_str}\n\n{issue_content}"
                            "</summary>\n\n"
                            f"```{relevant_file.split('.')[-1] if relevant_file else ''}\n"
                            f"{snippet}\n```"
                            "\n</details>"
                        )
                    else:
                        issue_str = f"{header_str}<br>{issue_content}"

                    markdown_text += f"{issue_str}\n\n"

                markdown_text += "</td></tr>\n"
            elif "prompt suggestion for agent" in key_nice.lower():
                markdown_text += "<tr><td>"
                if _is_value_no(value):
                    markdown_text += (
                        f"{emoji}&nbsp;<strong>No prompt suggestion provided</strong>"
                    )
                else:
                    markdown_text += f"{emoji}&nbsp;<strong>Prompt suggestion for comprehensive review by agent</strong><br><br>\n\n"
                    markdown_text += emphasize_header(str(value).strip())
                markdown_text += "</td></tr>\n"
            else:
                markdown_text += f"<tr><td>{emoji}&nbsp;<strong>{key_nice}</strong>: {value}</td></tr>\n"

        markdown_text += "</table>\n"
        return markdown_text

    def _render_input(self, input_data: ReviewInput) -> str:
        return user_template.render(**input_data.model_dump())

    def _render_system_prompt(self, input_data: ReviewInput) -> str:
        return system_template.render(**input_data.model_dump())