#!/usr/bin/env python3
"""Decide whether a promptfoo eval run passed, from the output.json it wrote.

Usage:
    uv run python tests/evals/enforce.py output.json

promptfoo's own exit code does not reflect errors, so eval.yml and `make eval` both call
this instead. It fails a run for three reasons, checked in this order:

1. The grader could not run. When the model behind an `llm-rubric` assertion cannot be
   called (no credentials, no permission, quota), promptfoo records a failed assertion
   with `metadata.graderError` and counts it as an ordinary failure, not as an error.
   Reported on its own, a red run then says "the grader could not log in" instead of
   "the agent got worse".
2. A test case errored, so the agent was never judged.
3. The pass rate is below the threshold in promptfoo.yaml.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG = Path(__file__).parent / "promptfoo.yaml"


@dataclass
class Verdict:
    """Whether the run passed, and the lines that explain why."""

    passed: bool
    summary: str
    errors: list[str] = field(default_factory=list)


def grader_errors(results: list[dict[str, Any]]) -> list[str]:
    """Return one line per test case whose grader call failed, with promptfoo's reason."""
    found = []
    for result in results:
        grading = result.get("gradingResult") or {}
        for component in grading.get("componentResults") or []:
            metadata = component.get("metadata") or {}
            if metadata.get("graderError"):
                description = (result.get("testCase") or {}).get("description", "?")
                reason = component.get("reason", "")
                found.append(f"{description}: {reason}")
                break
    return found


def judge(output: dict[str, Any], threshold: float) -> Verdict:
    """Return the verdict for one promptfoo output.json."""
    stats = output["results"]["stats"]
    successes = stats["successes"]
    failures = stats["failures"]
    errors = stats["errors"]
    total = successes + failures + errors
    pass_rate = successes / total if total else 0.0
    summary = (
        f"successes={successes} failures={failures} errors={errors} "
        f"pass_rate={pass_rate:.2%} threshold={threshold:.0%}"
    )

    ungraded = grader_errors(output["results"].get("results") or [])
    if ungraded:
        lines = [
            f"{len(ungraded)} test case(s) could not be graded: the grader model call "
            "failed (credentials, permission or quota). This says nothing about the "
            "agent. Fix the grader's login, then re-run."
        ]
        lines.extend(f"  {line}" for line in ungraded)
        return Verdict(passed=False, summary=summary, errors=lines)
    if errors:
        return Verdict(
            passed=False,
            summary=summary,
            errors=[
                f"{errors} test case(s) errored (could not complete): treated as failing."
            ],
        )
    if total == 0:
        return Verdict(
            passed=False, summary=summary, errors=["The run has no results."]
        )
    if pass_rate < threshold:
        return Verdict(
            passed=False,
            summary=summary,
            errors=[
                f"Pass rate {pass_rate:.2%} is below the required threshold "
                f"{threshold:.0%}."
            ],
        )
    return Verdict(passed=True, summary=summary)


def load_threshold(config: Path = CONFIG) -> float:
    """Return the pass-rate threshold set in promptfoo.yaml (1.0 when it sets none)."""
    with config.open() as f:
        return float(yaml.safe_load(f).get("threshold", 1.0))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: enforce.py <promptfoo output.json>", file=sys.stderr)
        return 2
    with Path(argv[1]).open() as f:
        output = json.load(f)
    verdict = judge(output, load_threshold())
    print(verdict.summary)
    # `::error::` makes GitHub Actions show the line as an annotation; locally it is
    # just a prefix.
    for line in verdict.errors:
        print(f"::error::{line}")
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
