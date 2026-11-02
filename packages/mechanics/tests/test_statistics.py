import math

import pytest

from polymech_mechanics.errors import InsufficientDataError
from polymech_mechanics.statistics import summarize


def test_summary_matches_hand_calculation() -> None:
    s = summarize([1.0, 2.0, 3.0])
    assert s.mean == pytest.approx(2.0)
    assert s.std == pytest.approx(1.0)
    assert s.sem == pytest.approx(1 / math.sqrt(3))
    half = 4.302652729911275 / math.sqrt(3)  # t(0.975, 2)
    assert s.ci95_low == pytest.approx(2 - half)
    assert s.ci95_high == pytest.approx(2 + half)
    assert s.cv == pytest.approx(0.5)


def test_single_value_has_no_spread() -> None:
    s = summarize([4.0])
    assert s.n == 1 and s.mean == 4.0 and math.isnan(s.std)


def test_empty_rejected() -> None:
    with pytest.raises(InsufficientDataError):
        summarize([])
