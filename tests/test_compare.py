from decimal import Decimal

from evaluation.compare import cell_f1, results_match


def test_identical():
    assert results_match([("a", 1)], [("a", 1)])


def test_row_order_ignored_by_default():
    assert results_match([("a",), ("b",)], [("b",), ("a",)])


def test_row_order_enforced_when_ordered():
    assert not results_match([("a",), ("b",)], [("b",), ("a",)], ordered=True)
    assert results_match([("a",), ("b",)], [("a",), ("b",)], ordered=True)


def test_ordered_tolerates_swaps_inside_a_tie_only():
    gold = [("A", 9), ("B", 5), ("C", 5), ("D", 1)]
    assert results_match(gold, [("A", 9), ("C", 5), ("B", 5), ("D", 1)], ordered=True)
    assert not results_match(gold, [("B", 5), ("A", 9), ("C", 5), ("D", 1)], ordered=True)


def test_ordered_without_numbers_is_strict():
    assert not results_match([("x",), ("y",)], [("y",), ("x",)], ordered=True)


def test_column_order_ignored():
    assert results_match([("a", 1), ("b", 2)], [(1, "a"), (2, "b")])


def test_column_alignment_is_per_row_not_per_column():
    # Same column value-sets, but the pairing is wrong -> must not match.
    assert not results_match([("a", 1), ("b", 2)], [("a", 2), ("b", 1)])


def test_numeric_types_and_float_noise():
    assert results_match([(Decimal("3.0"),)], [(3,)])
    assert results_match([(0.30000000004,)], [(0.3,)])


def test_whitespace_normalised_case_preserved():
    assert results_match([("a  b",)], [("a b",)])
    assert not results_match([("A",)], [("a",)])


def test_null_handling():
    assert results_match([(None, 1)], [(1, None)])


def test_row_count_mismatch():
    assert not results_match([("a",)], [("a",), ("a",)])


def test_extra_column_only_in_relaxed():
    assert not results_match([("P1",)], [("P1", "NAME")])
    assert results_match([("P1",)], [("P1", "NAME")], relaxed=True)


def test_relaxed_still_needs_correct_values():
    assert not results_match([("P1",)], [("P2", "NAME")], relaxed=True)


def test_both_empty_match():
    assert results_match([], [])


def test_empty_vs_nonempty():
    assert not results_match([], [(None,)])


def test_duplicates_matter():
    assert not results_match([("a",), ("a",)], [("a",), ("b",)])


def test_cell_f1_partial_credit():
    assert cell_f1([("a", "b")], [("a", "b")]) == 1.0
    assert 0 < cell_f1([("a", "b")], [("a", "c")]) < 1
    assert cell_f1([("a",)], [("z",)]) == 0.0
