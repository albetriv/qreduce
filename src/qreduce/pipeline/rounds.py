"""Round-level invariants shared by iterative reduction orchestration."""

from qreduce.domains import FixingManifest


def validate_round_manifest(
    input_item_ids: tuple[str, ...], manifest: FixingManifest, round_index: int
) -> None:
    """Validate that a manifest partitions precisely the current round domain."""
    if not isinstance(round_index, int) or isinstance(round_index, bool) or round_index < 0:
        raise ValueError("round_index must be a non-negative integer.")
    if len(set(input_item_ids)) != len(input_item_ids):
        raise ValueError("Input domain items must be unique.")
    if manifest.round_index != round_index:
        raise ValueError("Manifest round index does not match the current round.")
    if set(manifest.retained_item_ids) | set(manifest.excluded_item_ids) != set(input_item_ids):
        raise ValueError("Manifest must partition exactly the input domain.")


def validate_manifest_sequence(
    original_item_ids: tuple[str, ...], manifests: tuple[FixingManifest, ...]
) -> tuple[str, ...]:
    """Validate monotonic round partitions and return the final retained domain."""
    current = tuple(original_item_ids)
    if len(set(current)) != len(current):
        raise ValueError("Original domain items must be unique.")
    for index, manifest in enumerate(manifests):
        validate_round_manifest(current, manifest, index)
        current = manifest.retained_item_ids
    return current


def cumulative_fixing_manifest(
    original_item_ids: tuple[str, ...], manifests: tuple[FixingManifest, ...]
) -> FixingManifest:
    """Merge validated round fixings without losing the individual entries.

    Callers must retain the original manifests for round-level provenance.
    Conflicting assignments to a shared variable are rejected.
    """
    if not manifests:
        raise ValueError("At least one round manifest is required.")
    retained = validate_manifest_sequence(original_item_ids, manifests)
    entries = tuple(entry for manifest in manifests for entry in manifest.entries)
    assignments: dict[str, float] = {}
    for entry in entries:
        for variable, value in entry.variable_values.items():
            if variable in assignments and assignments[variable] != value:
                raise ValueError(f"Conflicting cumulative fixing for variable {variable!r}.")
            assignments[variable] = value
    excluded_set = set(original_item_ids) - set(retained)
    return FixingManifest(
        retained_item_ids=retained,
        excluded_item_ids=tuple(item for item in original_item_ids if item in excluded_set),
        entries=entries,
        origin="cumulative_round_fixings",
        round_index=manifests[-1].round_index,
        provenance={"round_count": len(manifests)},
    )