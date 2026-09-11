from src.support.clients.borderless.borderless_navigation_client import NavigationResult


class FakeNavigationClient:
    """`results` por destination id: NavigationResult ou Exception a lançar.
    `catalog`: lista de entradas ou Exception."""

    def __init__(self, results: dict, catalog=None) -> None:
        self._results = results
        self._catalog = catalog
        self.calls: list[dict] = []

    async def resolve(self, access_token, destination, topic=None, goal=None) -> NavigationResult:
        self.calls.append({"op": "resolve", "token": access_token, "destination": destination, "topic": topic, "goal": goal})
        outcome = self._results.get(destination)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            raise KeyError(f"sem resultado fake para {destination}")
        return outcome

    async def catalog(self, access_token) -> list[dict]:
        self.calls.append({"op": "catalog", "token": access_token})
        if isinstance(self._catalog, Exception):
            raise self._catalog
        return list(self._catalog or [])
