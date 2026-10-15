# Claude Code Task: Add an Isolated Agentic AI Research Feature to PredictionMarketProject

## Mission

Add a new, working AI research/strategy-assistant feature to this repository:

`andrewely8/PredictionMarketProject`

The existing application is an Electron + React desktop app with Python services. The new feature should let a user select prediction-market data files from the existing workspace and interact with an LLM through a chat-style panel.

Example user requests:

- "Observe these data files and suggest potential strategy hypotheses worth backtesting."
- "Analyze these order-book files and explain patterns that might be exploitable."
- "Create a strategy file that tests whether short-term order-book imbalance predicts future price movement."
- "Build a strategy prototype that trains an ML model on historical data and predicts future prices."
- "Compare these two data files and suggest why a strategy might behave differently."
- "Generate a Python strategy scaffold I can test in the existing simulator."

The feature MUST use a real LangChain pipeline and MUST integrate LangSmith tracing/evaluation. It should support structured tool calling rather than being only a single prompt sent to an LLM.

The feature is a research/prototyping assistant. It must never promise that a strategy is profitable. Generated strategies are hypotheses that must be tested on held-out data and/or through the existing backtester.

---

# CRITICAL REPOSITORY-CONTAINMENT RULE

This is the most important constraint.

Do NOT scatter new AI-related files throughout the existing repository.

Create one clearly isolated directory:

```text
reactWebsite/electron-react/NEW_FEATURE_BY_CLAUDE_CODE/
```

Put essentially ALL new implementation code inside this directory.

Preferred structure:

```text
reactWebsite/electron-react/NEW_FEATURE_BY_CLAUDE_CODE/
│
├── README.md
├── backend/
│   ├── server.py
│   ├── agent.py
│   ├── tools.py
│   ├── rag.py
│   ├── models.py
│   ├── requirements.txt
│   └── generated/
│
├── frontend/
│   ├── AIResearchPanel.jsx
│   └── AIResearchPanel.css
│
└── tests/
    └── ...
```

You may simplify this structure if fewer files are cleaner, but all AI-specific implementation must remain under `NEW_FEATURE_BY_CLAUDE_CODE`.

Do not create miscellaneous AI files in `src/main`, `src/renderer/components`, `backendPython`, the repository root, or other existing directories.

## Existing-code modification budget

Modify as little existing code as technically possible.

The ideal renderer integration is approximately:

```jsx
import AIResearchPanel from '../../NEW_FEATURE_BY_CLAUDE_CODE/frontend/AIResearchPanel.jsx';
```

and:

```jsx
<AIResearchPanel />
```

or the equivalent correct relative import for this project.

Small integration changes to Electron `main.ts`, `preload.ts`, `package.json`, or build configuration are allowed ONLY if they are genuinely required for startup, filesystem access, secure IPC, or packaging.

If those files must be touched:

1. Keep each modification extremely small.
2. Put all substantive logic inside `NEW_FEATURE_BY_CLAUDE_CODE`.
3. Do not refactor unrelated code.
4. Do not rename or reorganize existing files.
5. Do not change existing behavior unless required for this feature.
6. Reuse existing Electron APIs and patterns when possible.
7. Before making a broad architectural change, find another design.

If you believe this feature requires modifying more than a few existing integration files, STOP and redesign it to be more isolated.

---

# Existing application context

Inspect the repository before coding.

Important existing architecture:

- `reactWebsite/electron-react/src/renderer/App.tsx`
  - Main React layout.
  - Uses `react-resizable-panels`.
  - Existing panels include `MarketTracker`, `Workspace`, and `Replayer`.

- `reactWebsite/electron-react/src/renderer/components/Workspace.jsx`
  - Reads the selected workspace directory.
  - Distinguishes `.jsonl` market-data files from strategy files.
  - Existing strategy files can be selected for testing.

- `reactWebsite/electron-react/src/main/main.ts`
  - Electron main process.
  - Existing IPC handlers read directories/files.
  - Spawns Python strategy processes.
  - Spawns the existing FastAPI simulator.
  - Spawns the market-data collector.

- `reactWebsite/electron-react/src/main/preload.ts`
  - Exposes controlled Electron IPC functionality to the renderer.

- Existing Python/FastAPI infrastructure already exists under:
  - `reactWebsite/electron-react/backendPython/`

Do not replace these systems.

The AI feature should sit beside the current application as an isolated optional capability.

---

# User Experience

Add a visible panel called something like:

**AI Strategy Research**

The UI should be simple and functional rather than visually elaborate.

It should contain:

1. A list or selector for workspace `.jsonl` market-data files.
2. Ability to select one or multiple data files for the AI session.
3. A conversation/history area.
4. A multiline text box.
5. A Send button.
6. A status indicator while the agent is working.
7. Clear display of tool activity at a high level, for example:
   - "Profiling selected file..."
   - "Retrieving relevant market windows..."
   - "Generating strategy artifact..."
   - "Running validation..."
8. Artifact cards when the agent generates a file.

An artifact card should show:

- file name
- file type
- short description
- generated path
- buttons where applicable:
  - **Open**
  - **Download / Save As**
  - **Add to Workspace**
  - **Test**
  - optionally **Delete**

Do not silently write generated strategies into the user's normal workspace.

Generated files must initially be written only under:

```text
NEW_FEATURE_BY_CLAUDE_CODE/backend/generated/
```

or an equivalent application-data temporary directory if packaging requires it.

Only copy a generated file into the user's selected workspace after the user explicitly clicks **Add to Workspace**.

---

# Core Architecture

Use this conceptual flow:

```text
React AIResearchPanel
        |
        v
isolated local AI service
        |
        v
LangChain / agent workflow
        |
        +------> data inspection tools
        |
        +------> retrieval / RAG
        |
        +------> artifact generation
        |
        +------> strategy validation/testing tools
        |
        v
LLM
        |
        v
structured response + optional generated artifacts
```

Prefer a localhost Python service inside `NEW_FEATURE_BY_CLAUDE_CODE/backend`.

Do not put API keys in the React renderer.

Do not expose unrestricted filesystem access to the renderer.

The backend should accept only the paths/data necessary for selected workspace files and should validate paths before reading or writing.

---

# LLM Provider Abstraction

Design the backend so the agent is not permanently tied to one model.

Support at least one working provider now, but structure it so these can be swapped:

### Cloud option

Anthropic/Claude through the relevant LangChain integration.

Environment variable example:

```text
ANTHROPIC_API_KEY=
```

### Local/open-source option

Support or leave a clean configuration path for Ollama through the relevant LangChain integration.

Example models might include Qwen, Llama, Mistral, etc.

Example configuration:

```text
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b
```

or:

```text
LLM_PROVIDER=anthropic
```

Do not invent custom provider abstractions if LangChain already provides a clean interface.

The README must explain how to switch providers.

---

# REQUIRED: Actual LangChain Usage

This requirement is not satisfied by merely installing LangChain.

The application must genuinely use LangChain for the agent/workflow.

Use the current recommended LangChain/LangGraph APIs available at implementation time. Do not blindly copy deprecated tutorials.

The pipeline should include:

1. model initialization
2. system instructions
3. structured tools
4. agent/tool-calling loop
5. conversation state
6. retrieval context when files are selected
7. structured final response

The model must be able to decide when to invoke tools rather than receiving all raw data directly in every prompt.

Examples of tools:

```text
list_selected_data_files
profile_market_data
sample_market_windows
retrieve_relevant_market_context
create_strategy_artifact
create_analysis_artifact
validate_python_artifact
run_strategy_test
get_backtest_summary
```

Tool names may differ, but this kind of functionality should exist.

Do not expose a generic unrestricted shell tool to the LLM.

Do not give the LLM arbitrary filesystem access.

Give it narrow, validated application-specific tools.

---

# REQUIRED: LangSmith

Integrate LangSmith so agent execution can be traced.

Support standard environment-based configuration such as the current LangSmith-recommended variables.

The README must explain:

- how to enable LangSmith tracing
- how to name the project
- what is traced
- how traces help inspect model/tool behavior

At minimum, traces should make it possible to inspect:

- user request
- model calls
- tool calls
- retrieval operations
- final answer
- errors/latency where supported

If practical, create a tiny evaluation dataset containing several representative requests, such as:

1. identify a plausible order-book hypothesis
2. request a generated strategy
3. request an ML-based strategy scaffold
4. ask a question requiring retrieval from selected data
5. request something the system should refuse or qualify, such as "guarantee me a profitable strategy"

Add a small documented evaluation script if it can remain inside the feature directory.

Do not build a huge evaluation framework.

---

# RAG / DATA RETRIEVAL REQUIREMENTS

The market data files can be very large.

NEVER send an entire raw `.jsonl` data file to the LLM.

NEVER load hundreds of megabytes into a prompt.

Implement a lightweight retrieval pipeline.

A reasonable first version:

1. User selects one or more `.jsonl` files.
2. Backend profiles each file.
3. Parse/summarize useful fields.
4. Construct manageable text/structured chunks representing:
   - file metadata
   - market/ticker information
   - time ranges
   - sampled order-book states
   - spread / midpoint / imbalance information when available
   - representative windows
5. Build a temporary retrieval index for the selected files.
6. Retrieve only relevant chunks for each question.
7. Pass retrieved context into the agent.

Use a current LangChain-compatible retriever/vector store or another legitimate LangChain retrieval abstraction.

Because this is numerical market data, do not rely exclusively on semantic embeddings.

Where useful, expose deterministic analytical tools that calculate statistics directly from the data. The LLM should reason over tool results rather than hallucinating statistics.

Examples:

```text
profile_market_data(file)
calculate_spread_statistics(file)
calculate_orderbook_imbalance(file)
sample_windows(file, count, criteria)
compare_files(files)
```

The RAG component can retrieve textual summaries/windows while deterministic tools calculate numeric facts.

Cache indexes/summaries for the current session when practical.

---

# Strategy Research Behavior

The assistant should behave like a quantitative research copilot, not a stock-tip chatbot.

System instructions should explicitly say:

- Never claim a strategy is profitable solely because it sounds plausible.
- Clearly distinguish:
  - observed facts
  - hypotheses
  - generated strategy ideas
  - actual backtest results
- Avoid look-ahead bias.
- Avoid training/test leakage.
- For ML strategies, use chronological splits rather than random train/test splits unless there is a strong reason otherwise.
- Do not train on future information that would not have been available at decision time.
- Require a held-out test period.
- Explain assumptions about transaction costs, fills, latency, liquidity, and slippage.
- Treat historical performance as evidence, not proof of future profitability.
- Prefer simple baselines before complex ML models.

---

# ML Strategy Generation

The user should be able to ask something like:

> Build a strategy that develops an ML model to learn from this data and predict future prices.

A useful generated artifact could be a Python strategy/research script that:

1. parses selected historical market data
2. constructs features such as:
   - bid/ask spread
   - midpoint
   - top-of-book volume
   - order-book imbalance
   - recent price/midpoint changes
   - recent volume changes
3. creates a future-price or future-direction target
4. uses chronological train/validation/test splits
5. trains a simple baseline model
6. evaluates on unseen data
7. reports metrics
8. optionally converts predictions into simulated actions compatible with the backtesting environment

Prefer a simple interpretable baseline first, such as logistic regression or another lightweight model, before proposing deep learning.

Do not automatically install a giant ML stack unless needed.

Generated ML code must clearly mark assumptions and prevent obvious target leakage.

---

# Generated Artifacts

The agent should be capable of generating files.

Examples:

```text
strategy_orderbook_imbalance.py
ml_price_direction_strategy.py
market_analysis.md
experiment_plan.md
feature_report.json
```

The LLM should NOT directly write arbitrary paths.

Use a controlled tool such as:

```text
create_artifact(filename, content, artifact_type)
```

That tool must:

1. sanitize the filename
2. prevent `..` traversal
3. write only to the controlled generated-artifacts directory
4. return structured metadata
5. never overwrite an existing file without an explicit safe policy

Return something like:

```json
{
  "artifact_id": "...",
  "filename": "ml_price_direction_strategy.py",
  "type": "python_strategy",
  "path": "...",
  "description": "Baseline chronological ML strategy using order-book features"
}
```

The React panel should render this as an artifact card.

---

# Open / Download / Add to Workspace / Test

Implement these behaviors in the safest simple way possible.

## Open

Open the generated file using an appropriate local file/viewer behavior.

If opening directly is awkward, show the file contents in a modal or code viewer.

## Download / Save As

Allow the user to choose a destination and save a copy.

Use Electron's controlled dialog/filesystem layer if needed.

## Add to Workspace

Explicitly copy the generated artifact into the workspace selected by the existing application.

Never do this automatically.

If a file with the same name exists, ask for confirmation or create a non-destructive unique name.

## Test

For Python strategy artifacts, connect to the existing strategy/backtesting mechanism when practical.

Reuse existing behavior instead of creating a second unrelated simulator.

If direct reuse is too invasive for the first version, implement a narrowly scoped validation/test action such as:

1. syntax validation
2. import validation
3. optional execution against the existing simulator/API
4. return stdout/stderr and test status

Do not execute arbitrary shell commands provided by the LLM.

Only execute generated Python through a controlled strategy-testing path.

Use timeouts.

Allow the user to stop a long-running test.

---

# Security / Safety Boundaries

This is a local development feature, but still implement sane boundaries.

Required:

- No API keys in frontend code.
- No API keys committed to Git.
- Add an `.env.example` INSIDE the new feature directory if useful.
- Respect the repository's existing `.gitignore`; only modify it if absolutely necessary.
- Validate all file paths.
- Generated artifacts write only to the controlled directory until explicit user action.
- No arbitrary shell tool available to the LLM.
- No unrestricted `eval`.
- No arbitrary command execution supplied by model output.
- Add execution timeout for generated strategies.
- Do not let a generated strategy modify the source repository.
- Do not send entire private local directories to an external model.
- Clearly display which selected data files are being used in the AI conversation.

---

# Conversation Response Contract

Prefer structured backend responses so the frontend is easy to maintain.

Example:

```json
{
  "message": "I found a possible short-horizon order-book imbalance hypothesis...",
  "observations": [
    "..."
  ],
  "hypotheses": [
    "..."
  ],
  "artifacts": [
    {
      "id": "...",
      "filename": "strategy_orderbook_imbalance.py",
      "type": "python_strategy",
      "description": "...",
      "path": "..."
    }
  ],
  "tool_events": [
    {
      "tool": "profile_market_data",
      "status": "complete"
    }
  ]
}
```

Exact schema may differ, but keep frontend/backend communication explicit.

---

# Session Behavior

A chat session should remember recent conversation context.

It should also remember:

- which data files are selected
- retrieval index/session ID
- artifacts generated during the current session
- previous tool results when appropriate

Do not persist sensitive chat history indefinitely by default.

A simple in-memory session is acceptable for the first version.

---

# Suggested Feature Layout

The UI should fit naturally into the current resizable-panel application.

Do not redesign the existing app.

The smallest acceptable integration is to add one additional resizable panel or one contained child panel.

For example:

```jsx
<AIResearchPanel />
```

inside the existing application layout.

Keep styling local to:

```text
NEW_FEATURE_BY_CLAUDE_CODE/frontend/AIResearchPanel.css
```

Do not pollute `App.css` with a large block of feature-specific styles.

---

# Backend Startup

Prefer a design where the isolated AI backend can be started automatically with the Electron application using one tiny main-process integration.

For example, the existing Electron main process may call a single exported helper from the new feature directory:

```ts
startAIResearchService();
```

All spawn configuration, paths, logs, cleanup, and service-specific implementation should remain inside `NEW_FEATURE_BY_CLAUDE_CODE`.

If importing code from that location creates build problems, use the smallest alternative integration.

The Electron main file should not become the implementation of the AI feature.

The service should bind only to localhost, for example:

```text
127.0.0.1
```

Use a non-conflicting port.

The existing project already uses port `8000` for another FastAPI service, so DO NOT use port 8000.

Choose something like `8010`, with the value defined in one place.

Handle service cleanup when Electron exits.

---

# Dependencies

Keep AI dependencies isolated and documented.

Python requirements may include the current appropriate packages for:

- LangChain
- LangGraph if used
- LangSmith
- model-provider integration
- FastAPI/Uvicorn if using an HTTP service
- a lightweight retriever/vector-store dependency if needed
- optional Ollama integration
- minimal numerical/ML packages only where justified

Do not modify the project's main npm dependency list unless the frontend genuinely needs a package.

Do not install packages merely to make the resume look more impressive.

Every dependency should serve a real function.

---

# Implementation Sequence

Follow this order.

## Phase 1 — Inspect

Before editing anything:

1. inspect current renderer layout
2. inspect Workspace/global context
3. inspect Electron IPC/preload
4. inspect strategy runner
5. inspect FastAPI simulator
6. inspect representative JSONL schema
7. understand how a workspace path is stored

Do not assume paths or APIs.

## Phase 2 — Write a short implementation plan

Before changing code, print a concise plan including:

- files to create
- existing files to modify
- why each existing modification is unavoidable

The expected list of modified existing files should be very small.

## Phase 3 — Build isolated backend

Implement:

- provider initialization
- LangChain agent
- LangSmith tracing
- tools
- retrieval
- artifact generation
- controlled strategy testing
- local API

## Phase 4 — Build isolated frontend

Implement:

- data-file selection
- chat
- loading/tool state
- response rendering
- artifact actions

## Phase 5 — Minimal integration

Add the smallest necessary hooks into the existing app.

## Phase 6 — Verify

Run:

- existing tests if practical
- lint/type checking
- feature-specific tests
- backend smoke test
- one real chat request
- one data-inspection tool call
- one generated artifact
- one artifact validation/test action

Fix problems without unrelated refactoring.

---

# Definition of Done

The feature is complete when all of the following are true:

- [ ] Existing application still launches.
- [ ] Existing market tracking/workspace/replayer behavior still works.
- [ ] New AI code is overwhelmingly contained under `NEW_FEATURE_BY_CLAUDE_CODE`.
- [ ] Existing files contain only minimal integration edits.
- [ ] AI Research panel is visible.
- [ ] User can select existing workspace market-data files.
- [ ] User can send natural-language questions.
- [ ] A real LangChain pipeline handles requests.
- [ ] Agent uses at least several constrained tools.
- [ ] A retrieval/RAG path uses selected data without dumping full raw files into the prompt.
- [ ] Deterministic tools calculate numerical market facts where appropriate.
- [ ] LangSmith tracing is integrated and documented.
- [ ] At least one model provider works.
- [ ] Architecture supports local/open-source LLM use through Ollama or equivalent.
- [ ] Agent can generate a controlled file artifact.
- [ ] UI displays generated artifact.
- [ ] User can open/view the artifact.
- [ ] User can save/download it.
- [ ] User can explicitly add it to the workspace.
- [ ] Python artifacts can at least be safely validated/tested.
- [ ] No API key is exposed in the renderer or committed.
- [ ] No arbitrary shell/filesystem tool is exposed to the LLM.
- [ ] README explains setup and architecture.
- [ ] README explains LangChain, LangSmith, RAG, tools, and model-provider configuration.
- [ ] README includes example prompts.

---

# Quality Standard

This should be a real prototype, not resume theater.

It is better to implement:

- one useful LangChain agent,
- five narrow tools,
- one real retrieval path,
- one model provider,
- good LangSmith traces,
- and safe artifact generation

than to create a fake "multi-agent platform" with lots of abstractions that do nothing.

Do not call something "multi-agent" unless multiple independent agents actually exist and provide a justified benefit.

Do not add unnecessary abstractions.

Do not make claims about profitability.

Keep the code readable enough that a human developer can inspect the AI-generated implementation and understand what happened.

---

# Final Report Required From Claude Code

When finished, do NOT merely say "done."

Return a concise report with:

## 1. Architecture

Explain the request path from React -> local AI service -> LangChain -> tools/RAG -> model -> response.

## 2. Files created

List every file created under `NEW_FEATURE_BY_CLAUDE_CODE`.

## 3. Existing files modified

List every pre-existing repository file modified and explain exactly why it was necessary.

## 4. LangChain usage

Explain which LangChain/LangGraph abstractions are actually used.

## 5. LangSmith usage

Explain how tracing/evaluation is enabled and where to view/configure it.

## 6. RAG

Explain exactly what gets indexed/retrieved and how large raw JSONL files are kept out of the prompt.

## 7. Tools

List the tools the agent can call and their permissions.

## 8. Generated-file safety

Explain how artifact paths are sandboxed and how files move into the user's workspace.

## 9. Model providers

Explain how to run with the cloud provider and how to run with a local/open-source model.

## 10. How to run

Give exact commands.

## 11. Verification

List tests/checks actually run and their result.

## 12. Remaining limitations

Be explicit about what is prototype quality and what would need improvement before calling it production-ready.

---

# Final Constraint Reminder

Preserve the existing application.

The AI capability must look and behave like an isolated feature attached to the existing system, not like Claude Code rewrote the repository around itself.

When in doubt:

**new logic goes into `NEW_FEATURE_BY_CLAUDE_CODE`; existing files only get thin integration hooks.**

---
---

# UPDATE 2: Model Access Options (Claude Account Sign-In or Packaged Local Qwen)

This section was added after the first version of the feature was built. It extends that work.
Every rule above still applies, especially the repository-containment rule.

## Goal

The user must be able to choose, inside the AI Strategy Research panel, between exactly two ways
of powering the agent:

1. **Sign in with their own Claude account**, and have the agent use that account.
2. **Use a local open-source LLM packaged with the project**: Ollama running a Qwen model, with
   the runtime and model stored inside the project folder.

Neither option may require the user to paste an API key into the app.

## Option 1: Claude account sign-in

- Provide a **Sign in with Claude** button in the panel.
- Sign-in must use Anthropic's supported OAuth flow for API access: the Anthropic CLI
  (`ant auth login`), which opens the browser. The resulting profile is stored by the CLI in the
  user's standard Anthropic config location (`%APPDATA%\Anthropic` on Windows,
  `~/.config/anthropic` on macOS/Linux). The Anthropic SDK picks that profile up automatically.
- This is a Claude Console / API account; usage is billed to the API organization chosen during
  sign-in. Consumer claude.ai subscriptions (Pro/Max) cannot be used by third-party apps. The
  README and the UI must say this plainly rather than imply otherwise.
- If the `ant` CLI is not installed, the feature must obtain it automatically (official GitHub
  release for the user's OS, checksum verified) into a git-ignored folder inside
  `NEW_FEATURE_BY_CLAUDE_CODE`. Do not install anything system-wide.
- Show sign-in status: signed in / not signed in, verified with a real authenticated API call.
  Provide **Sign out**.
- Tokens must never reach the renderer, logs, git, or generated strategy processes.
- An `ANTHROPIC_API_KEY` in the environment may keep working as a developer fallback, but it is
  not one of the two user-facing options.

## Option 2: Local Ollama + Qwen, packaged in the project folder

- The Ollama runtime and the Qwen model weights live inside
  `NEW_FEATURE_BY_CLAUDE_CODE/` in a git-ignored runtime folder. They are several GB, so they
  must never be committed. They are downloaded on first use from official sources (Ollama GitHub
  release, Ollama model registry).
- Provide an **Install local model** button with download progress, plus a CLI equivalent for
  setting up without the UI.
- The packaged Ollama must run privately for this app: bound to `127.0.0.1` on a non-default
  port (not 11434, so it never collides with a separately installed Ollama), with its model
  directory set to the project folder.
- The AI service starts and stops the packaged Ollama itself. It must stop when the app quits.
- Default model: a Qwen model with tool-calling support that runs acceptably on a CPU-only
  machine (Qwen 3.5 4B). Allow a larger Qwen via configuration.
- The local agent must use the same tools, sandboxing, and structured response as the Claude
  path. Adjust only what local models need (context window, loop limits).
- Show status: not installed / installing (with progress) / starting / ready.

## UI requirements

- A compact **AI model** selector at the top of the panel with the two options.
- Remember the user's choice between launches (git-ignored settings file inside the feature dir).
- Switching options starts a fresh conversation.
- Disable Send until the selected option is ready, with a clear reason.

## Containment

- **No changes outside `NEW_FEATURE_BY_CLAUDE_CODE`** are expected for this update. The existing
  `main.ts` hook already starts the AI service, and the service manages Ollama and the Anthropic
  CLI itself. If a change outside the directory turns out to be unavoidable, keep it to a few
  lines and justify it in the final report.
- Ignore runtime downloads, model weights, and settings via the feature's own `.gitignore`.

## Verification

- Feature tests updated and passing (provider selection, Claude credential handling, local
  runtime management with mocked downloads).
- Actually install the packaged Ollama + Qwen on this machine and run at least one real local
  agent request end to end, including tool calls and an artifact.
- Verify the Claude sign-in path as far as possible without the user's credentials: CLI
  download, checksum, launch of the login flow, and correct "not signed in" status.
- Rebuild the Electron app and confirm the panel shows the selector.

## Final report

Update the README, list every file created or changed, report which steps were verified and
which were not, and state download sizes and expected local performance honestly.

---
---

# Status note: full refactor (after UPDATE 2)

The project was later refactored end to end, at the developer's request, so that the complete
pipeline works:

```text
collect live Kalshi data -> write a strategy -> test it in the Replayer -> ask the AI to improve it -> retest
```

As part of that, the isolated `NEW_FEATURE_BY_CLAUDE_CODE` directory described above was merged
into the app's single Python engine:

| Was | Now |
|---|---|
| `NEW_FEATURE_BY_CLAUDE_CODE/backend/*` | `reactWebsite/electron-react/engine/research/` |
| AI routes on port 8010 | routes under `/ai/...` on the engine (port 8000) |
| `frontend/` | `src/renderer/components/ai/` |
| `runtime/` (Ollama, Qwen, Anthropic CLI) | `engine/runtime/` |
| the AI's standalone `--data` test scripts | real backtests in the engine's Kalshi-compatible simulator |

The rules in this document still apply to the AI assistant:

- narrow tools only;
- sandboxed artifacts, added to the workspace only on an explicit click;
- no keys in the renderer;
- never promise profitability.

See the repository `README.md` and `reactWebsite/electron-react/engine/README.md`.
