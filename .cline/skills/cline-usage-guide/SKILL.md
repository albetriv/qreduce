---
name: cline-usage-guide
description: Guide the user in the most appropriate and effective use of Cline by consulting the local cline-docs MCP server. Use when the user asks how to use Cline, choose Cline workflows, configure Cline, use tools, rules, skills, MCP servers, modes, approvals, context, or best practices.
---

# Cline Usage Guide

Use this skill when the user wants guidance on how to use Cline effectively, safely, and according to official documentation.

This skill is intentionally focused on **Cline only**.

## Primary Documentation Source

Use the local MCP server `cline-docs` before giving documentation-sensitive guidance.

Available tools:

- `search_cline_docs`
  - Use when the exact documentation page is unknown.
  - Search with concise terms such as `skills`, `cline rules`, `MCP server`, `plan act mode`, `tools`, `custom instructions`, `context management`, or `approvals`.
- `fetch_cline_doc`
  - Use when the documentation path or URL is known.
  - Defaults to `/cline-overview`.
  - Use it after search to read the most relevant page in detail.

## When to Trigger

Trigger this skill for requests such as:

- “Come posso usare meglio Cline?”
- “Qual è il workflow giusto in Cline per questo task?”
- “Quando devo usare PLAN MODE o ACT MODE?”
- “Come creo o organizzo rules/skills?”
- “Come configuro un MCP server?”
- “Come devo chiedere a Cline di modificare codice?”
- “Come riduco errori, contesto inutile o tool calls sbagliate?”
- “Quali best practice Cline devo seguire?”

## Workflow

1. **Understand the user’s Cline goal**
   - Identify whether the user needs help with workflow, configuration, rules, skills, MCP, tool usage, context, approvals, or debugging.
   - If the request is vague, ask a short clarifying question.

2. **Consult official Cline docs**
   - If the correct page is unknown, call `search_cline_docs` first.
   - Then call `fetch_cline_doc` for the best matching page.
   - Prefer documentation-derived guidance over memory.

3. **Translate docs into practical advice**
   - Provide an actionable recommendation for the user’s situation.
   - Include concrete examples of prompts, file locations, settings, or workflow steps when useful.
   - Explain tradeoffs briefly: for example rules vs skills, MCP tools vs built-in tools, PLAN vs ACT.

4. **Cite sources**
   - Mention the relevant Cline documentation path or URL used.
   - If the answer is based on multiple pages, list them in a short “Fonti” section.

5. **Adapt to this workspace**
   - Respect existing `.clinerules/` instructions.
   - For skills, prefer workspace location `.cline/skills/` unless the user asks for a global skill.
   - For MCP servers, use `/Users/trivellatoa/Documents/Cline/MCP` unless the user specifies a different location.
   - For this workspace, remember that `src/ext/cato-ca.pem` may be needed for Node HTTPS through `NODE_EXTRA_CA_CERTS`.

## Common Guidance Patterns

### Rules vs Skills

- Use **Cline rules** for instructions that must always be active in a workspace.
- Use **skills** for specialized instructions that should load only when relevant.
- If the user asks for a repeated workflow that is not always needed, recommend a skill.
- If the instruction is a hard project convention, recommend a rule.

### PLAN MODE vs ACT MODE

- Use **PLAN MODE** for architecture, exploration, risk assessment, and agreeing on a plan before edits.
- Use **ACT MODE** for implementation, file changes, command execution, testing, and final delivery.
- If the task scope is ambiguous, gather context and propose a plan before editing.

### MCP Servers

- Recommend MCP servers when Cline needs durable access to external systems, documentation, APIs, databases, or tools.
- Prefer tools over static resources when dynamic parameters are needed.
- Ensure new MCP servers are configured with `disabled: false` and `autoApprove: []` unless explicitly instructed otherwise.
- After installation, test the exposed MCP tools directly.

### Prompting Cline Effectively

Encourage users to include:

- goal and expected output;
- relevant files or modules;
- constraints and non-goals;
- whether they want planning only or implementation;
- test or validation criteria;
- desired response language and detail level.

Example user prompt:

```text
Analizza questo modulo e proponi un piano prima di modificare codice. Obiettivo: aggiungere test per X. Vincoli: non cambiare API pubbliche. Dopo il piano, attendi conferma.
```

### Safe Implementation Workflow

When guiding Cline usage for coding tasks, recommend:

1. Explore files and definitions first.
2. Identify deliverables and success criteria.
3. Make minimal coherent edits.
4. Run focused tests or validation commands.
5. Summarize files changed, checks run, and any follow-up work.
6. Ask for feedback at completion, following workspace rules.

## Output Style

When this skill is active:

- Answer in Italian unless the user asks otherwise.
- Be practical and concise.
- Include source paths/URLs from Cline docs.
- If the user asks “come dovrei usare Cline per X?”, provide a recommended workflow and a ready-to-copy prompt.
- If documentation access fails, say so clearly and fall back to cautious general guidance.

## Quick Examples

### User: “Come uso Cline per creare un MCP server?”

1. Search Cline docs for `MCP server create`.
2. Fetch the relevant docs page.
3. Explain recommended MCP creation steps, settings file location, test strategy, and safety considerations.
4. Provide a prompt template the user can reuse.

### User: “Mi conviene una rule o una skill?”

1. Search/fetch docs for Cline rules and skills.
2. Explain: always-on convention → rule; on-demand specialist behavior → skill.
3. Recommend one based on the user’s case.

### User: “Come devo formulare task complessi?”

1. Consult docs on workflows/tools if needed.
2. Suggest a structured prompt with goal, constraints, files, success criteria, and desired mode.
