"""Tests for the public unified pipeline surface."""

from qreduce import pipeline
from qreduce.pipeline.unified import PipelineRunResult


def test_only_run_pipeline_is_a_public_execution_entry_point() -> None:
    """Legacy execution wrappers and first-round compatibility accessors are absent."""

    assert callable(pipeline.run_pipeline)
    assert "run_pipeline" in pipeline.__all__
    assert "run_single_pass" not in pipeline.__all__
    assert "run_multi_round" not in pipeline.__all__
    assert not hasattr(pipeline, "run_single_pass")
    assert not hasattr(pipeline, "run_multi_round")

    for attribute in (
        "retained_item_ids",
        "fixing_manifest",
        "selected_mis_samples",
        "candidate_records",
        "candidate_domain_item_records",
        "mis_compilation_result",
        "mis_execution_result",
    ):
        assert not hasattr(PipelineRunResult, attribute)