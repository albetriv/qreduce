---
name: dwave-usage-guide
description: Guide the user in the most appropriate and effective use of D-Wave quantum optimization tools by consulting the local dwave-docs MCP server. Use when the user asks about D-Wave, Ocean SDK, Leap, quantum annealing, hybrid solvers, QUBO, BQM, CQM, DQM, Ising models, samplers, embeddings, or solver selection.
---

# D-Wave Usage Guide

Use this skill when the user wants guidance on using D-Wave effectively and according to official documentation.

This skill is focused on **D-Wave** documentation and workflows.

## Primary Documentation Source

Use the local MCP server `dwave-docs` before giving documentation-sensitive guidance.

Available tools:

- `search_dwave_docs`
  - Use when the exact D-Wave documentation page is unknown.
  - Search with concise terms such as `QUBO`, `BinaryQuadraticModel`, `Ising`, `Ocean SDK`, `Leap`, `hybrid solver`, `CQM`, `DQM`, `sampler`, `embedding`, or `Solver API`.
- `fetch_dwave_doc`
  - Use when the documentation path or URL is known.
  - Defaults to `/en/latest/`.
  - Use after search to read the most relevant page in detail.

## When to Trigger

Trigger this skill for requests such as:

- “Come uso D-Wave per questo problema di ottimizzazione?”
- “Meglio QUBO, BQM, CQM o DQM?”
- “Come modello un problema per Ocean SDK?”
- “Come converto un problema QUBO in Ising?”
- “Quando uso un hybrid solver invece di una QPU?”
- “Come scelgo sampler, composite o embedding?”
- “Come imposto variabili, vincoli e penalità?”
- “Come invio un problema a Leap?”
- “Quali best practice D-Wave devo seguire?”

## Workflow

1. **Understand the optimization problem**
   - Identify objective, variables, constraints, data size, and output requirements.
   - Ask clarifying questions if the mathematical model or domain is underspecified.

2. **Choose the right model family**
   - Use **BQM/QUBO/Ising** when the problem is unconstrained or constraints can be encoded with penalties.
   - Use **CQM** when constraints are important and should remain explicit.
   - Use **DQM** for discrete variables with more than two states when appropriate.
   - Use **hybrid solvers** for larger or constraint-rich industrial problems.
   - Use direct **QPU** workflows when the user specifically needs quantum annealing behavior, embeddings, QPU parameters, or low-level experiments.

3. **Consult D-Wave docs**
   - If the correct page is unknown, call `search_dwave_docs` first.
   - Then call `fetch_dwave_doc` for the most relevant page.
   - Prefer documentation-derived guidance over memory.

4. **Translate docs into a practical modeling plan**
   - Define variables and domains.
   - Write the objective.
   - Add constraints or penalties.
   - Select a solver/sampler.
   - Define validation and interpretation steps.

5. **Cite sources**
   - Mention the relevant D-Wave documentation path or URL used.
   - If multiple pages were consulted, list them in a short “Fonti” section.

## Project Variable Convention

Always follow this workspace convention in Python, notebooks, examples, pseudocode, and explanations:

- `x` → continuous variable.
- `δ` → binary/Boolean variable in `{0,1}`.
- `z` → Ising spin variable in `{-1,+1}`.

Use explicit names when helpful:

- `x_weights`, `x_opt` for continuous variables.
- `δ_select`, `δ_opt` for binary variables.
- `z_spin`, `z_opt` for Ising spin variables.

When converting between binary and Ising variables, always state the mapping near the code or formula:

```text
δ = (1 + z) / 2
z = 2δ - 1
```

Avoid using the same symbol for multiple domains in the same explanation or file.

## Modeling Guidance Patterns

### QUBO / BQM

Use QUBO/BQM guidance when the problem can be represented with binary variables and a quadratic objective:

```text
minimize  Σ_i a_i δ_i + Σ_{i<j} b_ij δ_i δ_j
subject to δ_i ∈ {0,1}
```

Guidance:

- State what each `δ_i` represents.
- Keep coefficients scaled reasonably.
- Encode hard constraints with penalties only when appropriate.
- Explain penalty strength tradeoffs.
- Validate small instances classically before using D-Wave solvers.

### Ising

Use Ising guidance when the model is expressed with spin variables:

```text
minimize  Σ_i h_i z_i + Σ_{i<j} J_ij z_i z_j
subject to z_i ∈ {-1,+1}
```

Guidance:

- Define each `z_i` clearly.
- If starting from binary variables, explicitly use `z = 2δ - 1`.
- Explain interpretation of spin values in the original domain.

### CQM

Use CQM guidance when explicit constraints matter:

- Define objective separately from constraints.
- Keep binary variables as `δ`, continuous variables as `x`, and integer/discrete variables clearly named.
- Prefer CQM for constrained optimization before manually adding many penalty terms.

### Solver Selection

Recommend solver/sampler based on problem characteristics:

- Small BQM/QUBO and educational examples: local/simulated samplers first, then D-Wave samplers if access is configured.
- Larger unconstrained binary problems: hybrid BQM solver.
- Constraint-heavy problems: hybrid CQM solver.
- Experiments with quantum annealing hardware: QPU sampler and embedding-aware workflows.

Always mention that exact solver availability can depend on the user’s Leap account and region.

## Safe Implementation Workflow

When helping implement D-Wave code:

1. Search/fetch relevant D-Wave docs.
2. Clarify the model and variable domains.
3. Write a small reproducible example first.
4. Validate the objective and constraints on a tiny instance.
5. Add solver integration.
6. Interpret returned samples/energies/feasibility.
7. Document any assumptions and scaling choices.

## Output Style

When this skill is active:

- Answer in Italian unless the user asks otherwise.
- Be practical and mathematically explicit.
- Use the `x`, `δ`, `z` convention consistently.
- Include formulas when useful.
- Include Python/Ocean snippets only when they help.
- Cite D-Wave documentation URLs or paths consulted.
- If documentation access fails, say so clearly and fall back to cautious general guidance.

## Quick Examples

### User: “Come modello un selection problem in QUBO?”

1. Search D-Wave docs for `QUBO BinaryQuadraticModel`.
2. Fetch the relevant page.
3. Define `δ_select_i ∈ {0,1}`.
4. Write objective and penalties.
5. Suggest validation on a small instance.

### User: “Meglio CQM o QUBO?”

1. Search D-Wave docs for `CQM constraints hybrid solver` and `BQM QUBO`.
2. Explain tradeoffs.
3. Recommend CQM if constraints should remain explicit; QUBO/BQM if unconstrained or penalty encoding is simple.

### User: “Converti questo QUBO in Ising”

1. State mappings `δ = (1 + z) / 2` and `z = 2δ - 1`.
2. Substitute into the objective.
3. Simplify linear, quadratic, and constant terms.
4. Explain how `z_opt` maps back to `δ_opt`.
