from agent.grounding import check_grounding


def test_grounded_count():
    assert check_grounding("There are 12,000 proteins.", "How many proteins?", [(12000,)]).ok


def test_float_rendering_does_not_cause_false_alarm():
    assert check_grounding("The average is 620.", "avg?", [(620.0,)]).ok


def test_invented_number_is_flagged():
    g = check_grounding("There are 13000 proteins.", "How many proteins?", [(12000,)])
    assert g.ungrounded_numbers == ["13000"] and not g.ok


def test_number_from_question_is_allowed():
    assert check_grounding("Proteins longer than 5000 residues: 26.", "longer than 5000?", [(26,)]).ok


def test_row_count_is_allowed():
    assert check_grounding("Three accessions: A0A0C5B5G6, P62945, Q8IVG9.", "short?",
                           [("A0A0C5B5G6",), ("P62945",), ("Q8IVG9",)]).ok


def test_invented_accession_is_flagged():
    g = check_grounding("It is P12345.", "which?", [("P04637",)])
    assert g.ungrounded_accessions == ["P12345"]


def test_empty_result_must_be_acknowledged():
    assert check_grounding("No toxic doses are recorded.", "toxic doses?", []).ok
    assert not check_grounding("The toxic dose is 5 mg.", "toxic doses?", []).ok


def test_list_numbering_is_not_a_claim():
    answer = "Top 3:\n1. P42858 - 849\n2) Q8TBB1 - 778\n(3) A8MQ03 - 499"
    rows = [("P42858", 849), ("Q8TBB1", 778), ("A8MQ03", 499)]
    assert check_grounding(answer, "top 3?", rows).ok


def test_numbers_in_the_middle_of_a_line_are_still_checked():
    assert not check_grounding("Rank 2 has 5000 hits.", "q?", [(849,)]).ok


def test_derived_numbers_are_flagged_conservatively():
    g = check_grounding("There are 403 proteins without a function.", "q?", [(11597,)])
    assert g.ungrounded_numbers == ["403"]


def test_evidence_starting_with_a_decimal_is_not_mangled():
    assert check_grounding("The mean is 15.5.", "mean?", [(15.5,)]).ok
