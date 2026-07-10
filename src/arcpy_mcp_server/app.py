import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import __version__
from .artifacts import ArtifactService, artifact_routes
from .auth import ArtifactSigner, StaticBearerVerifier
from .catalog import ToolCatalog
from .config import Settings
from .db import Database
from .jobs import JobRunner, JobService
from .mcp_tools import ToolServices, register_tools
from .worker_supervisor import WorkerSupervisor
from .workspace import Workspace


LOGGER = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    database: Database
    workspace: Workspace
    artifacts: ArtifactService
    catalog: ToolCatalog
    supervisor: WorkerSupervisor
    jobs: JobService
    runner: JobRunner


def build_services(
    settings: Settings,
    *,
    worker_script: Path | None = None,
) -> Services:
    database = Database(settings.database_path)
    workspace = Workspace(
        settings.data_root,
        settings.max_expanded_bytes,
        settings.max_zip_entries,
        settings.max_zip_depth,
    )
    artifacts = ArtifactService(
        database,
        settings.data_root / "artifacts",
        workspace,
        ArtifactSigner(
            settings.artifact_signing_key.get_secret_value().encode()
        ),
        settings.max_upload_bytes,
    )
    catalog = ToolCatalog.load(
        Path(__file__).parents[2] / "config" / "tool_catalog.yaml"
    )
    supervisor = WorkerSupervisor(
        settings.arcpy_python,
        worker_script or settings.worker_script,
    )
    jobs = JobService(database)
    runner = JobRunner(
        jobs,
        database,
        catalog,
        artifacts,
        workspace,
        supervisor,
    )
    return Services(
        settings,
        database,
        workspace,
        artifacts,
        catalog,
        supervisor,
        jobs,
        runner,
    )


def create_mcp(settings: Settings, services: Services) -> FastMCP:
    async def clean_artifacts() -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                await services.artifacts.cleanup_expired(
                    settings.retention_days,
                    settings.incomplete_upload_hours,
                )
            except Exception:
                LOGGER.exception("artifact retention cleanup failed")

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict]:
        await services.database.start()
        await services.jobs.reconcile_after_restart()
        await services.runner.start()
        await services.artifacts.cleanup_expired(
            settings.retention_days,
            settings.incomplete_upload_hours,
        )
        cleanup_task = asyncio.create_task(clean_artifacts())
        try:
            yield {"services": services}
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            await services.runner.stop()
            await services.database.stop()

    verifier = StaticBearerVerifier(
        settings.bearer_token.get_secret_value(),
        str(settings.public_base_url),
    )
    mcp = FastMCP(
        "ArcPy MCP",
        version=__version__,
        auth=verifier,
        lifespan=lifespan,
        strict_input_validation=True,
        mask_error_details=True,
    )
    register_tools(
        mcp,
        ToolServices(
            services.artifacts,
            services.catalog,
            services.jobs,
            services.runner,
            services.supervisor,
            str(settings.public_base_url).rstrip("/"),
        ),
    )
    return mcp


async def healthz(request: Request) -> JSONResponse:
    services: Services = request.app.state.services
    return JSONResponse(
        {
            "status": (
                "healthy" if services.supervisor.pid else "degraded"
            ),
            "version": __version__,
        }
    )


def create_application(settings: Settings, services: Services):
    mcp = create_mcp(settings, services)
    app = mcp.http_app(
        path="/mcp",
        stateless_http=True,
        json_response=True,
    )
    app.state.services = services
    app.state.artifact_service = services.artifacts
    app.routes.extend(
        [Route("/healthz", healthz, methods=["GET"])]
        + artifact_routes()
    )
    return app
