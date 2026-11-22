"""Parametric pulse strategies for Pasqal neutral-atom MIS solving.

This module defines pulse sequence strategies that replace the naive
constant pulse with physically-motivated annealing schedules. The key
insight is that MIS on neutral atoms requires an adiabatic-like evolution:

1. Start with all atoms in ground state (detuning >> Rabi frequency)
2. Gradually turn on interactions (ramp up Rabi frequency)
3. Cross the quantum phase transition (detuning crosses zero)
4. End in the classical MIS manifold (detuning >> 0, atoms in |r> or |g>)

The strategies are designed to be:
- Versioned for reproducibility
- Parameterized for tuning
- Compatible with Pulser's AnalogDevice constraints
- Transparent about their limitations (MIS, not weighted MIS)

Reference:
- Pasqal MWIS tutorial: https://docs.pasqal.com/pulser/tutorials/mwis/
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from qreduce.artifacts.metadata import redact_metadata, to_primitive


class PulseStrategyId(StrEnum):
    """Identifier for pulse sequence strategies."""

    CONSTANT = "constant"  # Original naive constant pulse
    LINEAR_SWEEP = "linear_sweep"  # Simple linear annealing
    SMOOTHED_ANNEALING = "smoothed_annealing"  # Smooth ramps, no sudden jumps


@dataclass(frozen=True, slots=True)
class PulseStrategyConfig:
    """Configuration for a pulse sequence strategy.

    All times are in nanoseconds, frequencies in rad/µs.

    Attributes:
        strategy_id: Identifier for the pulse strategy.
        strategy_version: Version number for reproducibility.
        total_duration_ns: Total pulse duration in nanoseconds.
        max_amplitude_rad_per_us: Maximum Rabi frequency (Ω_max).
        initial_detuning_rad_per_us: Starting detuning (negative = ground state favored).
        final_detuning_rad_per_us: Ending detuning (positive = Rydberg state favored).
        ramp_up_fraction: Fraction of duration for amplitude ramp-up.
        ramp_down_fraction: Fraction of duration for amplitude ramp-down.
        additional_parameters: Strategy-specific parameters.
    """

    strategy_id: PulseStrategyId
    strategy_version: int
    total_duration_ns: int
    max_amplitude_rad_per_us: float
    initial_detuning_rad_per_us: float
    final_detuning_rad_per_us: float
    ramp_up_fraction: float = 0.15
    ramp_down_fraction: float = 0.15
    additional_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate basic constraints
        if self.total_duration_ns <= 0:
            raise ValueError("total_duration_ns must be positive")
        if self.max_amplitude_rad_per_us <= 0:
            raise ValueError("max_amplitude_rad_per_us must be positive")
        if not 0 <= self.ramp_up_fraction <= 0.5:
            raise ValueError("ramp_up_fraction must be in [0, 0.5]")
        if not 0 <= self.ramp_down_fraction <= 0.5:
            raise ValueError("ramp_down_fraction must be in [0, 0.5]")
        if self.ramp_up_fraction + self.ramp_down_fraction > 1:
            raise ValueError("ramp fractions must sum to at most 1")

        object.__setattr__(
            self,
            "additional_parameters",
            MappingProxyType(dict(self.additional_parameters)),
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def default_smoothed_annealing_config() -> PulseStrategyConfig:
    """Return the default smoothed annealing configuration.

    This configuration is designed for small MIS instances (up to 12 atoms)
    on Pasqal's AnalogDevice. The parameters are conservative defaults
    that should work for most cases but may not be optimal.

    The schedule follows the adiabatic MIS protocol:
    - Duration: 4000 ns (4 µs) - sufficient for adiabatic evolution
    - Amplitude: Ramps from 0 to 10 rad/µs (within AnalogDevice limits)
    - Detuning: Sweeps from -10 to +10 rad/µs (crosses the transition)
    - Ramps: 15% each for smooth amplitude envelope

    Returns:
        PulseStrategyConfig with smoothed annealing parameters.
    """
    return PulseStrategyConfig(
        strategy_id=PulseStrategyId.SMOOTHED_ANNEALING,
        strategy_version=1,
        total_duration_ns=4000,  # 4 µs
        max_amplitude_rad_per_us=10.0,  # Within AnalogDevice limits
        initial_detuning_rad_per_us=-10.0,  # Start favoring ground state
        final_detuning_rad_per_us=10.0,  # End favoring Rydberg state
        ramp_up_fraction=0.15,
        ramp_down_fraction=0.15,
        additional_parameters={
            "description": "Default smoothed annealing for MIS",
            "target_device": "AnalogDevice",
        },
    )


def default_linear_sweep_config() -> PulseStrategyConfig:
    """Return a simple linear sweep configuration.

    This is a minimal annealing schedule with linear ramps. It's simpler
    than smoothed annealing but may have worse adiabatic properties.

    Returns:
        PulseStrategyConfig with linear sweep parameters.
    """
    return PulseStrategyConfig(
        strategy_id=PulseStrategyId.LINEAR_SWEEP,
        strategy_version=1,
        total_duration_ns=3000,  # 3 µs
        max_amplitude_rad_per_us=8.0,
        initial_detuning_rad_per_us=-8.0,
        final_detuning_rad_per_us=8.0,
        ramp_up_fraction=0.1,
        ramp_down_fraction=0.1,
        additional_parameters={
            "description": "Simple linear sweep for MIS",
            "target_device": "AnalogDevice",
        },
    )


def legacy_constant_config() -> PulseStrategyConfig:
    """Return the legacy constant pulse configuration.

    This recreates the original constant pulse behavior for backward
    compatibility and comparison benchmarks. It is NOT recommended
    for production use as it does not perform proper annealing.

    Returns:
        PulseStrategyConfig matching the original constant pulse.
    """
    return PulseStrategyConfig(
        strategy_id=PulseStrategyId.CONSTANT,
        strategy_version=1,
        total_duration_ns=1000,  # Original 1 µs
        max_amplitude_rad_per_us=1.0,  # Original value
        initial_detuning_rad_per_us=1.0,  # Constant (no sweep)
        final_detuning_rad_per_us=1.0,  # Constant (no sweep)
        ramp_up_fraction=0.0,  # No ramps (constant)
        ramp_down_fraction=0.0,
        additional_parameters={
            "description": "Legacy constant pulse (not recommended)",
            "target_device": "AnalogDevice",
            "warning": "This configuration does not perform proper annealing",
        },
    )


def build_pulse_sequence(
    config: PulseStrategyConfig,
    register: Any,
    device: Any,
) -> Any:
    """Build a Pulser Sequence from a pulse strategy configuration.

    This function constructs the actual Pulser Sequence object with
    the specified pulse strategy applied to the global Rydberg channel.

    Args:
        config: The pulse strategy configuration.
        register: A Pulser Register with atom positions.
        device: The Pulser Device to validate against.

    Returns:
        A Pulser Sequence ready for simulation or execution.

    Raises:
        ImportError: If Pulser is not available.
        ValueError: If the configuration is incompatible with the device.
    """
    from pulser import Pulse, Sequence
    from pulser.waveforms import InterpolatedWaveform

    # Validate device compatibility
    # Device limits are on channels, not the device object directly
    channel_obj = device.channels.get("rydberg_global")
    if channel_obj is not None:
        max_amp = getattr(channel_obj, "max_amp", None)
        if max_amp is not None and config.max_amplitude_rad_per_us > max_amp:
            raise ValueError(
                f"Amplitude {config.max_amplitude_rad_per_us} exceeds device limit {max_amp}"
            )

    seq = Sequence(register, device)
    seq.declare_channel("global", "rydberg_global")

    duration = config.total_duration_ns

    if config.strategy_id == PulseStrategyId.CONSTANT:
        # Legacy constant pulse
        pulse = Pulse.ConstantPulse(
            duration,
            config.max_amplitude_rad_per_us,
            config.final_detuning_rad_per_us,  # Use final as the constant value
            0.0,  # No phase
        )
        seq.add(pulse, "global")

    elif config.strategy_id in (
        PulseStrategyId.LINEAR_SWEEP,
        PulseStrategyId.SMOOTHED_ANNEALING,
    ):
        # InterpolatedWaveform times must be normalized to [0, 1]
        ramp_up_frac = config.ramp_up_fraction
        ramp_down_frac = config.ramp_down_fraction
        plateau_end_frac = 1.0 - ramp_down_frac

        # Build amplitude waveform: 0 -> max -> max -> 0 (times normalized to [0, 1])
        amp_times = [0.0, ramp_up_frac, plateau_end_frac, 1.0]
        amp_values = [0.0, config.max_amplitude_rad_per_us, config.max_amplitude_rad_per_us, 0.0]

        # Build detuning waveform: initial -> final (linear sweep, times normalized)
        det_times = [0.0, 1.0]
        det_values = [config.initial_detuning_rad_per_us, config.final_detuning_rad_per_us]

        # Create interpolated waveforms
        amplitude_wf = InterpolatedWaveform(duration, amp_values, times=amp_times)
        detuning_wf = InterpolatedWaveform(duration, det_values, times=det_times)

        pulse = Pulse(amplitude_wf, detuning_wf, 0.0)
        seq.add(pulse, "global")

    else:
        raise ValueError(f"Unknown pulse strategy: {config.strategy_id}")

    return seq


@dataclass(frozen=True, slots=True)
class PulseStrategyDiagnostics:
    """Diagnostics about a pulse strategy's physical properties.

    This captures information about how well the pulse strategy
    matches the physical requirements for MIS solving.
    """

    strategy_id: PulseStrategyId
    strategy_version: int

    # Timing metrics
    total_duration_ns: int
    adiabatic_ratio: float | None  # T / T_adiabatic estimate

    # Energy scale metrics
    max_interaction_energy: float | None  # C6/r^6 for closest pair
    detuning_range: float  # |final - initial| detuning
    amplitude_to_interaction_ratio: float | None  # Ω/U comparison

    # Warnings
    warnings: tuple[str, ...] = ()

    # Validation
    device_compatible: bool | None = None
    validation_message: str | None = None

    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(
            self, "provenance", MappingProxyType(dict(self.provenance))
        )

    def to_dict(self) -> dict[str, object]:
        return redact_metadata(to_primitive(self))  # type: ignore[return-value]


def diagnose_pulse_strategy(
    config: PulseStrategyConfig,
    *,
    min_distance_um: float | None = None,
    c6_coefficient: float = 862690.0,  # Default C6 for Rb
) -> PulseStrategyDiagnostics:
    """Analyze a pulse strategy configuration for physical consistency.

    Args:
        config: The pulse strategy to analyze.
        min_distance_um: Minimum inter-atom distance in micrometers.
        c6_coefficient: Van der Waals C6 coefficient in rad·µs·µm^6.

    Returns:
        PulseStrategyDiagnostics with analysis results.
    """
    warnings = []

    # Calculate interaction energy if distance is known
    max_interaction = None
    amp_to_int_ratio = None

    if min_distance_um is not None and min_distance_um > 0:
        # U = C6 / r^6 in rad/µs
        max_interaction = c6_coefficient / (min_distance_um**6)
        amp_to_int_ratio = config.max_amplitude_rad_per_us / max_interaction

        # Check if amplitude is comparable to interaction
        if amp_to_int_ratio < 0.1:
            warnings.append(
                f"Amplitude ({config.max_amplitude_rad_per_us:.1f}) much smaller "
                f"than interaction ({max_interaction:.1f}); may not drive transitions"
            )
        elif amp_to_int_ratio > 10:
            warnings.append(
                f"Amplitude ({config.max_amplitude_rad_per_us:.1f}) much larger "
                f"than interaction ({max_interaction:.1f}); may cause unwanted excitations"
            )

    # Check detuning range
    detuning_range = abs(config.final_detuning_rad_per_us - config.initial_detuning_rad_per_us)
    if detuning_range < 2 * config.max_amplitude_rad_per_us:
        warnings.append(
            f"Detuning range ({detuning_range:.1f}) smaller than 2*amplitude; "
            "may not fully traverse the phase transition"
        )

    # Estimate adiabatic ratio (very rough)
    # T_adiabatic ~ hbar * N / gap^2, but gap depends on problem
    # Use a heuristic: T should be >> 1/Omega for adiabatic
    duration_us = config.total_duration_ns / 1000.0
    adiabatic_ratio = duration_us * config.max_amplitude_rad_per_us if config.max_amplitude_rad_per_us > 0 else None

    if adiabatic_ratio is not None and adiabatic_ratio < 10:
        warnings.append(
            f"Short duration may not be adiabatic (T*Ω = {adiabatic_ratio:.1f} < 10)"
        )

    # Check for constant pulse warning
    if config.strategy_id == PulseStrategyId.CONSTANT:
        warnings.append(
            "Constant pulse does not perform annealing; "
            "results may be suboptimal for MIS"
        )

    return PulseStrategyDiagnostics(
        strategy_id=config.strategy_id,
        strategy_version=config.strategy_version,
        total_duration_ns=config.total_duration_ns,
        adiabatic_ratio=adiabatic_ratio,
        max_interaction_energy=max_interaction,
        detuning_range=detuning_range,
        amplitude_to_interaction_ratio=amp_to_int_ratio,
        warnings=tuple(warnings),
        device_compatible=None,  # Device compatibility requires sequence construction.
        provenance={
            "min_distance_um": min_distance_um,
            "c6_coefficient": c6_coefficient,
        },
    )
