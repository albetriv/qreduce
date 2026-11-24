"""Test custom layout generation with real Pulser and no cloud connection."""

from dataclasses import replace
from time import perf_counter

import pytest

from qreduce.mwis.graph import ReductionGraph
from qreduce.solving.mwis.pasqal_custom_layout import generate_custom_layout


@pytest.fixture
def path_graph():
    edges = (("a", "b"), ("b", "c"))
    return ReductionGraph(("b", "a", "c"), {"a": 1, "b": 2, "c": 3}, edges,
                          dict.fromkeys(edges, "test"), "test", "1")


@pytest.mark.parametrize("trap_count", [12, 24])
def test_generates_reproducible_layout_for_different_device_limits(path_graph, trap_count):
    from pulser.devices import AnalogDevice

    device = replace(AnalogDevice, min_layout_traps=trap_count, max_layout_traps=trap_count,
                     max_atom_num=trap_count // 2, pre_calibrated_layouts=())
    kwargs = dict(radius=10, margin=1, deadline=None)
    first = generate_custom_layout(path_graph, device, **kwargs)
    second = generate_custom_layout(path_graph, device, **kwargs)
    assert first.details == second.details
    assert first.register is not None
    assert first.details["trap_count"] == trap_count
    assert tuple(first.details["assignment"]) == path_graph.node_ids
    device.validate_register(first.register)


def test_generation_budget_records_rejected_candidates(path_graph, monkeypatch):
    from pulser import Register
    from pulser.devices import AnalogDevice

    def reject(*args, **kwargs):
        raise RuntimeError("Cannot place empty traps")

    monkeypatch.setattr(Register, "with_automatic_layout", reject)
    result = generate_custom_layout(path_graph, AnalogDevice, radius=10, margin=1,
                                    deadline=None, attempts=5)
    assert result.register is None
    assert result.details["outcome"] == "budget_exceeded"
    assert result.details["attempts_used"] == 5
    assert result.details["rejected_candidates"]["layout_generation:RuntimeError"] > 0


def test_expired_deadline_stops_before_any_attempt(path_graph):
    from pulser.devices import AnalogDevice

    result = generate_custom_layout(path_graph, AnalogDevice, radius=10, margin=1,
                                    deadline=perf_counter() - 1)
    assert result.register is None
    assert result.details["outcome"] == "timeout"
    assert result.details["attempts_used"] == 0