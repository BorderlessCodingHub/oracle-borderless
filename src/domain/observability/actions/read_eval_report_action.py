from src.support.observability.eval_report_store import EvalReportStore


class ReadEvalReportAction:
    """Leitura do último report (e histórico) do harness de eval para a página de ops."""

    def __init__(self, store=None) -> None:
        self.store = store or EvalReportStore()

    async def execute(self) -> dict:
        report = self.store.read()
        if report is None:
            return {"status": "no_runs", "report": None, "history": []}
        return {"status": "ok", "report": report, "history": self.store.history()}
