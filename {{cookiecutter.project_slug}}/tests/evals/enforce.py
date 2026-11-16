#!/usr/bin/env python3
"""Decide whether a promptfoo eval run passed, from the output.json it wrote.

Usage:
    uv run python tests/evals/enforce.py output.json

promptfoo's own exit code does not reflect errors, so eval.yml and `make eval` both call
this instead. A run fails when a test case errored (the agent was never judged), or when
its pass rate is below the threshold in promptfoo.yaml.

Cases the grader could not judge are reported on their own. When the model behind an
`llm-rubric` assertion cannot be called (no credentials, no permission, quota), promptfoo
records a failed assertion with `metadata.graderError` and counts it as an ordinary
failure. They still count as failures against the threshold, which exists to absorb one
flaky case, so a single grader quota error does not fail a run on its own. But whenever
there are any, they are named first: a red run that is red because of them says "the
grader could not run" instead of "the agent got worse", and a green run warns.
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
    warnings: list[str] = field(default_factory=list)


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
    grader_lines = []
    if ungraded:
        grader_lines.append(
            f"{len(ungraded)} test case(s) could not be graded: the grader model call "
            "failed (credentials, permission or quota). They count as failures, but "
            "say nothing about the agent."
        )
        grader_lines.extend(f"  {line}" for line in ungraded)

    if errors:
        return Verdict(
            passed=False,
            summary=summary,
            errors=grader_lines
            + [
                f"{errors} test case(s) errored (could not complete): treated as failing."
            ],
        )
    if total == 0:
        return Verdict(
            passed=False, summary=summary, errors=["The run has no results."]
        )
    if pass_rate < threshold:
        below = (
            f"Pass rate {pass_rate:.2%} is below the required threshold "
            f"{threshold:.0%}."
        )
        if not ungraded:
            return Verdict(passed=False, summary=summary, errors=[below])
        # Blame the grader only if it decides the outcome: the run would have passed had
        # every ungraded case passed. Otherwise the agent failed on its own as well, and
        # a re-run with a working grader would still be red.
        best_case = (successes + len(ungraded)) / total
        if best_case >= threshold:
            cause = " The ungraded cases decide it: fix the grader, then re-run."
        else:
            cause = (
                f" Even if every ungraded case had passed, the pass rate would be "
                f"{best_case:.2%}: the agent fails cases of its own as well."
            )
        return Verdict(
            passed=False, summary=summary, errors=grader_lines + [below + cause]
        )
    return Verdict(passed=True, summary=summary, warnings=grader_lines)


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
    for line in verdict.warnings:
        print(f"::warning::{line}")
    for line in verdict.errors:
        print(f"::error::{line}")
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
