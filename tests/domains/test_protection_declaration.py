"""Tests for categorized domain-protection declarations."""

import pytest

from qreduce.domains import ProtectionDeclaration


def test_categorized_protection_declaration_exposes_required_and_best_effort_items() -> None:
    """Required categories survive the cap while best-effort incumbents remain distinct."""

    declaration = ProtectionDeclaration(
        mandatory_item_ids=("mandatory",),
        user_locked_item_ids=("locked",),
        safe_retained_item_ids=("safe",),
        incumbent_supported_item_ids=("incumbent",),
        incumbent_protection_mode="best_effort",
    )

    assert declaration.required_item_ids == ("mandatory", "locked", "safe")
    assert declaration.best_effort_item_ids == ("incumbent",)
    assert declaration.to_dict()["incumbent_protection_mode"] == "best_effort"


def test_protection_declaration_rejects_ambiguous_categories_and_unknown_modes() -> None:
    """An adapter cannot issue ambiguous protection precedence."""

    with pytest.raises(ValueError, match="more than one protection category"):
        ProtectionDeclaration(
            mandatory_item_ids=("same",), user_locked_item_ids=("same",)
        )
    with pytest.raises(ValueError, match="required.*best_effort"):
        ProtectionDeclaration(incumbent_protection_mode="optional")
    with pytest.raises(TypeError, match="tuple or list"):
        ProtectionDeclaration(mandatory_item_ids="not-a-sequence")  # type: ignore[arg-type]