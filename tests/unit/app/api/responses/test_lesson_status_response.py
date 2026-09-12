from src.app.api.responses.lesson_status_response import LessonStatusResponse


def test_chunk_count_serializes_as_camel_case_on_the_wire():
    """A Platform (TS) espera `chunkCount`, não `chunk_count` — é o contrato
    do endpoint com a aba Mentor."""
    response = LessonStatusResponse.from_action_result({"status": "ready", "chunkCount": 42})

    assert response.model_dump(by_alias=True) == {"status": "ready", "chunkCount": 42}


def test_from_action_result_still_accessible_by_field_name_in_python():
    response = LessonStatusResponse.from_action_result({"status": "unknown", "chunkCount": 0})

    assert response.status == "unknown"
    assert response.chunk_count == 0
