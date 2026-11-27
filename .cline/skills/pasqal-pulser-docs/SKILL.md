---
name: pasqal-pulser-docs
description: Guide the user in the most appropriate and effective use of Pasqal, Pulser, neutral atoms, and Pasqal Cloud by consulting the local pasqal-docs MCP server. Use when the user asks about Pasqal, Pulser, neutral atoms, Rydberg physics, pasqal-cloud, pulser-pasqal, MIS on neutral atoms, Pulser Register/Sequence/Pulse/Device APIs, or Pasqal backend execution.
---

# pasqal-pulser-docs

Use this skill to answer user requests about **Pasqal**, **Pulser**, neutral atoms, Rydberg atoms, Pasqal Cloud, or integrations between Pulser and Pasqal services.

This skill is focused on **Pasqal/Pulser** documentation and workflows.

## Primary Documentation Source

Use the local MCP server `pasqal-docs` before giving documentation-sensitive guidance.

Available tools:

- `search_pasqal_docs`
  - Use when the exact Pasqal/Pulser documentation page is unknown.
  - Search with concise terms such as `Pulser Register`, `Sequence`, `Pulse`, `AnalogDevice`, `pasqal-cloud`, `pulser-pasqal`, `Rydberg blockade`, `neutral atoms`, `MIS`, `backend`, or `PasqalCloud`.
- `fetch_pasqal_doc`
  - Use when the documentation path or URL is known.
  - Defaults to `/`.
  - Use after search to read the most relevant page in detail.

Pulser must be treated as an SDK for programming neutral-atom devices through physical registers and pulse sequences, not as a direct equivalent of gate-based frameworks such as Qiskit.

## Usage

Activate this skill when the user request contains or concerns one or more of these topics:

- `Pasqal`, `PASQAL`, `pasqal-cloud`, `Pasqal Cloud`, `QPU Pasqal`
- `Pulser`, `pulser`, `pulser-pasqal`, `pulser-simulation`
- neutral atoms, atomi neutri, Rydberg atoms, Rydberg blockade
- Pulser concepts such as `Register`, `Sequence`, `Pulse`, `Channel`, `Device`, `AnalogDevice`, `DigitalAnalogDevice`, `Fresnel`
- Pasqal/Pulser backends, emulators, `EmuFreeBackend`, `PasqalCloud`
- MIS / Maximum Independent Set mapped to neutral atoms or geometric graphs
- analog pulse sequences, detuning, Rabi frequency, amplitude, phase, pulse duration
- authentication or execution problems with Pasqal Cloud, including `401 Unauthorized` or `403 Forbidden`

## Sources and priority

1. Use the local MCP server `pasqal-docs` as the primary access path to official Pasqal/Pulser documentation for APIs, names, versions, and expected behavior.
2. Use local workspace files as additional context when relevant, if Pasqal/Pulser-specific files are present in this workspace.
3. If official documentation and local code disagree, explicitly mention the discrepancy and prefer the MCP-fetched official documentation for current API behavior.
4. If MCP/documentation access is unavailable, state that clearly and base the answer on internal knowledge plus local files, warning that `pasqal-cloud`, `pulser-pasqal`, and Pulser APIs may have changed.

## Steps

1. Classify the request as conceptual, implementation-oriented, debugging-oriented, or documentation-oriented.
2. Identify the relevant Pasqal/Pulser domain concepts:
   - neutral-atom analog programming;
   - physical atom layout via `Register`;
   - device/backend constraints;
   - `Sequence` construction;
   - channels, pulses, amplitude, detuning, phase, and duration;
   - simulator, emulator, QPU, or Pasqal Cloud execution.
3. Consult Pasqal/Pulser docs through `pasqal-docs`:
   - call `search_pasqal_docs` first if the exact page is unknown;
   - then call `fetch_pasqal_doc` for the most relevant page;
   - prefer documentation-derived guidance over memory.
4. For implementation requests, inspect the relevant workspace file before proposing or applying edits.
5. Prefer APIs, imports, and terminology consistent with the MCP-fetched official documentation.
6. Mention version/API caveats when examples may depend on installed package versions.
7. For cloud examples, never hardcode credentials. Use environment variables such as:
   - `PASQAL_USERNAME`
   - `PASQAL_PASSWORD`
   - `PASQAL_PROJECT_ID`
   - token-related variables when appropriate
8. Distinguish the Pasqal portal project id from cloud-provider project ids such as Google Cloud or Azure project/subscription identifiers.
9. For optimization problems, especially MIS:
   - connect the mapping to atom geometry and Rydberg blockade;
   - explain how graph constraints relate to physical interactions;
   - preserve this workspace's symbolic convention: `x` for continuous variables, `δ` for binary `{0,1}` variables, and `z` for Ising spins `{-1,+1}`.

## Response guidelines

For conceptual questions:

1. Give a short direct answer first.
2. Explain the Pasqal/Pulser-specific context.
3. Distinguish analog neutral-atom programming from gate-based programming and quantum annealing when useful.
4. Cite the relevant Pasqal/Pulser documentation path or URL returned by `pasqal-docs`.

For implementation questions:

1. Name the relevant workspace path/module and domain concept before suggesting edits.
2. Identify the Pulser/Pasqal components involved, such as `Register`, `Sequence`, device, backend, or cloud connection.
3. Propose or implement code using documented APIs.
4. Include warnings about credentials, SDK versions, and device/backend constraints.
5. Provide a verification command or test approach when possible.
6. Cite the relevant Pasqal/Pulser documentation path or URL returned by `pasqal-docs`.

For debugging questions:

1. Ask for the exact traceback/error if it is missing and cannot be inferred.
2. Separate authentication, project-id, onboarding, network/TLS, package-version, and device-constraint causes.
3. Treat `401 Unauthorized` and `403 Forbidden` as diagnostic signals, not as certain root causes without evidence.
4. Cite the relevant Pasqal/Pulser documentation path or URL returned by `pasqal-docs` when documentation was consulted.

## Avoid

- Do not present Pulser as a direct equivalent of Qiskit.
- Do not assume that every Pulser sequence can run on every Pasqal device.
- Do not invent backend, device, class, or method names that are not verified from official docs or local code.
- Do not hardcode real credentials, project ids, tokens, or secrets in examples or code changes.
- Do not ignore possible API changes in `pasqal-cloud`, `pulser-pasqal`, or Pulser compared with older local code.
