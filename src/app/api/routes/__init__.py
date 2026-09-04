"""Autodiscovery de rotas.

Cada módulo em `src/app/api/routes/` que expõe uma variável `router` ou
`public_router` é registrado automaticamente — basta criar o arquivo, nada a
registrar manualmente. A distinção não é mais só convenção: a exigência de
`require_user` é **mecânica** (ADR-0017/0018, fail-closed). `register_routes`
inclui todo `router` com `dependencies=[Depends(require_user)]` amarrado na
hora do `include_router` — um módulo novo que esqueça de proteger sua rota sai
protegido mesmo assim. `public_router` é incluído como está, sem essa
dependency extra: só use `public_router` para o que precisa mesmo ficar sem
auth (hoje: `/health` e `POST /auth/login`).

Um router que já declara sua própria auth (`require_user` ou `require_admin`,
que depende dele) não paga o preço em duplicidade: o FastAPI cacheia o
resultado de uma dependency por request (`use_cache`, o default), então o
`require_user` amarrado aqui e o já declarado no módulo resolvem para a mesma
chamada.
"""

import importlib
import logging
import pkgutil

from fastapi import APIRouter, Depends, FastAPI

from src.app.api.dependencies.require_user import require_user

logger = logging.getLogger(__name__)


def _include_module_routers(app: FastAPI, module, module_name: str = "<module>") -> None:
    """Inclui os routers de UM módulo já importado. Extraído de `register_routes`
    só para dar um ponto de entrada testável sem depender do pacote real de
    rotas (testes exercitam isto com um módulo fake e afirmam que `router`
    sai protegido mecanicamente, sem reimplementar o autodiscovery inteiro)."""
    public_router = getattr(module, "public_router", None)
    if isinstance(public_router, APIRouter):
        app.include_router(public_router)
        logger.info("Rota registrada: %s.public_router", module_name)

    router = getattr(module, "router", None)
    if isinstance(router, APIRouter):
        app.include_router(router, dependencies=[Depends(require_user)])
        logger.info("Rota registrada: %s.router (auth mecânica)", module_name)


def register_routes(app: FastAPI) -> None:
    """Descobre e inclui todos os routers dos módulos deste pacote."""
    package = importlib.import_module(__name__)

    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_"):
            continue

        module = importlib.import_module(f"{__name__}.{module_info.name}")
        _include_module_routers(app, module, module_info.name)
