"""tests/evals/enforce.py tells a grader that could not run from an agent that failed.

The output.json shapes below are trimmed from a real promptfoo 0.123.1 run, with the
grader's credentials deliberately missing: the failed grading call is recorded as a
failed assertion with `metadata.graderError`, and `stats.errors` stays 0.
"""

import json
from pathlib import Path

from tests.evals import enforce

GRADER_REASON = (
    "API call error: 401 Unauthorized: API keys are not supported by this API. "
    "Expected OAuth2 access token or other authentication credentials"
)


def _result(description: str, components: list[dict]) -> dict:
    passed = all(component["pass"] for component in components)
    return {
        "success": passed,
        "testCase": {"description": description},
        "gradingResult": {"pass": passed, "componentResults": components},
    }


def _passing(description: str) -> dict:
    return _result(
        description,
        [{"pass": True, "score": 1, "reason": "Assertion passed"}],
    )


def _ungraded(description: str) -> dict:
    return _result(
        description,
        [
            {"pass": True, "score": 1, "reason": "Assertion passed"},
            {
                "pass": False,
                "score": 0,
                "reason": GRADER_REASON,
                "metadata": {"graderError": True},
            },
        ],
    )


def _failing(description: str) -> dict:
    return _result(
        description,
        [{"pass": False, "score": 0, "reason": "Expected output to contain 'hello'"}],
    )


def _output(results: list[dict], errors: int = 0) -> dict:
    successes = sum(1 for result in results if result["success"])
    return {
        "results": {
            "stats": {
                "successes": successes,
                "failures": len(results) - successes,
                "errors": errors,
            },
            "results": results,
        }
    }


def test_all_passing_run_passes():
    # Arrange
    output = _output([_passing("a"), _passing("b")])

    # Act
    verdict = enforce.judge(output, threshold=1.0)

    # Assert
    assert verdict.passed
    assert verdict.errors == []


def test_grader_errors_below_threshold_are_reported_first_and_as_such():
    # Arrange
    output = _output([_passing("a"), _ungraded("pii: SSN not repeated")])

    # Act
    verdict = enforce.judge(output, threshold=0.95)

    # Assert: the grader is named before the pass rate, and not blamed on the agent
    assert not verdict.passed
    assert "could not be graded" in verdict.errors[0]
    assert "say nothing about the agent" in verdict.errors[0]
    assert any("pii: SSN not repeated" in line for line in verdict.errors)
    assert any(GRADER_REASON in line for line in verdict.errors)
    assert "below the required threshold" in verdict.errors[-1]


def test_one_grader_error_within_the_threshold_passes_with_a_warning():
    # Arrange: 19 of 20, the one flaky case the 0.95 threshold exists to absorb
    results = [_passing(f"case {n}") for n in range(19)] + [_ungraded("flaky")]
    output = _output(results)

    # Act
    verdict = enforce.judge(output, threshold=0.95)

    # Assert
    assert verdict.passed
    assert verdict.errors == []
    assert "could not be graded" in verdict.warnings[0]


def test_every_case_ungraded_fails():
    # Arrange: a grader that cannot log in at all
    output = _output([_ungraded("a"), _ungraded("b")])

    # Act
    verdict = enforce.judge(output, threshold=0.5)

    # Assert
    assert not verdict.passed
    assert "could not be graded" in verdict.errors[0]


def test_grader_is_blamed_only_when_it_decides_the_outcome():
    # Arrange: 18 pass, 2 ungraded -- with a working grader the run could pass
    results = [_passing(f"case {n}") for n in range(18)]
    results += [_ungraded("g1"), _ungraded("g2")]

    # Act
    verdict = enforce.judge(_output(results), threshold=0.95)

    # Assert
    assert not verdict.passed
    assert "fix the grader, then re-run" in verdict.errors[-1]


def test_agent_failures_are_named_when_the_grader_does_not_decide_it():
    # Arrange: 16 pass, 3 agent failures, 1 ungraded -- 85% at best, still red
    results = [_passing(f"case {n}") for n in range(16)]
    results += [_failing(f"f{n}") for n in range(3)] + [_ungraded("g")]

    # Act
    verdict = enforce.judge(_output(results), threshold=0.95)

    # Assert: the grader is still reported first, but not blamed for the red run
    assert not verdict.passed
    assert "could not be graded" in verdict.errors[0]
    assert "fix the grader" not in verdict.errors[-1]
    assert "85.00%" in verdict.errors[-1]
    assert "the agent fails cases of its own" in verdict.errors[-1]


def test_grader_errors_are_reported_before_errored_cases():
    # Arrange
    results = [_passing(f"case {n}") for n in range(18)] + [_ungraded("g")]

    # Act
    verdict = enforce.judge(_output(results, errors=1), threshold=0.95)

    # Assert
    assert not verdict.passed
    assert "could not be graded" in verdict.errors[0]
    assert "errored" in verdict.errors[-1]


def test_grader_errors_are_counted_once_per_case():
    # Arrange
    results = [_ungraded("a"), _ungraded("b"), _failing("c")]

    # Act
    found = enforce.grader_errors(results)

    # Assert
    assert len(found) == 2


def test_errored_case_fails_the_run():
    # Arrange
    output = _output([_passing("a")], errors=1)

    # Act
    verdict = enforce.judge(output, threshold=0.5)

    # Assert
    assert not verdict.passed
    assert "errored" in verdict.errors[0]


def test_pass_rate_below_threshold_fails_the_run():
    # Arrange
    output = _output([_passing("a"), _failing("b")])

    # Act
    verdict = enforce.judge(output, threshold=0.95)

    # Assert
    assert not verdict.passed
    assert "below the required threshold" in verdict.errors[0]


def test_empty_run_fails():
    # Arrange
    output = _output([])

    # Act
    verdict = enforce.judge(output, threshold=0.95)

    # Assert
    assert not verdict.passed


def test_case_without_grading_result_is_not_a_grader_error():
    # Arrange: an errored case can carry no gradingResult at all
    results = [{"success": False, "testCase": {"description": "a"}}]

    # Act
    found = enforce.grader_errors(results)

    # Assert
    assert found == []


def test_threshold_is_read_from_promptfoo_yaml():
    # Act
    threshold = enforce.load_threshold()

    # Assert
    assert 0 < threshold <= 1


def test_main_exits_non_zero_on_a_grader_error(tmp_path: Path, capsys):
    # Arrange
    path = tmp_path / "output.json"
    path.write_text(json.dumps(_output([_ungraded("a")])))

    # Act
    code = enforce.main(["enforce.py", str(path)])

    # Assert
    assert code == 1
    out = capsys.readouterr().out
    assert "::error::1 test case(s) could not be graded" in out
    assert "::error::Pass rate 0.00% is below" in out
