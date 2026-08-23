"""Statistical honesty checks.

The whole point of this module is to refuse to call a hot streak an edge, so
the tests are mostly about it staying sceptical when the record looks good.
"""

import pytest

from edgelord import evidence


class TestBreakeven:
    def test_standard_juice(self):
        assert evidence.BREAKEVEN == pytest.approx(0.5238, abs=1e-4)


class TestWilson:
    def test_small_sample_is_wide(self):
        lo, hi = evidence.wilson_interval(6, 10)
        assert lo < 0.35 and hi > 0.80

    def test_large_sample_is_tight(self):
        lo, hi = evidence.wilson_interval(600, 1000)
        assert hi - lo < 0.07

    def test_contains_the_point_estimate(self):
        lo, hi = evidence.wilson_interval(44, 73)
        assert lo < 44 / 73 < hi

    def test_empty_is_maximally_uncertain(self):
        assert evidence.wilson_interval(0, 0) == (0.0, 1.0)


class TestBinomialTail:
    def test_coin_flip_half(self):
        # P(X >= 5) for 10 flips at p=0.5 is 0.623
        assert evidence.binomial_tail(5, 10, 0.5) == pytest.approx(0.623, abs=1e-3)

    def test_all_wins_is_improbable(self):
        assert evidence.binomial_tail(20, 20, 0.5) == pytest.approx(0.5**20)

    def test_a_hot_44_of_73_is_not_significant(self):
        """60% over 73 plays feels convincing and is not."""
        p = evidence.binomial_tail(44, 73, evidence.BREAKEVEN)
        assert p > 0.05

    def test_same_rate_over_a_big_sample_is_significant(self):
        p = evidence.binomial_tail(600, 1000, evidence.BREAKEVEN)
        assert p < 0.001


class TestSampleSize:
    def test_detecting_55_percent_needs_thousands(self):
        n = evidence.plays_to_detect(0.55)
        assert 1500 < n < 3500

    def test_bigger_edge_needs_fewer_plays(self):
        assert evidence.plays_to_detect(0.60) < evidence.plays_to_detect(0.55)

    def test_no_edge_needs_nothing(self):
        assert evidence.plays_to_detect(0.50) == 0


class TestClvEvidence:
    def test_too_few_plays(self):
        out = evidence._clv_evidence([0.5])
        assert out["significant"] is False

    def test_consistent_positive_clv_is_significant(self):
        out = evidence._clv_evidence([0.5, 0.6, 0.4, 0.5, 0.55, 0.45] * 10)
        assert out["significant"] is True
        assert out["mean"] > 0

    def test_noisy_clv_around_zero_is_not(self):
        out = evidence._clv_evidence([1.0, -1.0, 0.5, -0.5, 2.0, -2.0] * 5)
        assert out["significant"] is False

    def test_negative_clv_is_never_significant_evidence_of_edge(self):
        out = evidence._clv_evidence([-0.5] * 40)
        assert out["mean"] < 0
        # z is strongly negative, so the one-sided test does not fire.
        assert out["significant"] is False


class TestDiscrimination:
    def _rows(self, pairs):
        return [
            {"confidence": c, "pick_result": r, "clv_points": None,
             "profit_units": 0, "pick_type": "spread"}
            for c, r in pairs
        ]

    def test_needs_enough_plays(self):
        out = evidence._discrimination(self._rows([(60, "win")] * 10))
        assert out["measurable"] is False

    def test_detects_a_real_signal(self):
        pairs = [(50, "loss")] * 15 + [(70, "win")] * 15
        out = evidence._discrimination(self._rows(pairs))
        assert out["informative"] is True
        assert out["spread"] > 0.5

    def test_detects_a_useless_signal(self):
        pairs = [(50, "win"), (70, "loss")] * 15
        out = evidence._discrimination(self._rows(pairs))
        assert out["informative"] is False


class TestVerdict:
    def test_thresholds(self):
        assert evidence._verdict(0) == "no signal yet"
        assert evidence._verdict(30) == "early, unproven"
        assert evidence._verdict(50) == "promising"
        assert evidence._verdict(80) == "established"
