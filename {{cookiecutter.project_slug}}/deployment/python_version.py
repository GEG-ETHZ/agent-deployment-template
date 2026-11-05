"""Send the container's Python version with every code deploy.

The engine is created by OpenTofu (infra/agent) without a package, so it has no Python
version yet, and the API falls back to 3.10 when the first code arrives. The SDK's
AgentEngine.update() never sends `python_version` -- only create() does -- and the API
rejects a package_spec that carries a version without the pickle, so OpenTofu cannot set
it either. The one request that can is the code update itself.

`sending_python_version` wraps the SDK's request builder, which update() calls by module
name, for the duration of one deploy: the SDK still validates, packages and uploads as
usual, and its request gains the version and the matching update-mask path. The builder
is private, so uv.lock pins the SDK and tests/unit/test_python_version.py covers it.
"""

import sys
from collections.abc import Iterator
from contextlib import contextmanager

from google.cloud.aiplatform_v1.types.reasoning_engine_service import (
    UpdateReasoningEngineRequest,
)

PYTHON_VERSION_MASK = "spec.package_spec.python_version"
# Present only when the update ships code; a version without it is rejected by the API.
PICKLE_MASK = "spec.package_spec.pickle_object_gcs_uri"


def local_python_version() -> str:
    """The Python the agent is pickled with, as the API wants it: major.minor."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def with_python_version(
    request: UpdateReasoningEngineRequest, python_version: str
) -> UpdateReasoningEngineRequest:
    """A copy of `request` that also sets the package's Python version.

    Requests that ship no code are returned as an unchanged copy.
    """
    updated = UpdateReasoningEngineRequest()
    UpdateReasoningEngineRequest.copy_from(updated, request)
    if PICKLE_MASK not in updated.update_mask.paths:
        return updated
    updated.reasoning_engine.spec.package_spec.python_version = python_version
    updated.update_mask.paths.append(PYTHON_VERSION_MASK)
    return updated


@contextmanager
def sending_python_version(python_version: str) -> Iterator[None]:
    """Make the SDK's update() send `python_version` while the block runs."""
    from vertexai.agent_engines import _agent_engines as sdk

    original = sdk._generate_update_request_or_raise

    def generate(**kwargs) -> UpdateReasoningEngineRequest:
        return with_python_version(original(**kwargs), python_version)

    sdk._generate_update_request_or_raise = generate
    try:
        yield
    finally:
        sdk._generate_update_request_or_raise = original
