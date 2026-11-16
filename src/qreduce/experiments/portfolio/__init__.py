"""Repository-internal mean-variance portfolio experiment domain.

The unified entry point for running experiments is `run_portfolio_experiment`.
The execution mode is controlled by the `reduction_policy` parameter:

- `max_reduction_rounds=0`: Classical-only baseline
- `max_reduction_rounds=1`: Single reduction round (default)
- `max_reduction_rounds>1`: Multi-round reduction
"""

from qreduce.experiments.portfolio.adapter import MeanVariancePortfolioAdapter
from qreduce.experiments.portfolio.analysis import (
    SyntheticPortfolioAnalysis,
    load_multi_round_correlation_data,
    load_synthetic_portfolio_analysis,
)
from qreduce.experiments.portfolio.execution import (
    UNIFIED_EXPERIMENT_ID,
    run_portfolio_experiment,
)
from qreduce.experiments.portfolio.generator import (
    default_generation_policy,
)
from qreduce.experiments.portfolio.inputs import (
    DEFAULT_PORTFOLIO_OUTPUT_ROOT,
    SyntheticPortfolioInputs,
    build_synthetic_portfolio_inputs,
    default_graph_policy,
    default_reduction_policy,
)
from qreduce.experiments.portfolio.models import (
    PortfolioGraphPolicy,
    PortfolioProblem,
    PortfolioResidualProblem,
    PortfolioVariableMapping,
    SyntheticPortfolioGenerationPolicy,
)

__all__ = [
    "DEFAULT_PORTFOLIO_OUTPUT_ROOT",
    "UNIFIED_EXPERIMENT_ID",
    "MeanVariancePortfolioAdapter",
    "PortfolioGraphPolicy",
    "PortfolioProblem",
    "PortfolioResidualProblem",
    "PortfolioVariableMapping",
    "SyntheticPortfolioAnalysis",
    "SyntheticPortfolioGenerationPolicy",
    "SyntheticPortfolioInputs",
    "build_synthetic_portfolio_inputs",
    "default_generation_policy",
    "default_graph_policy",
    "default_reduction_policy",
    "load_multi_round_correlation_data",
    "load_synthetic_portfolio_analysis",
    "run_portfolio_experiment",
]