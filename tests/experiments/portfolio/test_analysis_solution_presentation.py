"""Tests for analysis module solution presentation methods."""

import math
from unittest.mock import MagicMock

import pytest

from qreduce.experiments.portfolio.analysis import (
    PortfolioSolutionAnalysis,
    SyntheticPortfolioAnalysis,
)
from qreduce.mwis import ReductionGraph


@pytest.fixture
def mock_graph() -> ReductionGraph:
    """Return a minimal mock graph."""
    return ReductionGraph(
        node_ids=("asset-a", "asset-b", "asset-c"),
        node_weights={"asset-a": 0.9, "asset-b": 0.7, "asset-c": 0.6},
        edges=(),
        edge_reasons={},
        graph_policy_id="test",
        graph_policy_version="1.0",
    )


@pytest.fixture
def mock_artifacts_with_solution() -> MagicMock:
    """Return mock artifacts with classical solution data."""
    artifacts = MagicMock()
    artifacts.result = {
        "classical_result": {
            "variable_values": {
                "delta__asset-a": 1.0,
                "delta__asset-b": 1.0,
                "delta__asset-c": 0.0,
                "x__asset-a": 0.6,
                "x__asset-b": 0.4,
                "x__asset-c": 0.0,
            }
        }
    }
    return artifacts


@pytest.fixture
def analysis_with_solution(mock_artifacts_with_solution, mock_graph) -> SyntheticPortfolioAnalysis:
    """Return analysis object with solution data."""
    return SyntheticPortfolioAnalysis(
        artifacts=mock_artifacts_with_solution,
        graph=mock_graph,
        asset_ids=("asset-a", "asset-b", "asset-c"),
        correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
        correlation_threshold=0.9,
        retained_item_ids=("asset-a", "asset-b"),
    )


@pytest.fixture
def solution_analysis_with_solution(mock_artifacts_with_solution) -> PortfolioSolutionAnalysis:
    """Return PortfolioSolutionAnalysis object with solution data."""
    return PortfolioSolutionAnalysis(
        artifacts=mock_artifacts_with_solution,
        asset_ids=("asset-a", "asset-b", "asset-c"),
        correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
        correlation_threshold=0.9,
        retained_item_ids=("asset-a", "asset-b"),
        lower_bounds={"asset-a": 0.0, "asset-b": 0.0, "asset-c": 0.0},
        upper_bounds={"asset-a": 0.7, "asset-b": 0.7, "asset-c": 0.7},
        min_selected_assets=None,
        max_selected_assets=None,
        is_classical_only=False,
    )


class TestSolutionSelectionRows:
    """Tests for solution_selection_rows method."""

    def test_returns_all_assets(self, analysis_with_solution):
        """Test that all assets are returned."""
        rows = analysis_with_solution.solution_selection_rows()
        assert len(rows) == 3
        assert [r["asset"] for r in rows] == ["asset-a", "asset-b", "asset-c"]

    def test_correctly_identifies_retained(self, analysis_with_solution):
        """Test that retained status is correct."""
        rows = analysis_with_solution.solution_selection_rows()
        rows_by_asset = {r["asset"]: r for r in rows}

        assert rows_by_asset["asset-a"]["retained"] is True
        assert rows_by_asset["asset-b"]["retained"] is True
        assert rows_by_asset["asset-c"]["retained"] is False

    def test_correctly_identifies_selected(self, analysis_with_solution):
        """Test that selected (delta=1) is correct."""
        rows = analysis_with_solution.solution_selection_rows()
        rows_by_asset = {r["asset"]: r for r in rows}

        assert rows_by_asset["asset-a"]["selected"] is True
        assert rows_by_asset["asset-b"]["selected"] is True
        assert rows_by_asset["asset-c"]["selected"] is False

    def test_correctly_identifies_invested(self, analysis_with_solution):
        """Test that invested (weight > 0) is correct."""
        rows = analysis_with_solution.solution_selection_rows()
        rows_by_asset = {r["asset"]: r for r in rows}

        assert rows_by_asset["asset-a"]["invested"] is True
        assert rows_by_asset["asset-b"]["invested"] is True
        assert rows_by_asset["asset-c"]["invested"] is False

    def test_returns_delta_and_weight_values(self, analysis_with_solution):
        """Test that numeric values are returned."""
        rows = analysis_with_solution.solution_selection_rows()
        rows_by_asset = {r["asset"]: r for r in rows}

        assert rows_by_asset["asset-a"]["delta"] == 1.0
        assert rows_by_asset["asset-a"]["weight"] == 0.6
        assert rows_by_asset["asset-b"]["weight"] == 0.4
        assert rows_by_asset["asset-c"]["delta"] == 0.0

    def test_returns_valid_flag(self, analysis_with_solution):
        """Test that valid flag is returned for all rows."""
        rows = analysis_with_solution.solution_selection_rows()
        for row in rows:
            assert "valid" in row
            assert row["valid"] is True

    def test_respects_integrality_tolerance(self, mock_graph):
        """Test that integrality tolerance affects selection classification."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 0.9999,  # Almost 1
                    "delta__asset-b": 0.9,     # Not close to 1
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": 0.3,
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        # Default tolerance: only asset-a should be selected
        rows = analysis.solution_selection_rows(integrality_tolerance=1e-3)
        rows_by_asset = {r["asset"]: r for r in rows}
        assert rows_by_asset["asset-a"]["selected"] is True
        assert rows_by_asset["asset-b"]["selected"] is False

        # Larger tolerance: both asset-a and asset-b should be selected
        rows = analysis.solution_selection_rows(integrality_tolerance=0.2)
        rows_by_asset = {r["asset"]: r for r in rows}
        assert rows_by_asset["asset-a"]["selected"] is True
        assert rows_by_asset["asset-b"]["selected"] is True

    def test_respects_weight_tolerance(self, mock_graph):
        """Test that weight tolerance affects invested classification."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": 1e-9,  # Very small but positive
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        # Default tolerance: asset-b NOT invested
        rows = analysis.solution_selection_rows(weight_tolerance=1e-8)
        rows_by_asset = {r["asset"]: r for r in rows}
        assert rows_by_asset["asset-a"]["invested"] is True
        assert rows_by_asset["asset-b"]["invested"] is False

        # Smaller tolerance: asset-b IS invested
        rows = analysis.solution_selection_rows(weight_tolerance=1e-10)
        rows_by_asset = {r["asset"]: r for r in rows}
        assert rows_by_asset["asset-b"]["invested"] is True

    def test_no_retained_when_none(self, mock_graph):
        """Test that retained is None when no reduction was performed."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,
                    "delta__asset-c": 1.0,
                    "x__asset-a": 0.3,
                    "x__asset-b": 0.3,
                    "x__asset-c": 0.4,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,  # No reduction
        )

        rows = analysis.solution_selection_rows()
        for row in rows:
            assert row["retained"] is None

    def test_returns_empty_when_no_solution(self, mock_graph):
        """Test that empty list is returned when no solution data."""
        artifacts = MagicMock()
        artifacts.result = {}

        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        assert analysis.solution_selection_rows() == []

    def test_selected_but_not_invested(self, mock_graph):
        """Test case where delta=1 but weight=0 (possible when lower_bound=0)."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": 0.0,  # Selected but not invested
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        rows = analysis.solution_selection_rows()
        rows_by_asset = {r["asset"]: r for r in rows}

        # asset-b: selected (delta=1) but not invested (weight=0)
        assert rows_by_asset["asset-b"]["selected"] is True
        assert rows_by_asset["asset-b"]["invested"] is False


class TestSolutionSummary:
    """Tests for solution_summary method."""

    def test_returns_correct_counts(self, analysis_with_solution):
        """Test that summary counts are correct."""
        summary = analysis_with_solution.solution_summary()

        assert summary["total_assets"] == 3
        assert summary["retained_count"] == 2  # asset-a, asset-b
        assert summary["selected_count"] == 2  # delta=1 for a, b
        assert summary["invested_count"] == 2  # weight > 0 for a, b
        assert summary["selected_but_not_invested"] == 0

    def test_total_weight(self, analysis_with_solution):
        """Test that total weight is computed correctly."""
        summary = analysis_with_solution.solution_summary()
        assert abs(summary["total_weight"] - 1.0) < 1e-10  # 0.6 + 0.4

    def test_tolerances_returned(self, analysis_with_solution):
        """Test that tolerances are included in summary."""
        summary = analysis_with_solution.solution_summary(
            integrality_tolerance=1e-4,
            weight_tolerance=1e-6,
        )

        assert summary["tolerances"]["integrality_tolerance"] == 1e-4
        assert summary["tolerances"]["weight_tolerance"] == 1e-6

    def test_selected_but_not_invested_count(self, mock_graph):
        """Test that selected_but_not_invested is computed correctly."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,  # Selected
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": 0.0,  # Not invested
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        summary = analysis.solution_summary()
        assert summary["selected_count"] == 2
        assert summary["invested_count"] == 1
        assert summary["selected_but_not_invested"] == 1

    def test_returns_none_when_no_solution(self, mock_graph):
        """Test that summary returns None values when no solution."""
        artifacts = MagicMock()
        artifacts.result = {}

        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        summary = analysis.solution_summary()
        assert summary["total_assets"] == 3
        assert summary["retained_count"] is None
        assert summary["selected_count"] is None
        assert summary["invested_count"] is None
        assert summary["total_weight"] is None

    def test_no_reduction_retained_count_none(self, mock_graph):
        """Test that retained_count is None when no reduction."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,
                    "delta__asset-c": 1.0,
                    "x__asset-a": 0.3,
                    "x__asset-b": 0.3,
                    "x__asset-c": 0.4,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,  # No reduction
        )

        summary = analysis.solution_summary()
        assert summary["retained_count"] is None
        assert summary["selected_count"] == 3
        assert summary["invested_count"] == 3

    def test_is_complete_and_valid_counts(self, analysis_with_solution):
        """Test that is_complete and valid/invalid counts are returned."""
        summary = analysis_with_solution.solution_summary()

        assert summary["is_complete"] is True
        assert summary["valid_count"] == 3
        assert summary["invalid_count"] == 0


class TestNonFiniteValues:
    """Tests for handling NaN and infinity values."""

    def test_nan_weight_marked_invalid(self, mock_graph):
        """Test that NaN weight is marked as invalid."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": float("nan"),  # NaN weight
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        rows = analysis.solution_selection_rows()
        rows_by_asset = {r["asset"]: r for r in rows}

        assert rows_by_asset["asset-b"]["valid"] is False
        assert rows_by_asset["asset-b"]["selected"] is None
        assert rows_by_asset["asset-b"]["invested"] is None
        # Weight value is preserved for inspection
        assert math.isnan(rows_by_asset["asset-b"]["weight"])

    def test_inf_weight_marked_invalid(self, mock_graph):
        """Test that infinite weight is marked as invalid."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": float("inf"),  # Infinite weight
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        rows = analysis.solution_selection_rows()
        rows_by_asset = {r["asset"]: r for r in rows}

        assert rows_by_asset["asset-b"]["valid"] is False
        assert rows_by_asset["asset-b"]["selected"] is None
        assert rows_by_asset["asset-b"]["invested"] is None

    def test_nan_delta_marked_invalid(self, mock_graph):
        """Test that NaN delta is marked as invalid."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": float("nan"),  # NaN delta
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": 0.3,
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        rows = analysis.solution_selection_rows()
        rows_by_asset = {r["asset"]: r for r in rows}

        assert rows_by_asset["asset-b"]["valid"] is False

    def test_summary_excludes_invalid_from_counts(self, mock_graph):
        """Test that summary counts exclude invalid rows."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": float("nan"),  # Invalid
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        summary = analysis.solution_summary()

        # asset-b is invalid, so not counted
        assert summary["selected_count"] == 1  # Only asset-a
        assert summary["invested_count"] == 1  # Only asset-a
        assert summary["valid_count"] == 2  # asset-a and asset-c
        assert summary["invalid_count"] == 1  # asset-b
        assert summary["is_complete"] is False

    def test_summary_total_weight_ignores_non_finite(self, mock_graph):
        """Test that total_weight ignores non-finite values."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "delta__asset-b": 1.0,
                    "delta__asset-c": 0.0,
                    "x__asset-a": 0.5,
                    "x__asset-b": float("inf"),  # Should be ignored
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=None,
        )

        summary = analysis.solution_summary()
        assert summary["total_weight"] == 0.5  # Only asset-a counted


class TestToleranceValidation:
    """Tests for tolerance parameter validation."""

    def test_nan_integrality_tolerance_raises(self, analysis_with_solution):
        """Test that NaN integrality tolerance raises ValueError."""
        with pytest.raises(ValueError, match="integrality_tolerance"):
            analysis_with_solution.solution_selection_rows(integrality_tolerance=float("nan"))

    def test_inf_integrality_tolerance_raises(self, analysis_with_solution):
        """Test that infinite integrality tolerance raises ValueError."""
        with pytest.raises(ValueError, match="integrality_tolerance"):
            analysis_with_solution.solution_selection_rows(integrality_tolerance=float("inf"))

    def test_negative_integrality_tolerance_raises(self, analysis_with_solution):
        """Test that negative integrality tolerance raises ValueError."""
        with pytest.raises(ValueError, match="integrality_tolerance"):
            analysis_with_solution.solution_selection_rows(integrality_tolerance=-1e-5)

    def test_nan_weight_tolerance_raises(self, analysis_with_solution):
        """Test that NaN weight tolerance raises ValueError."""
        with pytest.raises(ValueError, match="weight_tolerance"):
            analysis_with_solution.solution_selection_rows(weight_tolerance=float("nan"))

    def test_inf_weight_tolerance_raises(self, analysis_with_solution):
        """Test that infinite weight tolerance raises ValueError."""
        with pytest.raises(ValueError, match="weight_tolerance"):
            analysis_with_solution.solution_selection_rows(weight_tolerance=float("inf"))

    def test_negative_weight_tolerance_raises(self, analysis_with_solution):
        """Test that negative weight tolerance raises ValueError."""
        with pytest.raises(ValueError, match="weight_tolerance"):
            analysis_with_solution.solution_selection_rows(weight_tolerance=-1e-8)

    def test_zero_tolerances_accepted(self, analysis_with_solution):
        """Test that zero tolerances are valid."""
        # Should not raise
        rows = analysis_with_solution.solution_selection_rows(
            integrality_tolerance=0.0,
            weight_tolerance=0.0,
        )
        assert len(rows) == 3


class TestPortfolioSolutionAnalysis:
    """Tests for PortfolioSolutionAnalysis (baseline-compatible loader)."""

    def test_baseline_analysis_attributes(self, solution_analysis_with_solution):
        """Test that PortfolioSolutionAnalysis has expected attributes."""
        analysis = solution_analysis_with_solution
        assert analysis.asset_ids == ("asset-a", "asset-b", "asset-c")
        assert analysis.correlation is not None
        assert analysis.correlation_threshold == 0.9
        assert analysis.is_classical_only is False

    def test_solution_selection_rows_works(self, solution_analysis_with_solution):
        """Test that solution_selection_rows works on PortfolioSolutionAnalysis."""
        rows = solution_analysis_with_solution.solution_selection_rows()
        assert len(rows) == 3
        assert all("valid" in row for row in rows)

    def test_solution_summary_works(self, solution_analysis_with_solution):
        """Test that solution_summary works on PortfolioSolutionAnalysis."""
        summary = solution_analysis_with_solution.solution_summary()
        assert summary["total_assets"] == 3
        assert summary["is_complete"] is True

    def test_classical_only_flag(self):
        """Test that is_classical_only is properly set."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {}
            }
        }
        analysis = PortfolioSolutionAnalysis(
            artifacts=artifacts,
            asset_ids=("asset-a",),
            correlation=None,
            correlation_threshold=None,
            retained_item_ids=None,
            lower_bounds=None,
            upper_bounds=None,
            min_selected_assets=None,
            max_selected_assets=None,
            is_classical_only=True,
        )
        assert analysis.is_classical_only is True


class TestRetainedCountIndependence:
    """Tests that retained_count is independent of solution validity."""

    def test_retained_count_with_partial_solution(self, mock_graph):
        """Test that retained_count is correct even when solution is partial."""
        # 2 assets retained, but only 1 has valid solution values
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "x__asset-a": 0.5,
                    # asset-b has no solution values
                    "delta__asset-c": 0.0,
                    "x__asset-c": 0.0,
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=("asset-a", "asset-b"),  # 2 assets in domain
        )

        summary = analysis.solution_summary()

        # retained_count should be 2 (from retained_item_ids), not 1
        assert summary["retained_count"] == 2
        assert summary["is_complete"] is False
        assert summary["invalid_count"] == 1  # asset-b has no values

    def test_retained_count_with_no_solution(self, mock_graph):
        """Test that retained_count is correct even when no solution exists."""
        artifacts = MagicMock()
        artifacts.result = {}  # No classical_result at all

        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=("asset-a", "asset-b"),  # 2 assets in domain
        )

        summary = analysis.solution_summary()

        # retained_count should be 2, even with no solution
        assert summary["retained_count"] == 2
        assert summary["selected_count"] is None
        assert summary["is_complete"] is False

    def test_retained_count_with_all_invalid_values(self, mock_graph):
        """Test that retained_count is correct when all values are invalid."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": float("nan"),
                    "x__asset-a": float("nan"),
                    "delta__asset-b": float("inf"),
                    "x__asset-b": float("inf"),
                    "delta__asset-c": float("nan"),
                    "x__asset-c": float("nan"),
                }
            }
        }
        analysis = SyntheticPortfolioAnalysis(
            artifacts=artifacts,
            graph=mock_graph,
            asset_ids=("asset-a", "asset-b", "asset-c"),
            correlation=((1.0, 0.5, 0.1), (0.5, 1.0, 0.2), (0.1, 0.2, 1.0)),
            correlation_threshold=0.9,
            retained_item_ids=("asset-a", "asset-b", "asset-c"),  # All 3 retained
        )

        summary = analysis.solution_summary()

        # retained_count should be 3, even though all values are invalid
        assert summary["retained_count"] == 3
        assert summary["valid_count"] == 0
        assert summary["invalid_count"] == 3
        assert summary["is_complete"] is False

    def test_portfolio_solution_analysis_retained_count_independence(self):
        """Test PortfolioSolutionAnalysis also has correct retained_count."""
        artifacts = MagicMock()
        artifacts.result = {
            "classical_result": {
                "variable_values": {
                    "delta__asset-a": 1.0,
                    "x__asset-a": 0.5,
                    # asset-b missing
                }
            }
        }
        analysis = PortfolioSolutionAnalysis(
            artifacts=artifacts,
            asset_ids=("asset-a", "asset-b"),
            correlation=None,
            correlation_threshold=None,
            retained_item_ids=("asset-a", "asset-b"),  # 2 retained
            lower_bounds=None,
            upper_bounds=None,
            min_selected_assets=None,
            max_selected_assets=None,
            is_classical_only=False,
        )

        summary = analysis.solution_summary()

        # retained_count = 2, independent of solution validity
        assert summary["retained_count"] == 2
        assert summary["valid_count"] == 1
        assert summary["invalid_count"] == 1


class TestLoaderExperimentIdCompatibility:
    """Tests that load_portfolio_solution_analysis accepts all portfolio experiment IDs."""

    def test_accepts_unified_id(self):
        """Test that 'synthetic-portfolio' ID is accepted."""
        from qreduce.experiments.portfolio.analysis import _ALL_PORTFOLIO_IDS
        assert "synthetic-portfolio" in _ALL_PORTFOLIO_IDS

    def test_accepts_legacy_single_pass_id(self):
        """Test that 'synthetic-portfolio-single-pass' ID is accepted."""
        from qreduce.experiments.portfolio.analysis import _ALL_PORTFOLIO_IDS
        assert "synthetic-portfolio-single-pass" in _ALL_PORTFOLIO_IDS

    def test_accepts_legacy_multi_round_id(self):
        """Test that 'synthetic-portfolio-multi-round' ID is accepted."""
        from qreduce.experiments.portfolio.analysis import _ALL_PORTFOLIO_IDS
        assert "synthetic-portfolio-multi-round" in _ALL_PORTFOLIO_IDS

    def test_all_portfolio_ids_is_union(self):
        """Test that _ALL_PORTFOLIO_IDS contains both single-pass and multi-round IDs."""
        from qreduce.experiments.portfolio.analysis import (
            _ALL_PORTFOLIO_IDS,
            _MULTI_ROUND_COMPATIBLE_IDS,
            _SINGLE_PASS_COMPATIBLE_IDS,
        )
        # Must be the union
        expected = _SINGLE_PASS_COMPATIBLE_IDS | _MULTI_ROUND_COMPATIBLE_IDS
        assert _ALL_PORTFOLIO_IDS == expected

    def test_loader_rejects_unknown_id(self):
        """Test that loader rejects unknown experiment IDs with helpful error."""
        from unittest.mock import MagicMock, patch

        from qreduce.experiments.artifacts import ExperimentArtifactError
        from qreduce.experiments.portfolio.analysis import (
            load_portfolio_solution_analysis,
        )

        # Create mock artifacts with unknown experiment ID
        mock_artifacts = MagicMock()
        mock_artifacts.manifest = {
            "experiment_id": "unknown-experiment",
            "run_id": "test",
        }

        with patch(
            "qreduce.experiments.portfolio.analysis.load_experiment_run",
            return_value=mock_artifacts,
        ), pytest.raises(ExperimentArtifactError) as exc_info:
            load_portfolio_solution_analysis("/fake/path")

        # Error message should mention accepted IDs
        error_msg = str(exc_info.value)
        assert "synthetic-portfolio" in error_msg
        assert "synthetic-portfolio-multi-round" in error_msg


class TestPackageExports:
    """Tests that new analysis classes are exported from the package."""

    def test_portfolio_solution_analysis_exported(self):
        """Test that PortfolioSolutionAnalysis is exported from package."""
        from qreduce.experiments.portfolio import PortfolioSolutionAnalysis
        assert PortfolioSolutionAnalysis is not None

    def test_load_portfolio_solution_analysis_exported(self):
        """Test that load_portfolio_solution_analysis is exported from package."""
        from qreduce.experiments.portfolio import load_portfolio_solution_analysis
        assert callable(load_portfolio_solution_analysis)

    def test_all_exports_in_all_list(self):
        """Test that new exports are in __all__."""
        from qreduce.experiments import portfolio
        assert "PortfolioSolutionAnalysis" in portfolio.__all__
        assert "load_portfolio_solution_analysis" in portfolio.__all__
