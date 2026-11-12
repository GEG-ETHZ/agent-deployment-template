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


def test_grader_error_is_reported_as_such_not_as_an_agent_failure():
    # Arrange
    output = _output([_passing("a"), _ungraded("pii: SSN not repeated")])

    # Act
    verdict = enforce.judge(output, threshold=0.5)

    # Assert: fails even though the pass rate meets the threshold, and says why
    assert not verdict.passed
    assert "could not be graded" in verdict.errors[0]
    assert "says nothing about the agent" in verdict.errors[0]
    assert any("pii: SSN not repeated" in line for line in verdict.errors[1:])
    assert any(GRADER_REASON in line for line in verdict.errors[1:])


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
    assert "::error::1 test case(s) could not be graded" in capsys.readouterr().out
