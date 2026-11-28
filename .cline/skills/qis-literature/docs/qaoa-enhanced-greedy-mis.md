# A scalable quantum-enhanced greedy algorithm for maximum independent set problems — detailed notes

Source PDF supplied by user:
`/Users/trivellatoa/DATADIR/Manuali/QuantumComputing/AScalableQuantumEnhancedGreedyAlgorithmForMISProblems.pdf`

Paper title: **A scalable quantum-enhanced greedy algorithm for maximum independent set problems**  
Authors: Elisabeth Wybo, Jami Rönkkö, Olli Hirviniemi, Jernej Rudi Finžgar, Martin Leib  
Context: arXiv preprint, quantum optimization / QAOA / MIS.

## 1. Core idea

The paper studies a **hybrid quantum-classical algorithm** for the Maximum Independent Set (MIS) problem on regular graphs. The method combines:

1. a classical greedy MIS construction; and
2. local expectation values obtained from shallow QAOA circuits.

Instead of using QAOA as a standalone optimizer, QAOA is used as an **advisory subroutine** that informs each greedy decision. This is important because shallow QAOA alone performs poorly for MIS at low depths, while greedy algorithms are scalable but often make locally myopic decisions.

The main contribution is a scalable quantum-enhanced greedy algorithm that:

- avoids instance-specific variational parameter optimization;
- uses fixed QAOA angles precomputed from regular-tree models;
- uses local light-cone expectation values to rank candidate vertices;
- remains constructive, always producing a valid independent set;
- scales as `O(N)` for fixed graph degree `d` and QAOA depth `p`.

## 2. MIS formulation

Given a graph `G = (V, E)`, an independent set is a subset of vertices `I ⊆ V` such that no two selected vertices are adjacent:

```text
∀ i, j ∈ I: (i, j) ∉ E
```

The MIS problem asks for an independent set of maximum cardinality.

Using the project convention:

- use `δ_i ∈ {0,1}` to indicate whether vertex `i` is selected;
- use `z_i ∈ {-1,+1}` for Ising spin variables;
- use the explicit mapping `δ_i = (1 + z_i) / 2` and `z_i = 2δ_i - 1` when needed.

The paper uses a number operator

```text
N_i = (Z_i + 1) / 2
```

which acts like a binary selection variable in the computational basis. In project notation, this corresponds conceptually to `δ_i`.

The MIS Hamiltonian is written as:

```text
H_λ = λ Σ_(ij∈E) N_i N_j - Σ_(i∈V) N_i,   λ ≥ 1
```

Interpretation:

- `-Σ_i N_i` rewards selecting vertices;
- `λ Σ_(ij∈E) N_i N_j` penalizes selecting adjacent vertices;
- `λ ≥ 1` ensures constraint violations are not energetically favorable.

In Pauli-Z form, the Hamiltonian contains:

- pairwise `Z_i Z_j` couplings for edges;
- local `Z_i` fields depending on degree;
- a constant offset.

## 3. Classical greedy baseline

The baseline is the **minimal-degree greedy algorithm**:

1. choose a vertex of minimum degree, randomly if there are ties;
2. add it to the independent set;
3. delete the selected vertex and all its neighbors;
4. repeat until the graph is empty.

For bounded-degree graphs, the baseline has a worst-case approximation bound. For large random 3-regular graphs, the average independence ratio is about `0.432`, while a stronger classical linear-time prioritized search algorithm reaches about `0.445`.

The paper uses these as important baselines.

## 4. QAOA background

QAOA prepares a depth-`p` state via alternating applications of:

- the problem Hamiltonian `H`;
- the mixing Hamiltonian `B = Σ_i X_i`.

The depth-`p` ansatz is:

```text
|γ, β⟩ = exp(-i β_p B) exp(-i γ_p H) ... exp(-i β_1 B) exp(-i γ_1 H) |+⟩
```

A standard QAOA workflow would optimize parameters `(γ, β)` to minimize `⟨H⟩`. This paper avoids that costly optimization loop by using **fixed tree angles**.

## 5. Fixed tree angles

For large random `d`-regular graphs, local neighborhoods look like `d`-regular trees with high probability. Because depth-`p` QAOA is local, a local expectation value depends only on the graph structure inside a radius-`p` light cone.

Therefore, optimal or near-optimal angles can be precomputed on regular trees and reused across instances. This removes the bottleneck of variational parameter training.

Key consequence:

- fixed `p` and fixed `d` imply constant local quantum work per greedy decision;
- the total algorithm is linear in graph size `N`.

## 6. Quantum-enhanced greedy algorithm

The hybrid algorithm keeps the greedy delete-and-reduce backbone, but replaces random/min-degree tie-breaking with QAOA-informed ranking.

At each step:

1. compute or retrieve local QAOA expectation values `⟨Z_i⟩_p` for candidate vertices;
2. select the vertex with the largest expectation value;
3. add it to the independent set;
4. delete that vertex and its neighbors;
5. recompute only local expectation values affected by the deletion.

In the paper's interpretation, the vertex with the highest `⟨Z_i⟩_p` also has the highest `⟨N_i⟩` and is therefore considered most likely to belong to a good independent set.

Important implementation insight:

- after selecting vertex `i`, only vertices within distance `p + 1` of `i` need recomputation;
- expectation values for isomorphic rooted light-cone subgraphs can be cached;
- fixed-depth light-cone evaluations do not scale with total `N`.

At `p = 1`, the method reduces to the classical minimal-degree greedy rule. For `p > 1`, QAOA captures longer-range structure and can break greedy ties more intelligently.

## 7. Complexity

For fixed depth `p` and degree `d`:

```text
Total algorithmic scaling: O(N)
```

because each greedy update requires only a bounded number of local expectation-value computations.

However, if one wants QAOA light cones to see the whole graph, theoretical results suggest `p ∈ Ω(log N)`. In that regime, the scaling worsens.

The paper discusses three computational regimes for estimating `⟨Z_i⟩_p`:

1. **Tensor-network contraction**
   - tree-like light cones: exponential in `p`;
   - non-tree light cones: potentially double-exponential in `p` in the worst case.
2. **Quantum hardware with all-to-all connectivity**
   - roughly `O(p)` circuit depth for the local circuit.
3. **Quantum hardware with planar/local connectivity**
   - additional routing overhead; depth scales with light-cone size.

The paper argues that the cost of classical tensor-network contraction grows rapidly with `p`, while quantum hardware can estimate expectation values more directly.

## 8. Tensor-network simulations

The authors use tensor-network simulations, via QUIMB, to evaluate local QAOA expectation values up to `p = 4` on 3-regular graphs with sizes up to `N = 5000`.

The results show:

- quantum-enhanced greedy consistently outperforms the classical minimal-degree greedy baseline;
- depth `p = 4` can outperform the linear-time prioritized search baseline up to tested sizes around `N ≤ 2000`; 
- vanilla QAOA at low depth performs worse than greedy, emphasizing that the hybrid construction is the useful element.

## 9. Hardware implementation

The algorithm is implemented on a 20-qubit IQM superconducting device, IQM Garnet.

Key hardware details:

- local light-cone circuits are transpiled to native single-qubit rotations and CZ gates;
- p=2 light-cone subgraphs involve up to 10 qubits;
- p=3 can involve 21–22 qubits for rare subgraphs, slightly exceeding the device capacity;
- Pauli twirling is used to make coherent noise more stochastic/depolarizing-like;
- each circuit/data point uses 20,000 measurements split across twirled variants.

Hardware results show that noisy expectation values can still guide greedy selection effectively if the ordering/hierarchy of expectation values is preserved.

## 10. Noise model

The paper proposes a phenomenological noise model for measured expectation values:

```text
⟨Ẑ_i⟩ = (1 - η)^{|Ṽ_i|} ⟨Z_i⟩ + α + ξ_i
```

where:

- `|Ṽ_i|` is the size of the local light-cone subgraph;
- `η` models subgraph-size dependent shrinking from accumulated noise;
- `α` models uniform bias;
- `ξ_i` models residual Gaussian fluctuations.

The fitted values for p=3 are roughly:

- `η = 0.03`;
- `α = -0.05`;
- `σ = 0.04`.

The main performance degradation is attributed more to random fluctuations than to uniform shrinking.

## 11. Main results and implications

The paper's key messages:

- QAOA alone is not competitive for MIS at shallow depths.
- QAOA can still be useful as a local advisory component in a classical greedy algorithm.
- Fixed tree angles make the algorithm non-variational and scalable.
- The algorithm is constructive and always returns a valid independent set.
- The method has modular potential: it can be integrated into existing MIS solvers and extended to related sparse-graph combinatorial problems.

## 12. Relevance for this project

This paper is relevant for QIS portfolio optimization because portfolio diversification via market graphs can be formulated as MIS. It suggests a possible architecture:

1. build a market graph from asset correlations;
2. define binary variables `δ_i` for selecting assets;
3. solve or approximate MIS using classical, quantum-inspired, or quantum-enhanced methods;
4. optionally use QAOA local expectation values to guide greedy selection on sparse market graphs.

For dense market graphs, direct application of sparse-regular-graph assumptions may not hold. However, if the graph is thresholded or sparsified, the hybrid greedy idea may become more applicable.

## 13. Implementation checklist for future coding

When using these ideas in code:

- represent asset/vertex selection as `δ_select[i] ∈ {0,1}`;
- if using Ising variables, define `z_spin[i] = 2δ_select[i] - 1` explicitly;
- separate graph construction from optimization;
- separate feasibility checking from objective scoring;
- cache local subgraph evaluations if implementing QAOA-guided greedy;
- validate that selected vertices form an independent set after every solver run;
- benchmark against simple greedy and NetworkX-style heuristics before adding quantum components.
