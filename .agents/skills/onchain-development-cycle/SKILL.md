---
name: onchain-development-cycle
description: Plan, implement, verify, and review each development phase of this on-chain analytics and risk-management project, including readiness checks, acceptance evidence, and interview-oriented technical review. Also use when explaining this project's code or language/framework concepts from a smart-contract developer's perspective. Do not use for unrelated repositories or generic blockchain questions.
---

# On-chain Development Cycle

Use one repeatable engineering cycle for every phase. Tie analysis and interview preparation to decisions and evidence from the actual implementation.

## Local Configuration Boundary

Never open, read, search, parse, print, copy, or edit a real `.env` file or other local credentials file, including through scripts, logs, or command output. Inspect and edit `.env.example` only. If a real value must change, name the variable for the user to update locally. The application may load `.env` during normal startup, but agent tools must not inspect its contents or infer credentials from runtime responses.

## Explanation Style

For explanations of this project's code, language syntax, or framework concepts:

- Assume the user is familiar with Solidity and smart-contract development but may be new to Python and backend frameworks. Prefer Chinese explanations unless the user requests another language.
- Start with the concept's actual role in the repository, then use a familiar Solidity/Foundry analogy and a small side-by-side example when useful. Favor concepts such as structs, interfaces, constructors, modifiers, contract instances, and dependency injection through interface-typed parameters.
- State where each analogy stops being accurate. Distinguish classes from instances, data containers from behavior, Python type hints from Solidity type enforcement, and off-chain service state from on-chain storage. Do not imply that creating a Python object deploys a contract or that an RPC client is the blockchain node.
- Inspect the relevant definitions before making project-specific claims. Explain unfamiliar syntax and how values flow through the current code, rather than relying on backend jargon alone.

For explanation-only requests, use this guidance without starting the phase implementation workflow or making unrelated code changes.

## Project Baseline

Preserve these choices unless the user explicitly changes them:

- Target Base Sepolia for development and demonstrations (`chain_id=84532`, native asset ETH, 18 decimals). Treat Base Mainnet (`chain_id=8453`) as a separate future configuration; never mix network data.
- Use BlockPI as the RPC provider. Keep its endpoint and credentials in environment variables and redact them from logs and output.
- Build the API with Python, FastAPI, Pydantic, web3.py, and pytest.
- Keep the first product read-only. Do not add transaction signing, private keys, or execution without a later explicit scope decision.
- Treat Foundry as an optional local-chain, contract-deployment, fixture-generation, and cross-checking tool. Do not make it a Python service runtime dependency.
- Prefer deterministic data collection and rules before adding LLM interpretation.

Read the relevant phase in `AI学习路线.md` before planning or editing. Inspect the repository and current changes before deciding what remains.

## Cycle Workflow

### 1. Establish the phase contract

State before implementation:

- Goal and user-visible deliverable.
- In-scope and explicitly out-of-scope behavior.
- Inputs, outputs, external dependencies, and data sources.
- Acceptance criteria that can be demonstrated or tested.
- Assumptions that would materially affect the design.

Keep the smallest vertical slice that satisfies the phase. Do not pull later-phase databases, LLMs, agents, or deployment infrastructure forward without a concrete need.

### 2. Audit readiness

Check the real workspace rather than assuming it is ready:

- Runtime and dependency versions, isolated environment, lock or dependency file.
- Required services and tools, including RPC access and optional Foundry tools.
- Configuration template, `.gitignore`, secret handling, and startup documentation.
- Reproducible public addresses, transaction hashes, blocks, or fixed fixtures.
- Network identity and provider capabilities.

Never request that the user paste a secret into chat. Use placeholder values and name the environment variable that must be configured locally.

### 3. Design correctness boundaries

Before editing, identify the behavior at each boundary:

- API validation and normalization.
- Service-level business semantics.
- Provider-specific RPC translation.
- Error categories and HTTP mapping.
- Source, scope, observation time, block number, and block hash carried with results.
- Retry, timeout, rate-limit, and partial-data behavior.

Use an adapter around BlockPI/web3.py so business logic and tests are not coupled to a particular RPC endpoint.

### 4. Implement and verify incrementally

Implement one testable slice at a time. After each meaningful slice:

- Run focused unit tests.
- Use mocked or fake providers for error paths and deterministic logic.
- Use a small, clearly marked integration suite for BlockPI Base Sepolia.
- Cross-check selected public results with `cast` or an independent explorer when useful.
- Update documentation and example configuration when behavior changes.

Do not make ordinary unit tests depend on RPC availability, rate limits, or a mutable chain head.

### 5. Maintain a problem register

For every phase, summarize likely and encountered problems using this structure:

| Problem | Why it occurs | Chosen handling | Tradeoff | Verification |
| --- | --- | --- | --- | --- |

Cover only relevant categories:

- Data correctness and snapshot consistency.
- Chain behavior, finality, reorganization, and pending state.
- RPC transport, JSON-RPC errors, rate limits, timeouts, and provider variance.
- Numeric precision, token metadata, address/hash normalization, and pagination.
- Async concurrency, resource lifecycle, caching, and observability.
- Security, secrets, untrusted metadata, permissions, and data leakage.
- LLM grounding, citations, unsupported conclusions, evaluation, cost, and recovery when those features enter scope.

Distinguish a limitation from a bug. Represent unknown or incomplete data explicitly instead of converting it into a negative result.

### 6. Produce interview notes from the work

Turn actual engineering decisions into interview material. For each important topic, capture:

- A concise question an interviewer could ask.
- The principle being tested.
- The answer used in this project.
- One rejected alternative or tradeoff.
- The code, test, log, or fixture that proves the answer is implemented.

Prioritize questions that require reasoning, such as consistency, failure semantics, idempotency, boundary design, and verification. Avoid trivia lists and claims that are not reflected in the repository.

### 7. Close the phase with evidence

Before calling a phase complete, report:

- What now works and what remains intentionally unsupported.
- Acceptance criteria and their evidence.
- Commands/tests run and their results.
- Known limitations and operational risks.
- Interview topics learned from this phase.
- Entry conditions for the next phase.

Do not mark the phase complete when external dependencies, required tests, or documentation needed for independent reproduction are missing.

## On-chain Invariants

Apply these whenever relevant:

- Verify the RPC-reported chain ID instead of trusting the configured network name.
- Keep on-chain amounts as integers; use `Decimal` only for display conversion and never use binary floating point for value calculations.
- For a consistent balance snapshot, select a block first and query state at that block. Return its number and hash.
- A transaction receipt does not contain block time; retrieve the containing block when time is required.
- Treat receipt success as EVM execution success, not proof of business correctness or safety.
- An RPC node cannot enumerate every address transaction, token balance, or approval without indexing or bounded log scanning.
- Historical events do not necessarily represent current contract state.
- Keep HTTP failures, JSON-RPC errors, valid null results, and domain-level unsupported states distinct.
- Preserve provenance and coverage limits in API results and reports.
- Never infer maliciousness from unlimited approval, unusual activity, or a model response alone.

## Phase 1 Focus

For the initial Base Sepolia/BlockPI phase, keep the deliverable to:

- Health and network identity checks.
- ETH balance at an identified block.
- Transaction receipt plus containing-block time.
- Address, transaction hash, and configured-network validation.
- Clear handling of pending/not-found transactions, BlockPI timeout, rate limit, RPC error, and chain mismatch.
- Unit tests, a small opt-in integration test set, 3-5 reproducible public fixtures, `.env.example`, and startup documentation.

Do not add BEP-20 discovery, transaction-history enumeration, risk scoring, a database, or an LLM during this phase.
