from pydantic import BaseModel, ConfigDict, Field


class LessonStatusResponse(BaseModel):
    """Prontidão de uma aula para o mentor (`GET /lessons/{platform_video_id}/status`).

    `chunk_count` sai como `chunkCount` no fio: é o único consumidor deste
    endpoint (a aba Mentor da Platform, em TS/camelCase) e não há convenção de
    `alias_generator` neste repo para reaproveitar — a curva é local a este
    schema.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str
    chunk_count: int = Field(alias="chunkCount")

    @classmethod
    def from_action_result(cls, result: dict) -> "LessonStatusResponse":
        return cls(status=result["status"], chunkCount=result["chunkCount"])
