"""Bootstrap da aplicação FastAPI: cria o app, registra middlewares, handlers e rotas."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.app.api.exception_handlers import register_exception_handlers
from src.app.api.middlewares import (
    BackgroundTaskMiddleware,
    DBSessionMiddleware,
    ProcessTimeMiddleware,
    RequestContextMiddleware,
)
from src.app.api.routes import register_routes
from src.support.core.lifespan import lifespan
from src.support.core.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # Middlewares — add_middleware empilha em ordem inversa de execução.
    # Execução desejada: RequestContext → DBSession → BackgroundTask → ProcessTime.
    app.add_middleware(ProcessTimeMiddleware)
    app.add_middleware(BackgroundTaskMiddleware)
    app.add_middleware(DBSessionMiddleware)
    app.add_middleware(RequestContextMiddleware)

    # CORS: só quando SPA e API ficam em hosts distintos (CORS_ORIGINS
    # preenchido). Vazio = mesmo origin/proxy do Vite em dev, sem middleware.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,  # cookie SameSite=Lax exige mesmo host; sem credentials cross-origin (ADR-0018)
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    register_exception_handlers(app)
    register_routes(app)

    return app


app = create_app()
