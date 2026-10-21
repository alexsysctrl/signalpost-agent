"""A saved working state for the research layer.

Screening a batch is not a single question, it is a line of work: "companies in Oslo over 5 employees", then
"of those, ranked by revenue". The plan and the result set of each step are kept so the next question can
build on the last, and so a reviewer can see what the agent actually did rather than only what it printed.

Pins are organisations deliberately kept across steps — the ones a person asked to hold onto.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def empty_workspace() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "created_at": _now(), "pins": [], "history": []}


def load_workspace(path: str | Path) -> tuple[dict[str, Any], str | None]:
    """An unreadable workspace is reset, and the reset is reported instead of silently starting over."""
    source = Path(path)
    if not source.exists():
        return empty_workspace(), None
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("pins"), list) or not isinstance(value.get("history"), list):
            raise ValueError("unsupported workspace schema")
        return value, None
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return empty_workspace(), f"workspace reset: {type(exc).__name__}"


def record_screen(workspace: dict[str, Any], result: dict[str, Any], *, pin_organisations: list[str] | None = None) -> dict[str, Any]:
    """Append one screening step. The plan is stored with the result: the filter is the explanation.

    Returns a new dict. A working state that mutates in place while a caller still holds the previous one is
    how a history ends up describing the last question asked.
    """
    updated = json.loads(json.dumps(workspace))
    results = result.get("results") or []
    updated.setdefault("history", []).append(
        {
            "created_at": _now(),
            "query": result.get("query"),
            "plan": result.get("plan"),
            "abstained": bool(result.get("abstained")),
            "why_abstained": result.get("why_abstained"),
            "result_count": len(results),
            "result_organisation_numbers": [str(item.get("organisation_number")) for item in results],
        }
    )
    updated["history"] = updated["history"][-100:]
    pins = set(updated.setdefault("pins", []))
    pins.update(str(org) for org in (pin_organisations or []))
    updated["pins"] = sorted(pins)
    return updated


def save_workspace(path: str | Path, workspace: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(workspace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


if __name__ == "__main__":
    ws = empty_workspace()
    step = {"query": "companies in oslo with more than 5 employees top 2 by revenue", "plan": {"filters": [{"field": "municipality"}], "limit": 2}, "results": [{"organisation_number": "1"}, {"organisation_number": "2"}]}
    ws = record_screen(ws, step, pin_organisations=["1"])
    assert len(ws["history"]) == 1 and ws["history"][0]["result_count"] == 2, ws
    assert ws["history"][0]["plan"]["limit"] == 2, "the filter plan is the point of saving the step"
    abstained = record_screen(ws, {"query": "companies with positive glassdoor sentiment", "plan": {"filters": []}, "results": [], "abstained": True, "why_abstained": "no profile carries glassdoor sentiment"})
    assert abstained["history"][-1]["abstained"] is True, abstained["history"][-1]
    assert abstained["pins"] == ["1"], "an abstention does not change what is pinned"
    assert record_screen(ws, step)["pins"] == ["1"], "pinned organisations survive a step that does not mention them"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "workspace.json"
        save_workspace(path, abstained)
        loaded, note = load_workspace(path)
        assert note is None and loaded["history"][0]["result_count"] == 2, loaded
        path.write_text("{ not json", encoding="utf-8")
        reset, note = load_workspace(path)
        assert note and reset["history"] == [], (reset, note)
    print("workspace self-test OK: steps and pins persist, an abstention is recorded, unreadable state resets with a stated reason")
