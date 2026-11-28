# Cross-paper synthesis: MIS, market graphs, QUBO/Ising, and quantum-enhanced solvers

This note connects the two bundled literature summaries:

1. **A scalable quantum-enhanced greedy algorithm for maximum independent set problems**
2. **Correlation-diversified portfolio construction by finding maximum independent set in large-scale market graph**

## 1. Shared core abstraction

Both papers revolve around the same combinatorial object: the **Maximum Independent Set (MIS)**.

For a graph `G = (V, E)`:

- vertices represent generic graph nodes in the QAOA paper;
- vertices represent stocks/assets in the market graph paper;
- edges represent graph adjacency in the QAOA paper;
- edges represent sufficiently high correlation in the market graph paper.

The common binary decision is:

```text
δ_i = 1  select vertex/asset i
δ_i = 0  do not select vertex/asset i
```

The feasibility condition is:

```text
δ_i δ_j = 0  for all (i, j) ∈ E
```

The maximum-cardinality objective is:

```text
maximize Σ_i δ_i
```

## 2. Common QUBO structure

A standard MIS QUBO minimization is:

```text
minimize  A Σ_(i,j∈E) δ_i δ_j - B Σ_i δ_i
```

where:

- `A > 0` penalizes invalid adjacent selections;
- `B > 0` rewards selection;
- usually choose `B < A` for this simple cardinality formulation.

The market graph paper uses this directly with `A = 2`, `B = 1`.

The QAOA paper writes a Hamiltonian version:

```text
H_λ = λ Σ_(i,j∈E) N_i N_j - Σ_i N_i
```

where `N_i` plays the same role as a binary selection variable.

In this project, write the binary variable as `δ_i`, and map to Ising spins only when needed:

```text
δ_i = (1 + z_i) / 2
z_i = 2δ_i - 1
```

## 3. Solver roles

The two papers highlight different solver regimes.

### Market graph paper

Uses a **quantum-inspired simulated bifurcation machine** to solve large dense-ish MIS/QUBO instances generated from market correlations.

Strengths:

- practical for thousands of stocks;
- fast on specialized FPGA hardware;
- directly tied to a portfolio backtest;
- compares against NetworkX and OR-tools.

### QAOA-enhanced greedy paper

Uses **QAOA expectation values** to guide a classical greedy algorithm on sparse regular graphs.

Strengths:

- constructive and always feasible;
- scalable for fixed QAOA depth;
- avoids variational training via fixed tree angles;
- demonstrates hybrid quantum-classical value even when QAOA alone is weak.

## 4. Implication for QIS portfolio optimization

A practical project architecture can combine insights from both:

1. **Data layer**
   - ingest asset prices;
   - compute log returns;
   - estimate correlations and volatilities.

2. **Graph layer**
   - build market graph with threshold `θ`;
   - optionally sparsify or constrain graph degree if a QAOA-greedy method is desired.

3. **Optimization layer**
   - define `δ_select[i]` binary variables;
   - formulate MIS QUBO/Ising model;
   - solve with classical heuristics, exact solvers for small instances, simulated annealing, quantum annealing, simulated bifurcation, or QAOA-enhanced greedy.

4. **Portfolio layer**
   - convert selected assets into continuous weights `x_weights[i]`;
   - evaluate EW, IVW, or other allocation methods;
   - include turnover and transaction costs.

5. **Validation layer**
   - check independent-set feasibility;
   - measure selected-set size;
   - compute risk/return/Sharpe;
   - compare with baselines;
   - inspect factor tilts.

## 5. Important modeling distinction

MIS portfolio selection maximizes **number of low-correlation assets**, not directly Sharpe ratio or mean-variance utility.

Therefore, MIS can be used as:

- a diversification filter;
- a candidate subset generator;
- a constraint component in a richer portfolio optimizer;
- a first-stage selection method before continuous allocation.

If the project later integrates expected returns, risk models, sector constraints, or cardinality constraints, the model may move beyond pure MIS into a richer QUBO/CQM/MIQP formulation.

## 6. When to use which paper

Use `mis-market-graph-portfolio.md` when the task is about:

- asset correlations;
- market graph construction;
- QUBO formulation for portfolio selection;
- threshold search;
- backtesting MIS portfolio strategies;
- EW/IVW allocation;
- simulated bifurcation.

Use `qaoa-enhanced-greedy-mis.md` when the task is about:

- QAOA;
- hybrid quantum-classical greedy algorithms;
- local expectation values;
- light-cone subgraphs;
- fixed QAOA angles;
- quantum hardware/noise;
- sparse graph MIS heuristics.

Use this cross-paper synthesis when designing project architecture or comparing solver approaches.

## 7. Suggested naming in code

Follow project variable conventions:

```python
# continuous portfolio weights
x_weights = ...

# binary selected/not-selected asset variables
δ_select = ...

# Ising spin encoding
z_spin = 2 * δ_select - 1

# inverse map
δ_select = (1 + z_spin) / 2
```

If ASCII-only identifiers are required in code, use explicit comments:

```python
delta_select = ...  # δ_select ∈ {0, 1}
z_spin = 2 * delta_select - 1  # z_spin ∈ {-1, +1}
x_weights = ...  # continuous portfolio weights
```

## 8. Risk and research caveats

- Historical backtest performance is not a guarantee of future performance.
- Market graph construction is sensitive to correlation windows and threshold `θ`.
- MIS selection can introduce unintended factor exposures.
- Sparse-regular graph QAOA results do not automatically transfer to dense financial market graphs.
- Quantum or quantum-inspired solvers should be benchmarked against simple heuristics and robust baselines.
