"""Cookie de sessão do oráculo (ADR-0018, spec §4.4).

HttpOnly (JS não lê), SameSite=Lax (bloqueia POST cross-site — é a proteção
CSRF; exige SPA e API no MESMO host), Secure fora de dev, Max-Age 7 dias.
A plataforma renova a sessão dela conforme o uso (janela deslizante); para o
cookie acompanhar, `GET /auth/me` (todo boot do SPA) o reemite com Max-Age
cheio. Quem expira de verdade é a plataforma.

Leitura, escrita e limpeza vivem SÓ aqui — nome e atributos num lugar único,
senão um cookie setado com um atributo e apagado com outro vira login preso.
"""

from fastapi import Request, Response

from src.support.core.settings import settings

SESSION_COOKIE_NAME = "ob_session"
SESSION_COOKIE_MAX_AGE_S = 7 * 24 * 60 * 60


def _attrs() -> dict:
    return {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": not settings.is_development,
    }


def read_session_cookie(request: Request) -> str | None:
    raw = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    return raw or None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME, value=token, max_age=SESSION_COOKIE_MAX_AGE_S, **_attrs()
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, **_attrs())


def clearing_cookie_headers() -> dict[str, str]:
    """`Set-Cookie` que apaga o cookie, para anexar a uma HTTPException — o 401
    de sessão morta não pode deixar o browser replicando um cookie inútil."""
    probe = Response()
    clear_session_cookie(probe)
    return {"set-cookie": probe.headers["set-cookie"]}
