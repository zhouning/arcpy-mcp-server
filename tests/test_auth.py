import time

import pytest

from arcpy_mcp_server.auth import ArtifactSigner, StaticBearerVerifier


@pytest.mark.asyncio
async def test_static_bearer_verifier_accepts_only_exact_token():
    verifier = StaticBearerVerifier("x" * 32, "https://192.168.25.228:8765")

    accepted = await verifier.verify_token("x" * 32)
    rejected = await verifier.verify_token("x" * 31 + "y")

    assert accepted is not None
    assert accepted.client_id == "codex-macos"
    assert rejected is None


def test_artifact_signature_binds_operation_and_expiry():
    signer = ArtifactSigner(b"k" * 32)
    expires = int(time.time()) + 60
    signature = signer.sign("upload", "artifact-1", expires)

    assert signer.verify("upload", "artifact-1", expires, signature)
    assert not signer.verify("download", "artifact-1", expires, signature)
    assert not signer.verify("upload", "artifact-1", int(time.time()) - 1, signature)
