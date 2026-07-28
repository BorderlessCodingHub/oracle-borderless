from src.app.console.commands.knowledge_calibrate_command import format_row


def test_marks_rows_below_the_threshold_as_passing():
    assert format_row(0.31, "o que é o bootcamp?", "Web3", 0.55).startswith("PASSA")


def test_marks_rows_above_the_threshold_as_refused():
    assert format_row(0.81, "capital da Austrália?", "Módulo", 0.55).startswith("RECUSA")


def test_row_shows_distance_with_three_decimals():
    assert "0.310" in format_row(0.31, "q", "t", 0.55)
