from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from crystal_agent.schemas import RankedCandidate


def render_report(project_id: str, candidates: list[RankedCandidate]) -> str:
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("report.html.j2")
    return template.render(project_id=project_id, candidates=candidates)
