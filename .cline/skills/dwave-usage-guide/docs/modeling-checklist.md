# D-Wave Modeling Checklist

Use this checklist before implementing or submitting a D-Wave optimization model.

## Problem Definition

- What is the objective?
- Is it minimization or maximization?
- Which decisions are binary `δ`, continuous `x`, or Ising spin `z`?
- Are constraints hard, soft, or optional?
- What output does the user need?

## Model Choice

- QUBO/BQM: binary variables and quadratic unconstrained objective.
- Ising: spin variables `z ∈ {-1,+1}`.
- CQM: explicit constraints, mixed variable types, industrial optimization.
- DQM: discrete variables with multiple states.

## Validation

- Test a tiny instance.
- Check objective values manually.
- Check feasibility if constraints exist.
- Confirm variable-domain conversions:
  - `δ = (1 + z) / 2`
  - `z = 2δ - 1`

## Solver Selection

- Local sampler for smoke tests.
- Hybrid BQM solver for large unconstrained binary models.
- Hybrid CQM solver for constrained models.
- QPU sampler for quantum annealing experiments and embedding-specific work.
