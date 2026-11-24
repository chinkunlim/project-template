"""HTTP routes for Master-Child live linkage (`/api/projects/graphify`, `/api/feedback/*`).

Purpose:
    Exposes graph refresh and bidirectional `TEMPLATE_FEEDBACK.md` management on the
    local FastAPI Hub (`entrypoints/web_ui.py`), backed by `services/template_service.py`
    and `services/feedback.py`. Write endpoints enforce `confirm=true` (HTTP 428 otherwise).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from project_template.entrypoints.web_routes import need_confirm, started
from project_template.services import feedback as feedback_svc
from project_template.services import template_service as ts

logger = logging.getLogger(__name__)
router = APIRouter()


class GraphifyIn(BaseModel):
    """Target selector for refreshing dependency graphs and Graphify output."""

    project: str = Field(default="", description="Tracked project name or `master`; empty = all tracked projects")
    path: str = Field(default="", description="Absolute project path (alternative to project)")
    root: str = Field(default="", description="Projects root folder; empty = default")
    include_master: bool = Field(default=False, description="Also refresh Master's own graphs when updating all")


class FeedbackAddIn(BaseModel):
    """Payload to append a template improvement suggestion to a project's `TEMPLATE_FEEDBACK.md`."""

    project: str = Field(default="", description="Tracked project name or `master`")
    path: str = Field(default="", description="Absolute project path (alternative to project)")
    root: str = Field(default="", description="Projects root folder; empty = default")
    text: str = Field(description="Suggestion description")
    source: str = Field(default="master-hub", description="Source conversation or task label")
    status: str = Field(default="待決定", description="Initial status (`待決定`, `已採用`, `不採用`)")
    confirm: bool = Field(default=False, description="Must be true: writes to docs/TEMPLATE_FEEDBACK.md")


class FeedbackStatusIn(BaseModel):
    """Payload to update a suggestion row's status in a project's `TEMPLATE_FEEDBACK.md`."""

    file: str = Field(description="Path to `<project>/docs/TEMPLATE_FEEDBACK.md`")
    text: str = Field(description="Exact suggestion text of the row to update")
    date: str = Field(default="", description="Optional row date to disambiguate identical texts")
    status: str = Field(description="New status (`待決定`, `已採用`, `不採用`)")
    confirm: bool = Field(default=False, description="Must be true: edits docs/TEMPLATE_FEEDBACK.md")


@router.post("/api/projects/graphify", status_code=202)
def refresh_project_graphify(body: GraphifyIn) -> dict[str, Any]:
    """Run `agentctl graph` and `graphify update .` for one or all tracked projects.

    Args:
        body: Target project selector and projects root.

    Returns:
        Started background job metadata (`id`, `title`, `commands`).
    """
    root = ts.resolve_root(body.root)
    title, steps = ts.graphify_steps(body.model_dump(), root)
    return started(title, steps, after=lambda job: setattr(job, "result", ts.overview(root)), keep_going=True)


@router.post("/api/feedback/add")
def add_template_feedback(body: FeedbackAddIn) -> dict[str, Any]:
    """Append a template improvement suggestion to a project's `docs/TEMPLATE_FEEDBACK.md`. Needs `confirm=true`.

    Args:
        body: Target project, suggestion text, metadata, and confirmation flag.

    Returns:
        Inserted row details including `project`, `file`, `date`, `text`, and `status`.
    """
    need_confirm(body.confirm, "新增母版改進建議")
    root = ts.resolve_root(body.root)
    target = ts.resolve_feedback_target(body.path or body.project, root)
    return feedback_svc.add_suggestion(target, body.text, source=body.source, status=body.status)


@router.post("/api/feedback/status")
def update_feedback_status(body: FeedbackStatusIn) -> dict[str, Any]:
    """Update a row status inside `<project>/docs/TEMPLATE_FEEDBACK.md`. Needs `confirm=true`.

    Args:
        body: Target file, matching text/date, new status, and confirmation flag.

    Returns:
        Updated suggestion row details.
    """
    need_confirm(body.confirm, "更新改進建議狀態")
    return feedback_svc.update_suggestion_status(Path(body.file), body.text, body.status, match_date=body.date)
