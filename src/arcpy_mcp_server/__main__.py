import uvicorn

from .app import build_services, create_application
from .config import Settings


def main() -> None:
    settings = Settings()
    if not settings.tls_cert.is_file() or not settings.tls_key.is_file():
        raise SystemExit(
            "TLS certificate and key are required before startup"
        )
    services = build_services(settings)
    app = create_application(settings, services)
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.bind_port,
        ssl_certfile=str(settings.tls_cert),
        ssl_keyfile=str(settings.tls_key),
    )


if __name__ == "__main__":
    main()
