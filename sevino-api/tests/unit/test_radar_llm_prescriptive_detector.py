"""The prescriptive-language deny-list (spec §13.4 — labels stay descriptive)."""

import pytest

from app.services.radar_job.llm import (
    PRESCRIPTIVE_TERMS,
    find_prescriptive_terms,
)


@pytest.mark.parametrize("term", PRESCRIPTIVE_TERMS)
def test_every_denied_term_is_flagged(term):
    assert find_prescriptive_terms(f"Some context {term} more context") == [term]


@pytest.mark.parametrize("term", PRESCRIPTIVE_TERMS)
def test_detection_is_case_insensitive(term):
    assert find_prescriptive_terms(f"PREFIX {term.upper()} SUFFIX") == [term]


@pytest.mark.parametrize(
    "label",
    [
        "Great buying opportunity",  # "buy" inside "buying"
        "Analysts are selling fast",  # "sell" inside "selling"
        "Recommended by many funds",  # "recommend" inside "recommended"
    ],
)
def test_inflections_are_flagged(label):
    assert find_prescriptive_terms(label)


@pytest.mark.parametrize(
    "label",
    [
        "Major chipmaker in a sector you don't currently own",
        "Reports earnings Thursday — second-largest US bank",
        "Largest US homebuilder by revenue",
        "Pays a 3% dividend; reports next week",
    ],
)
def test_descriptive_labels_pass(label):
    assert find_prescriptive_terms(label) == []


def test_multiple_terms_all_returned():
    terms = find_prescriptive_terms("You should buy this and we like it")
    assert set(terms) == {"should", "buy", "we like"}
