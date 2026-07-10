import sys
from pathlib import Path
from unittest.mock import AsyncMock

from fastmcp import Client

from arcpy_mcp_server.app import build_services, create_mcp
from arcpy_mcp_server.config import Settings
from arcpy_mcp_server.models import JobRecord, JobStatus


def make_settings(tmp_path):
    return Settings(
        public_base_url="https://192.168.25.228:8765",
        data_root=tmp_path / "data",
        tls_cert=tmp_path / "server.crt",
        tls_key=tmp_path / "server.key",
        bearer_token="x" * 32,
        artifact_signing_key="k" * 32,
        arcpy_python=Path(sys.executable),
    )


async def test_mcp_lists_stable_tools_and_calls_health(tmp_path):
    settings = make_settings(tmp_path)
    services = build_services(
        settings,
        worker_script=Path("tests/fixtures/fake_worker.py"),
    )
    mcp = create_mcp(settings, services)

    async with Client(mcp) as client:
        tools = {tool.name for tool in await client.list_tools()}
        result = await client.call_tool("health_check")

    assert {
        "health_check",
        "get_capabilities",
        "search_tools",
        "describe_tool",
        "create_upload",
        "get_upload_status",
        "renew_upload",
        "complete_upload",
        "list_artifacts",
        "create_download",
        "delete_artifact",
        "submit_job",
        "get_job",
        "list_jobs",
        "cancel_job",
        "get_job_log",
        "inspect_dataset",
        "buffer_features",
        "clip_features",
        "project_features",
        "dissolve_features",
        "intersect_features",
        "spatial_join",
        "check_geometry",
        "repair_geometry",
        "clip_raster",
        "project_raster",
        "calculate_slope",
        "zonal_statistics",
        "export_map_layout",
        "detect_objects",
        "classify_pixels",
        "classify_objects",
        "detect_change",
    } <= tools
    assert result.data["status"] == "healthy"
    assert result.data["worker"]["worker"] == "fake"


async def test_mcp_artifact_and_catalog_workflow(tmp_path):
    settings = make_settings(tmp_path)
    services = build_services(
        settings,
        worker_script=Path("tests/fixtures/fake_worker.py"),
    )
    mcp = create_mcp(settings, services)

    async with Client(mcp) as client:
        upload = await client.call_tool(
            "create_upload",
            {
                "logical_name": "roads.zip",
                "expected_size": 10,
                "expected_sha256": "a" * 64,
                "media_type": "application/zip",
            },
        )
        described = await client.call_tool(
            "describe_tool", {"tool_id": "vector.buffer"}
        )
        unknown = await client.call_tool(
            "submit_job",
            {"tool_id": "python.eval", "parameters": {}},
            raise_on_error=False,
        )

    assert upload.data["committed_size"] == 0
    assert upload.data["upload_url"].startswith(
        "https://192.168.25.228:8765/artifacts/"
    )
    assert described.data["id"] == "vector.buffer"
    assert unknown.is_error


async def test_clip_features_maps_to_allowlisted_catalog_request(tmp_path):
    settings = make_settings(tmp_path)
    services = build_services(
        settings,
        worker_script=Path("tests/fixtures/fake_worker.py"),
    )
    submitted = JobRecord(
        id="job-1",
        tool_id="vector.clip",
        status=JobStatus.QUEUED,
        request={},
    )
    services.runner.submit = AsyncMock(return_value=submitted)
    mcp = create_mcp(settings, services)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "clip_features",
            {
                "input_artifact_id": "input-1",
                "input_path": "roads.shp",
                "clip_artifact_id": "clip-1",
                "clip_path": "boundary.shp",
                "output_name": "clipped.gdb",
            },
        )

    services.runner.submit.assert_awaited_once_with(
        "vector.clip",
        {
            "input_artifact_id": "input-1",
            "input_path": "roads.shp",
            "clip_artifact_id": "clip-1",
            "clip_path": "boundary.shp",
            "output_name": "clipped.gdb",
        },
    )
    assert result.data["id"] == "job-1"
