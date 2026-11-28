# Correlation-diversified portfolio construction by finding MIS in large-scale market graph — detailed notes

Source PDF supplied by user:
`/Users/trivellatoa/DATADIR/Manuali/QuantumComputing/CorrelationDiversifiedPortfolioConstructionByFindingMISInLargeScaleMarketGraph.pdf`

Paper title: **Correlation-diversified portfolio construction by finding maximum independent set in large-scale market graph**  
Authors: Ryo Hidaka, Yohei Hamakawa, Jun Nakayama, Kosuke Tatsumura  
Context: quantum-inspired combinatorial optimization / simulated bifurcation / market graph portfolio construction.

## 1. Core idea

The paper constructs diversified equity portfolios by finding **Maximum Independent Sets (MIS)** in **market graphs**.

A market graph is built as follows:

- each stock is a node;
- an undirected edge connects two stocks if their historical correlation is above a threshold `θ`;
- an independent set is a subset of stocks with no pairwise edge between selected stocks;
- therefore, an MIS corresponds to a large group of stocks that are mutually below the correlation threshold.

The key claim is that selecting an MIS from a market graph creates a **correlation-diversified portfolio**.

The paper solves large MIS instances using a quantum-inspired Ising machine based on **Simulated Bifurcation (SB)** and evaluates the resulting strategy with Japanese equity data.

## 2. Market graph construction

For a universe of `N` stocks, define daily log returns:

```text
R_i(t) = ln(P_i(t) / P_i(t-1))
```

The correlation coefficient between stocks `i` and `j` is computed over a lookback window of `T` days:

```text
C_ij = Σ_t (R_i(t) - mean(R_i)) (R_j(t) - mean(R_j))
       / sqrt(Σ_t (R_i(t) - mean(R_i))^2) sqrt(Σ_t (R_j(t) - mean(R_j))^2)
```

A graph edge is added when:

```text
C_ij ≥ θ
```

Interpretation:

- high `θ` creates a sparser graph, because fewer pairs exceed the threshold;
- low `θ` creates a denser graph;
- as `θ` increases, independent sets tend to become larger;
- the choice of `θ` is a strategy parameter with direct impact on diversification and risk/return.

## 3. Portfolio selection via MIS

Using project notation:

```text
δ_i = 1  if stock i is selected
δ_i = 0  otherwise
```

The MIS selection imposes:

```text
δ_i δ_j = 0 for every edge (i, j) ∈ E
```

and maximizes:

```text
Σ_i δ_i
```

That is, select as many stocks as possible while avoiding pairs whose correlation exceeds the threshold.

The paper directly maps the selected MIS stocks into the portfolio constituents.

## 4. Portfolio composition methods

After selecting stocks, the paper studies two allocation schemes.

### 4.1 Equal Weight (EW)

Each selected stock receives equal weight:

```text
x_weight_i = 1 / N_selected
```

In project convention, `x_weight_i` is continuous.

### 4.2 Inverse Volatility Weight (IVW)

Weights are proportional to inverse volatility:

```text
x_weight_i = v_i^{-1} / Σ_k v_k^{-1}
```

where `v_i` is the standard deviation of the stock's daily log returns over the past three years.

Empirically, IVW tends to reduce risk relative to EW in the paper's experiments.

## 5. Monthly rebalancing and transaction costs

The strategy is rebalanced monthly.

At each rebalance date:

1. compute correlations and volatilities using the trailing three-year window;
2. build the market graph using the fixed threshold `θ`;
3. solve MIS;
4. translate the MIS into portfolio constituents;
5. allocate weights by EW or IVW;
6. account for transaction cost of 0.1% of traded amount;
7. compute monthly return.

The monthly portfolio return is computed from portfolio value changes.

## 6. QUBO formulation of MIS

The paper formulates MIS as QUBO.

Original paper notation uses binary variables `b_i`. In this project, use:

```text
δ_i ∈ {0,1}
```

where `δ_i = 1` means node/stock `i` is selected.

The cost function is:

```text
H = H_A + H_B
H_A = A Σ_{i,j} f_ij δ_i δ_j
H_B = -B Σ_i δ_i
```

where:

- `f_ij = 1` if edge `(i,j)` exists, else `0`;
- `H_A` penalizes selecting correlated/adjacent stocks;
- `H_B` rewards selecting more stocks;
- `A` and `B` are positive coefficients;
- the paper uses `A = 2`, `B = 1`;
- the condition `B < A` prevents a constraint-violating pair from being rewarded overall.

This is a minimization problem. Feasible large independent sets have low energy.

## 7. Ising mapping

The QUBO is solved by an Ising machine. Use the project convention:

```text
δ_i = (1 + z_i) / 2
z_i = 2δ_i - 1
```

where `z_i ∈ {-1,+1}` is the spin variable.

When implementing this mapping, carefully derive:

- quadratic couplings between `z_i` and `z_j` from `δ_i δ_j`;
- local fields from both the reward term and expanded penalty terms;
- constant offsets, which do not affect the minimizer but are useful for energy comparison.

## 8. Simulated Bifurcation (SB)

The paper uses **Simulated Bifurcation**, a quantum-inspired heuristic algorithm for Ising optimization.

Key concepts:

- SB numerically simulates nonlinear oscillator dynamics;
- oscillator positions are eventually digitized into spin states;
- ballistic SB (bSB) introduces perfectly inelastic walls at positions `+1` and `-1`;
- the algorithm is highly parallelizable and suitable for FPGA/GPU acceleration.

The authors implement a 2,048-spin fully connected Ising machine on FPGA.

Important hardware/software details:

- look-aside PCIe FPGA accelerator;
- host CPU handles market graph construction and Ising mapping;
- FPGA solves the Ising problem;
- APIs and hardware abstraction layer expose the accelerator to Python/C++ workflows;
- each MIS problem is solved 10 times from different initial states;
- solutions are checked for constraint violations;
- the best feasible solution with largest independent set is selected.

## 9. Solver comparison

The paper compares:

- SB-based MIS solver;
- NetworkX heuristic MIS solver;
- OR-tools exact solver.

Market graph sizes correspond to Japanese stock universes:

- TOPIX 100: about 99 nodes;
- Nikkei 225: about 222 nodes;
- TOPIX 1000: about 952 nodes;
- TOPIX: about 2,026 nodes.

Key results:

- OR-tools times out for 952 nodes and above with a 10-hour limit;
- SB is fastest across tested graph sizes;
- at 2,026 nodes, SB is reported as about 6,230× faster than NetworkX;
- for small instances where exact results are available, SB finds exact or near-exact solutions;
- for larger instances, SB finds independent sets roughly 20% larger than NetworkX in the reported comparison.

## 10. Parameter search and backcast

The paper performs a 10-year backcast from 2013 to 2023 using a TOPIX-based universe of 1,747 stocks.

The search covers:

- 19 threshold values: `θ = 0.18` to `0.36`;
- two allocation methods: EW and IVW;
- 38 total strategy settings;
- 120 monthly rebalance periods;
- 10 SB executions per monthly graph.

Total SB executions reported: 22,800.

As `θ` increases:

- edge density decreases;
- selected independent set size increases;
- portfolio risk generally decreases;
- Sharpe ratio is strong across many settings but peaks at lower-to-moderate thresholds.

The paper selects `θ = 0.23` with IVW as the best strategy under a constraint that the portfolio should contain more than 50 constituents.

## 11. Portfolio performance results

For the best MIS strategy (`θ = 0.23`, IVW), the paper reports:

```text
Annualized return: 16.3%
Annualized risk:   14.0%
Sharpe ratio:      1.16
```

Compared benchmarks include TOPIX and MSCI Japan Minimum Volatility Index.

Reported comparison:

- TOPIX: return 10.0%, risk 15.2%, Sharpe 0.66;
- MSCI Japan Minimum Volatility: return 7.7%, risk 12.1%, Sharpe 0.64;
- MIS portfolio: return 16.3%, risk 14.0%, Sharpe 1.16.

The paper emphasizes that trading costs are included for the MIS strategy, making the comparison conservative in that respect.

## 12. Factor analysis

The authors analyze why the MIS portfolio outperformed TOPIX in a strong period.

Findings:

- selected stocks tended to be small-cap and low-correlation names;
- large-cap stocks often had high graph degree because they are more correlated with the broad market;
- high-degree stocks are less likely to appear in an independent set;
- the strategy's excess return was attributed partly to exposure to smaller low-correlation stocks.

This is a useful caution: MIS selection is not purely a risk reduction technique; it can introduce systematic factor tilts such as small-cap exposure.

## 13. Relevance for this project

This paper directly supports a graph-based QIS portfolio workflow:

1. compute return matrix from asset prices;
2. compute correlation matrix;
3. threshold correlations to build a market graph;
4. define binary decision variables `δ_select[i]`;
5. solve MIS via QUBO/Ising/heuristic methods;
6. validate independent-set feasibility;
7. assign continuous weights `x_weights[i]` using EW, IVW, or another portfolio weighting method;
8. evaluate return, risk, Sharpe, turnover, and transaction costs.

For code and documentation, keep the variable distinction clear:

- `δ_select` for selected/unselected assets;
- `z_spin` for Ising encoding;
- `x_weights` for portfolio weights.

## 14. Implementation checklist for future coding

When implementing an MIS portfolio module:

- expose `θ` as a strategy parameter;
- use robust correlation estimation and handle missing price data;
- build graph edges only for `C_ij ≥ θ` unless a different rule is explicitly intended;
- define QUBO penalty coefficient `A` and reward coefficient `B`, with `B < A` for the simple MIS QUBO;
- after solving, check that no selected pair has an edge;
- compute both equal-weight and inverse-volatility-weight portfolios;
- measure turnover and transaction costs;
- compare against simple baselines, not only against advanced solvers;
- report factor tilts such as market cap, sector, volatility, or beta if available.

## 15. Caveats

- The reported performance is historical and market-specific.
- The method may load on small-cap or low-liquidity names.
- Correlation estimates depend strongly on the lookback window.
- Threshold choice `θ` can overfit if optimized on the same historical period used for evaluation.
- MIS maximizes the number of selected assets, not directly risk-adjusted return.
