from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, create_model
from pydantic_ai import AgentRunResult

from .command_interface import CommandInterface, RelatedIssue
from app.agents.utils import get_line_link
from app.prompts.describe import system_template, user_template
from app.core.config import settings


class MRType(str, Enum):
    bug_fix = "Bug fix"
    tests = "Tests"
    enhancement = "Enhancement"
    documentation = "Documentation"
    other = "Other"


class DescribeInput(BaseModel):
    title: str
    branch: str
    diff: str
    description: Optional[str] = None
    commit_messages_str: Optional[str] = None
    related_issues: Optional[List[RelatedIssue]] = None
    extra_instructions: Optional[str] = None
    enable_diagram: bool = False
    enable_files: bool = False
    enable_file_summary: bool = False
    duplicate_prompt_examples: bool = False


class FileDescription(BaseModel):
    filename: str
    changes_summary: Optional[str] = None
    changes_title: str
    label: str


class DescribeCommand(CommandInterface):
    async def run(
        self,
        project_id: int,
        mr_iid: int,
        flags: dict[str, str | bool],
        args: list[str],
    ) -> str:
        # Gather GitLab data
        gitlab_data = await self.gether_gitlab_data(project_id, mr_iid)

        # Prepare input for the agent
        input_data = DescribeInput(
            title=gitlab_data["title"],
            branch=gitlab_data["branch"],
            diff=gitlab_data["diff"],
            description=gitlab_data.get("description"),
            related_issues=gitlab_data.get("related_issues"),
            extra_instructions=flags.get("extra_instructions"),
            enable_diagram=flags.get("enable_diagram", True),
            enable_files=flags.get("enable_files", True),
            enable_file_summary=flags.get("enable_file_summary", True),
            duplicate_prompt_examples=flags.get("duplicate_prompt_examples", False),
        )

        # Render prompts
        system_prompt = self._render_system_prompt(input_data)
        user_prompt = self._render_input(input_data)

        # Build MR describe output base model dynamically
        model_fields = {
            "type": (List[MRType], ...),
            "description": (str, ...),
            "title": (str, ...),
            "changes_diagram": (Optional[str], None)
            if input_data.enable_diagram
            else None,
            "mr_files": (Optional[List[FileDescription]], None)
            if input_data.enable_files
            else None,
        }
        # Remove None fields
        model_fields = {k: v for k, v in model_fields.items() if v is not None}
        MRDescriptionOutput = create_model("MRDescriptionOutput", **model_fields)

        # Build agent
        self.build_agent(system_prompt, MRDescriptionOutput)

        # Get response from agent
        response: AgentRunResult = await self.agent.run(user_prompt=user_prompt)
        output_data = response.output

        # Convert to markdown
        markdown_text = self._convert_to_markdown(output_data)

        return markdown_text

    def _convert_to_markdown(
        self,
        output_data: BaseModel,
        project_id: Optional[int] = None,
        source_branch: str | None = None,
    ) -> str:
        """Render the model output into the legacy markdown layout."""

        def _normalize_dict(data: BaseModel | dict) -> dict:
            if isinstance(data, BaseModel):
                return data.model_dump()
            return dict(data)

        def _format_diagram(diagram: str) -> str:
            diagram = diagram.strip()
            if not diagram:
                return ""
            if diagram.startswith("```") and not diagram.endswith("```"):
                return f"{diagram}\n```"
            if not diagram.startswith("```") and "mermaid" in diagram:
                return f"```{diagram}```"
            return diagram

        def _build_file_table(files: list[dict], project_path: str, branch: str) -> str:
            if not files:
                return ""

            grouped: dict[str, list[dict]] = {}
            for file in files:
                label = (file.get("label") or "other").strip()
                grouped.setdefault(label, []).append(file)

            html_parts: list[str] = []
            html_parts.append("<table>")
            html_parts.append(
                '<thead><tr><th></th><th align="left">Relevant files</th></tr></thead>'
            )
            html_parts.append("<tbody>")

            for label, label_files in grouped.items():
                html_parts.append(
                    f"<tr><td><strong>{label.capitalize()}</strong></td><td><table>"
                )
                for file in label_files:
                    filename = (file.get("filename") or "").replace("'", "`")
                    display_name = filename.split("/")[-1] if filename else ""
                    changes_title = (file.get("changes_title") or "").strip()
                    changes_summary = (file.get("changes_summary") or "").strip()

                    link = ""
                    if project_path and branch and filename:
                        try:
                            link = get_line_link(
                                self.gitlab_client.url,
                                project_path,
                                branch,
                                filename,
                                -1,
                            )
                        except Exception:
                            link = ""

                    heading = (
                        f'<a href="{link}"><strong>{display_name}</strong></a>'
                        if link
                        else f"<strong>{display_name}</strong>"
                    )
                    if changes_title:
                        heading += f"<dd><code>{changes_title}</code></dd>"

                    summary_html = changes_summary.replace("\\n", "<br>")
                    html_parts.append(
                        f"<tr><td>{heading}</td><td>{summary_html}</td></tr>"
                    )

                html_parts.append("</table></td></tr>")

            html_parts.append("</tbody></table>")
            return "\n".join(html_parts)

        data = _normalize_dict(output_data)
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        types = data.get("type") or []
        diagram = _format_diagram(data.get("changes_diagram") or "")
        mr_files = data.get("mr_files") or []

        project_path = self.bot.gitlab_project_path or ""
        if project_id is not None:
            try:
                project = self.gitlab_client.projects.get(project_id, lazy=True)
                project_path = project.path_with_namespace
            except Exception:
                project_path = self.bot.gitlab_project_path or ""

        sections: list[str] = []

        if types:
            types_str = ", ".join(types)
            sections.append(f"### **MR Type**\n{types_str}")

        if description:
            sections.append(f"### **Description**\n{description}")

        if diagram:
            sections.append(f"### Diagram Walkthrough\n\n{diagram}")

        if mr_files:
            file_table = _build_file_table(mr_files, project_path, source_branch)
            if file_table:
                sections.append(
                    "<details> <summary><h3> File Walkthrough</h3></summary>\n\n"
                    f"{file_table}\n\n</details>"
                )

        body = "\n\n___\n\n".join(sections)
        return f"## Title\n\n{title}\n\n___\n{body}"

    def _render_input(self, input_data: DescribeInput) -> str:
        return user_template.render(**input_data.model_dump())

    def _render_system_prompt(self, input_data: DescribeInput) -> str:
        return system_template.render(**input_data.model_dump())
