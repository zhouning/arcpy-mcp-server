from dataclasses import dataclass

from fastmcp import FastMCP

from .artifacts import ArtifactService
from .catalog import ToolCatalog
from .jobs import InvalidTransition, JobRunner, JobService
from .models import ArtifactState
from .worker_supervisor import WorkerSupervisor


@dataclass
class ToolServices:
    artifacts: ArtifactService
    catalog: ToolCatalog
    jobs: JobService
    runner: JobRunner
    supervisor: WorkerSupervisor
    public_base_url: str


def _artifact(record):
    return record.model_dump(mode="json", exclude={"storage_path", "content_root"})


def _job(record):
    return record.model_dump(mode="json")


def register_tools(mcp: FastMCP, services: ToolServices) -> None:
    @mcp.tool()
    async def health_check() -> dict:
        """Return gateway and ArcPy worker health."""
        return {
            "status": "healthy" if services.supervisor.pid else "degraded",
            "worker": services.supervisor.capabilities,
        }

    @mcp.tool()
    async def get_capabilities() -> dict:
        """Return ArcGIS worker capabilities and allowlisted categories."""
        return {
            "worker": services.supervisor.capabilities,
            "categories": sorted(
                {tool.category for tool in services.catalog.tools.values()}
            ),
            "tool_count": len(services.catalog.tools),
        }

    @mcp.tool()
    async def search_tools(query: str, category: str | None = None) -> list[dict]:
        """Search the allowlisted ArcPy catalog."""
        return [
            tool.model_dump(mode="json")
            for tool in services.catalog.search(query, category)
        ]

    @mcp.tool()
    async def describe_tool(tool_id: str) -> dict:
        """Describe one allowlisted ArcPy tool and its JSON Schema."""
        return services.catalog.describe(tool_id).model_dump(mode="json")

    @mcp.tool()
    async def create_upload(
        logical_name: str,
        expected_size: int,
        expected_sha256: str,
        media_type: str,
    ) -> dict:
        """Create a resumable artifact upload session."""
        record = await services.artifacts.create_upload(
            logical_name,
            expected_size,
            expected_sha256,
            media_type,
        )
        return {
            **_artifact(record),
            "upload_url": services.artifacts.signed_url(
                services.public_base_url,
                record.id,
                "upload",
                600,
            ),
        }

    @mcp.tool()
    async def get_upload_status(artifact_id: str) -> dict:
        """Return the server-confirmed committed upload offset."""
        return _artifact(
            await services.artifacts.get_upload_status(artifact_id)
        )

    @mcp.tool()
    async def renew_upload(artifact_id: str) -> dict:
        """Issue a fresh signed URL for an incomplete upload."""
        record = await services.artifacts.get_upload_status(artifact_id)
        if record.state is not ArtifactState.INCOMPLETE:
            raise ValueError("artifact is not an incomplete upload")
        return {
            "artifact_id": artifact_id,
            "committed_size": record.committed_size,
            "upload_url": services.artifacts.signed_url(
                services.public_base_url,
                artifact_id,
                "upload",
                600,
            ),
        }

    @mcp.tool()
    async def complete_upload(artifact_id: str) -> dict:
        """Verify size and SHA-256, then make an upload ready."""
        return _artifact(
            await services.artifacts.complete_upload(artifact_id)
        )

    @mcp.tool()
    async def list_artifacts() -> list[dict]:
        """List non-deleted artifacts."""
        return [
            _artifact(record)
            for record in await services.artifacts.list_artifacts()
        ]

    @mcp.tool()
    async def create_download(artifact_id: str) -> dict:
        """Issue a resumable signed download URL for a ready artifact."""
        record = await services.artifacts.get_upload_status(artifact_id)
        if record.state is not ArtifactState.READY:
            raise ValueError("artifact is not ready")
        return {
            **_artifact(record),
            "download_url": services.artifacts.signed_url(
                services.public_base_url,
                artifact_id,
                "download",
                600,
            ),
        }

    @mcp.tool()
    async def delete_artifact(artifact_id: str) -> dict:
        """Delete an artifact that is not protected by an active job."""
        if await services.artifacts.db.artifact_has_active_job(artifact_id):
            raise ValueError("artifact is referenced by an active job")
        return _artifact(
            await services.artifacts.delete_artifact(artifact_id)
        )

    @mcp.tool()
    async def submit_job(tool_id: str, parameters: dict) -> dict:
        """Submit one validated allowlisted ArcPy job."""
        return _job(await services.runner.submit(tool_id, parameters))

    @mcp.tool()
    async def get_job(job_id: str) -> dict:
        """Return one job status and sanitized result."""
        return _job(await services.jobs.get(job_id))

    @mcp.tool()
    async def list_jobs(limit: int = 100) -> list[dict]:
        """List recent ArcPy jobs."""
        return [
            _job(record)
            for record in await services.jobs.list_jobs(limit)
        ]

    @mcp.tool()
    async def cancel_job(job_id: str) -> dict:
        """Cancel a queued or currently running ArcPy job."""
        try:
            return _job(await services.runner.cancel(job_id))
        except InvalidTransition as error:
            raise ValueError(str(error)) from error

    @mcp.tool()
    async def get_job_log(job_id: str) -> list[dict]:
        """Return sanitized append-only job events."""
        return await services.jobs.events(job_id)

    async def submit_dedicated(tool_id: str, parameters: dict) -> dict:
        return _job(await services.runner.submit(tool_id, parameters))

    @mcp.tool()
    async def inspect_dataset(
        input_artifact_id: str, input_path: str
    ) -> dict:
        """Inspect an uploaded GIS dataset."""
        return await submit_dedicated(
            "inspect.dataset",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
            },
        )

    @mcp.tool()
    async def buffer_features(
        input_artifact_id: str,
        input_path: str,
        output_name: str,
        distance: str,
        dissolve_option: str = "NONE",
    ) -> dict:
        """Submit an ArcPy Buffer job."""
        return await submit_dedicated(
            "vector.buffer",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "output_name": output_name,
                "distance": distance,
                "dissolve_option": dissolve_option,
            },
        )

    @mcp.tool()
    async def clip_features(
        input_artifact_id: str,
        input_path: str,
        clip_artifact_id: str,
        clip_path: str,
        output_name: str,
    ) -> dict:
        """Clip uploaded features by an uploaded polygon dataset."""
        return await submit_dedicated(
            "vector.clip",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "clip_artifact_id": clip_artifact_id,
                "clip_path": clip_path,
                "output_name": output_name,
            },
        )

    @mcp.tool()
    async def project_features(
        input_artifact_id: str,
        input_path: str,
        output_name: str,
        output_spatial_reference: int | str,
        geographic_transform: str | None = None,
    ) -> dict:
        """Project uploaded features into another spatial reference."""
        parameters = {
            "input_artifact_id": input_artifact_id,
            "input_path": input_path,
            "output_name": output_name,
            "output_spatial_reference": output_spatial_reference,
        }
        if geographic_transform is not None:
            parameters["geographic_transform"] = geographic_transform
        return await submit_dedicated("vector.project", parameters)

    @mcp.tool()
    async def dissolve_features(
        input_artifact_id: str,
        input_path: str,
        output_name: str,
        dissolve_fields: list[str] | None = None,
    ) -> dict:
        """Dissolve uploaded features by optional attribute fields."""
        parameters = {
            "input_artifact_id": input_artifact_id,
            "input_path": input_path,
            "output_name": output_name,
        }
        if dissolve_fields is not None:
            parameters["dissolve_fields"] = dissolve_fields
        return await submit_dedicated("vector.dissolve", parameters)

    @mcp.tool()
    async def intersect_features(
        inputs: list[dict[str, str]],
        output_name: str,
        join_attributes: str = "ALL",
    ) -> dict:
        """Intersect multiple uploaded feature datasets."""
        return await submit_dedicated(
            "vector.intersect",
            {
                "inputs": inputs,
                "output_name": output_name,
                "join_attributes": join_attributes,
            },
        )

    @mcp.tool()
    async def spatial_join(
        target_artifact_id: str,
        target_path: str,
        join_artifact_id: str,
        join_path: str,
        output_name: str,
        join_operation: str = "JOIN_ONE_TO_ONE",
        match_option: str = "INTERSECT",
    ) -> dict:
        """Join uploaded features using a spatial relationship."""
        return await submit_dedicated(
            "vector.spatial_join",
            {
                "target_artifact_id": target_artifact_id,
                "target_path": target_path,
                "join_artifact_id": join_artifact_id,
                "join_path": join_path,
                "output_name": output_name,
                "join_operation": join_operation,
                "match_option": match_option,
            },
        )

    @mcp.tool()
    async def check_geometry(
        input_artifact_id: str,
        input_path: str,
        output_name: str,
        validation_method: str = "ESRI",
    ) -> dict:
        """Create a table of geometry defects."""
        return await submit_dedicated(
            "vector.check_geometry",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "output_name": output_name,
                "validation_method": validation_method,
            },
        )

    @mcp.tool()
    async def repair_geometry(
        input_artifact_id: str,
        input_path: str,
        output_name: str,
        delete_null: str = "DELETE_NULL",
        validation_method: str = "ESRI",
    ) -> dict:
        """Copy uploaded features and repair geometry defects."""
        return await submit_dedicated(
            "vector.repair_geometry",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "output_name": output_name,
                "delete_null": delete_null,
                "validation_method": validation_method,
            },
        )

    @mcp.tool()
    async def clip_raster(
        input_artifact_id: str,
        input_path: str,
        template_artifact_id: str,
        template_path: str,
        output_name: str,
        clipping_geometry: bool = True,
    ) -> dict:
        """Clip an uploaded raster with an uploaded template dataset."""
        return await submit_dedicated(
            "raster.clip",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "template_artifact_id": template_artifact_id,
                "template_path": template_path,
                "output_name": output_name,
                "clipping_geometry": clipping_geometry,
            },
        )

    @mcp.tool()
    async def project_raster(
        input_artifact_id: str,
        input_path: str,
        output_name: str,
        output_spatial_reference: int | str,
        resampling_type: str = "NEAREST",
        cell_size: float | None = None,
    ) -> dict:
        """Project an uploaded raster into another spatial reference."""
        parameters = {
            "input_artifact_id": input_artifact_id,
            "input_path": input_path,
            "output_name": output_name,
            "output_spatial_reference": output_spatial_reference,
            "resampling_type": resampling_type,
        }
        if cell_size is not None:
            parameters["cell_size"] = cell_size
        return await submit_dedicated("raster.project", parameters)

    @mcp.tool()
    async def calculate_slope(
        input_artifact_id: str,
        input_path: str,
        output_name: str,
        output_measurement: str = "DEGREE",
        z_factor: float = 1.0,
    ) -> dict:
        """Submit an ArcPy Spatial Analyst Slope job."""
        return await submit_dedicated(
            "raster.slope",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "output_name": output_name,
                "output_measurement": output_measurement,
                "z_factor": z_factor,
            },
        )

    @mcp.tool()
    async def zonal_statistics(
        zone_artifact_id: str,
        zone_path: str,
        zone_field: str,
        value_artifact_id: str,
        value_path: str,
        output_name: str,
        statistics_type: str = "ALL",
    ) -> dict:
        """Summarize uploaded raster values by uploaded zones."""
        return await submit_dedicated(
            "raster.zonal_statistics",
            {
                "zone_artifact_id": zone_artifact_id,
                "zone_path": zone_path,
                "zone_field": zone_field,
                "value_artifact_id": value_artifact_id,
                "value_path": value_path,
                "output_name": output_name,
                "statistics_type": statistics_type,
            },
        )

    @mcp.tool()
    async def export_map_layout(
        input_artifact_id: str,
        aprx_path: str,
        layout_name: str,
        output_name: str,
        format: str,
        dpi: int = 300,
    ) -> dict:
        """Export an exact layout from an uploaded ArcGIS Pro project."""
        return await submit_dedicated(
            "map.export_layout",
            {
                "input_artifact_id": input_artifact_id,
                "aprx_path": aprx_path,
                "layout_name": layout_name,
                "output_name": output_name,
                "format": format,
                "dpi": dpi,
            },
        )

    @mcp.tool()
    async def detect_objects(
        input_artifact_id: str,
        input_path: str,
        model_artifact_id: str,
        model_path: str,
        output_name: str,
        arguments: str = "",
    ) -> dict:
        """Submit CPU ArcGIS Image Analyst object detection."""
        return await submit_dedicated(
            "dl.detect_objects",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "model_artifact_id": model_artifact_id,
                "model_path": model_path,
                "output_name": output_name,
                "arguments": arguments,
            },
        )

    @mcp.tool()
    async def classify_pixels(
        input_artifact_id: str,
        input_path: str,
        model_artifact_id: str,
        model_path: str,
        output_name: str,
        arguments: str = "",
    ) -> dict:
        """Submit CPU ArcGIS Image Analyst pixel classification."""
        return await submit_dedicated(
            "dl.classify_pixels",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "model_artifact_id": model_artifact_id,
                "model_path": model_path,
                "output_name": output_name,
                "arguments": arguments,
            },
        )

    @mcp.tool()
    async def classify_objects(
        input_artifact_id: str,
        input_path: str,
        model_artifact_id: str,
        model_path: str,
        output_name: str,
        arguments: str = "",
    ) -> dict:
        """Submit CPU ArcGIS Image Analyst object classification."""
        return await submit_dedicated(
            "dl.classify_objects",
            {
                "input_artifact_id": input_artifact_id,
                "input_path": input_path,
                "model_artifact_id": model_artifact_id,
                "model_path": model_path,
                "output_name": output_name,
                "arguments": arguments,
            },
        )

    @mcp.tool()
    async def detect_change(
        from_artifact_id: str,
        from_path: str,
        to_artifact_id: str,
        to_path: str,
        model_artifact_id: str,
        model_path: str,
        output_name: str,
        arguments: str = "",
    ) -> dict:
        """Submit CPU deep-learning change detection."""
        return await submit_dedicated(
            "dl.detect_change",
            {
                "from_artifact_id": from_artifact_id,
                "from_path": from_path,
                "to_artifact_id": to_artifact_id,
                "to_path": to_path,
                "model_artifact_id": model_artifact_id,
                "model_path": model_path,
                "output_name": output_name,
                "arguments": arguments,
            },
        )
