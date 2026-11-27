"""Compatibility tests for the Sharpe benchmark configuration."""

from inspect import Parameter, signature

from qreduce.experiments.portfolio_sr.benchmark import BenchmarkConfig


def test_lower_bound_preserves_benchmark_positional_arguments() -> None:
    legacy_args = ("prices.csv", 50, None, None, "log", 0.7, None, 10)

    default_config = BenchmarkConfig(*legacy_args)
    minimum_config = BenchmarkConfig(*legacy_args, lower_bound=0.05)

    for config in (default_config, minimum_config):
        assert config.upper_bound == 0.7
        assert config.sector_constraints is None
        assert config.max_positions == 10
    assert default_config.lower_bound == 0.0
    assert minimum_config.lower_bound == 0.05
    assert signature(BenchmarkConfig).parameters["lower_bound"].kind == Parameter.KEYWORD_ONLY