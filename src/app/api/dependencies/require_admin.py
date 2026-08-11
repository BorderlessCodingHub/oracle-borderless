"""Encaixe único da auth de admin da página de ops."""


async def require_admin() -> None:
    """HOJE: no-op — a página está aberta por decisão da dona do produto, enquanto a
    auth do ecossistema não está definida (ver CLAUDE.md, "pontos em aberto").

    QUANDO A AUTH CHEGAR: validar aqui a identidade (hoje o e-mail chega por
    `Cf-Access-Authenticated-User-Email`, sem validação) e, para quem não for admin,
    levantar `NotFoundError` — que o exception_handlers traduz para **404**. Não usar
    403: a página de ops não deve nem revelar que existe. O lado do frontend é
    `useCurrentUser().isAdmin`, que decide se a rota é montada.
    """
    return None
