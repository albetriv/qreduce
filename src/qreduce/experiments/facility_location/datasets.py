"""Whitespace-token parser for numeric OR-Library capacitated instances."""

from hashlib import sha256
from pathlib import Path

from .models import FacilityLocationProblem

# Fingerprints identify the exact locally acquired files, not their filenames.
REFERENCE_BY_SHA256 = {
    "31fa9f6ad3c684c66392f0ad5dfa3dcd0262a404ea02a79238f9a1200071358e": ("cap41", 1040444.375),
    "fa065519070061e3eb897b5b91e22e053cc6a15e76297906294a56d90cfba27e": ("cap42", 1098000.450),
    "a19afbd39576615f9ecc69f1a4667c80ddb77878c09a656db9500e39763a8e46": ("cap43", 1153000.450),
    "d0ee030dbdc08e3d5f57cfc3337c546d85635b4ea9e14507bab91590696c3279": ("cap44", 1235500.450),
}


def identify_reference(data: bytes) -> dict[str, object] | None:
    reference = REFERENCE_BY_SHA256.get(sha256(data).hexdigest())
    if reference is None:
        return None
    return {"instance_id": reference[0], "objective": reference[1], "published_decimals": 3,
            "source": "https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/capopt.txt"}


def parse_or_library(text: str) -> FacilityLocationProblem:
    tokens = text.split()
    if any(token.lower() == "capacity" for token in tokens):
        raise ValueError("Capacity placeholders in capa, capb and capc are unsupported.")
    try:
        if len(tokens) < 2:
            raise ValueError("Missing dimensions")
        m, n = int(tokens[0]), int(tokens[1])
        if m <= 0 or n <= 0:
            raise ValueError("Dimensions must be positive")
        if len(tokens) != 2 + 2 * m + n * (m + 1):
            raise ValueError("Truncated instance or unexpected extra tokens")
        values = [float(token) for token in tokens[2:]]
        capacities = tuple(values[2 * i] for i in range(m))
        fixed = tuple(values[2 * i + 1] for i in range(m))
        offset = 2 * m
        demands = tuple(values[offset + j * (m + 1)] for j in range(n))
        costs = tuple(tuple(values[offset + j * (m + 1) + 1:offset + (j + 1) * (m + 1)]) for j in range(n))
        return FacilityLocationProblem(capacities, fixed, demands, costs)
    except (ValueError, OverflowError) as error:
        raise ValueError(f"Invalid OR-Library instance: {error}") from error


def load_or_library(path: str | Path) -> FacilityLocationProblem:
    return parse_or_library(Path(path).read_text(encoding="ascii"))