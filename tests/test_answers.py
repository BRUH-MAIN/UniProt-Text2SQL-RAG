from evaluation.answers import answer_metrics, value_recall


def test_recall_counts_gold_values_present():
    assert value_recall("TP53 is P04637.", [["P04637"], ["TP53"]]) == 1.0
    assert value_recall("It is P04637.", [["P04637"], ["TP53"]]) == 0.5
    assert value_recall("Nothing relevant.", [["P04637"]]) == 0.0


def test_numbers_ignore_commas_and_float_rendering():
    assert value_recall("There are 12,000 proteins.", [[12000.0]]) == 1.0


def test_recall_undefined_for_empty_gold():
    assert value_recall("none", []) is None


def test_limits_and_empty_honesty():
    long = "word " * 120
    assert not answer_metrics(long, [["x"]])["within_limit"]
    assert answer_metrics("No toxic doses are recorded.", [])["empty_ok"] is True
    assert answer_metrics("The dose is 5 mg.", [])["empty_ok"] is False
    assert answer_metrics("anything", [["x"]])["empty_ok"] is None
