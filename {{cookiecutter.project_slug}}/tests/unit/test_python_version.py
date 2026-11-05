"""Unit tests for sending the container's Python version with a code deploy.

The SDK's AgentEngine.update() never sends `python_version`, so an engine created by
OpenTofu (no package_spec) builds on the API default, 3.10, and google-adk 2.x cannot
install there. deployment/python_version.py adds it to the update request.
"""

import sys

from google.cloud.aiplatform_v1.types import ReasoningEngine, ReasoningEngineSpec
from google.cloud.aiplatform_v1.types.reasoning_engine_service import (
    UpdateReasoningEngineRequest,
)
from google.protobuf import field_mask_pb2
from vertexai.agent_engines import _agent_engines as sdk

from deployment.python_version import (
    PYTHON_VERSION_MASK,
    local_python_version,
    sending_python_version,
    with_python_version,
)

PICKLE_MASK = "spec.package_spec.pickle_object_gcs_uri"


def code_update_request() -> UpdateReasoningEngineRequest:
    """What the SDK builds when update() ships an agent: a package_spec, no version."""
    spec = ReasoningEngineSpec(
        package_spec=ReasoningEngineSpec.PackageSpec(
            pickle_object_gcs_uri="gs://bucket/agent/agent_engine.pkl"
        )
    )
    return UpdateReasoningEngineRequest(
        reasoning_engine=ReasoningEngine(name="projects/p/locations/l/x/1", spec=spec),
        update_mask=field_mask_pb2.FieldMask(paths=[PICKLE_MASK]),
    )


def test_local_python_version_is_major_dot_minor():
    expected = f"{sys.version_info.major}.{sys.version_info.minor}"

    assert local_python_version() == expected


def test_with_python_version_adds_the_version_and_its_mask():
    request = with_python_version(code_update_request(), "3.12")

    assert request.reasoning_engine.spec.package_spec.python_version == "3.12"
    assert list(request.update_mask.paths) == [PICKLE_MASK, PYTHON_VERSION_MASK]


def test_with_python_version_leaves_the_original_request_untouched():
    original = code_update_request()

    with_python_version(original, "3.12")

    assert original.reasoning_engine.spec.package_spec.python_version == ""
    assert list(original.update_mask.paths) == [PICKLE_MASK]


def test_with_python_version_ignores_updates_that_ship_no_code():
    """A package_spec without the pickle is rejected by the API, so a request that
    changes only, say, the display name must stay as it is."""
    request = UpdateReasoningEngineRequest(
        reasoning_engine=ReasoningEngine(name="n", display_name="x"),
        update_mask=field_mask_pb2.FieldMask(paths=["display_name"]),
    )

    result = with_python_version(request, "3.12")

    assert list(result.update_mask.paths) == ["display_name"]
    assert result.reasoning_engine.spec.package_spec.python_version == ""


def test_sending_python_version_applies_to_the_sdk_builder_inside_the_block():
    original_builder = sdk._generate_update_request_or_raise
    sdk._generate_update_request_or_raise = lambda **_: code_update_request()
    try:
        with sending_python_version("3.12"):
            request = sdk._generate_update_request_or_raise(
                resource_name="n", staging_bucket="gs://b"
            )
        outside = sdk._generate_update_request_or_raise(
            resource_name="n", staging_bucket="gs://b"
        )
    finally:
        sdk._generate_update_request_or_raise = original_builder

    assert request.reasoning_engine.spec.package_spec.python_version == "3.12"
    assert outside.reasoning_engine.spec.package_spec.python_version == ""


def test_sending_python_version_restores_the_sdk_builder_after_an_error():
    original_builder = sdk._generate_update_request_or_raise

    try:
        with sending_python_version("3.12"):
            raise RuntimeError("deploy failed")
    except RuntimeError:
        pass

    assert sdk._generate_update_request_or_raise is original_builder
