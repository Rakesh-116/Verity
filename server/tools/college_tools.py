"""Primitive mocked college assessment reader for the Verity demo."""

from typing import Any


def get_assessment_status(course: str) -> dict[str, Any]:
    """Return mocked upcoming assessment status for one explicitly named course."""
    if not course.strip():
        return {"course": course, "success": False, "reason": "course_required"}
    return {
        "course": course,
        "success": True,
        "assessments": [
            {"title": f"{course} assignment", "status": "due", "due_in_days": 3},
            {"title": f"{course} quiz", "status": "graded", "score": "pending release"},
        ],
        "mocked": True,
    }
