"""Portfolio Sharpe Ratio experiment with real S&P500 data.

This experiment demonstrates QReduce domain reduction on a maximum Sharpe ratio
portfolio optimization problem using real market data from the S&P500 index.

Key features:
- Real historical price data from S&P500 components
- Continuous weights calculated by classical solver (no binary allocation encoding)
- Sharpe ratio as the single financial objective
- Sector diversification via hard constraints (not MWIS penalties)
- Optional cardinality constraint (maximum number of positions)
- MWIS auxiliary problem for domain reduction (distinct from financial objective)

The experiment follows the transformation approach:
    maximize SR(x) = (mu^T * x) / sqrt(x^T * Sigma * x)

Transformed to a convex QP:
    minimize x_scaled^T * Sigma * x_scaled
    subject to mu^T * x_scaled = 1

See README.md for methodological comparison with Mattesi et al. (2024).
"""

from qreduce.experiments.portfolio_sr.adapter import SharpePortfolioAdapter
from qreduce.experiments.portfolio_sr.datasets import (
    SP500Dataset,
    load_sp500_prices,
)
from qreduce.experiments.portfolio_sr.execution import run_sharpe_portfolio_experiment
from qreduce.experiments.portfolio_sr.inputs import (
    SharpePortfolioInputs,
    build_sharpe_portfolio_inputs,
)
from qreduce.experiments.portfolio_sr.models import (
    ReturnConvention,
    SectorConstraints,
    SharpeGraphPolicy,
    SharpePortfolioProblem,
    TransformedSharpeProblem,
)

__all__ = [
    # Models
    "ReturnConvention",
    "SP500Dataset",
    "SectorConstraints",
    "SharpeGraphPolicy",
    # Adapter
    "SharpePortfolioAdapter",
    "SharpePortfolioInputs",
    "SharpePortfolioProblem",
    "TransformedSharpeProblem",
    # Inputs
    "build_sharpe_portfolio_inputs",
    # Datasets
    "load_sp500_prices",
    # Execution
    "run_sharpe_portfolio_experiment",
]
