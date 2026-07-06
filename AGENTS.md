# Project DNA - Agent Instructions

This file defines the tech stack, naming conventions, and hard project rules including Zero-Cost constraints and mandatory human-in-the-loop (HITL) gates.

## Tech Stack
- **Core Language**: Python
- **Database/Analytics**: Google BigQuery
- **Package Management**: uv / pip

## Naming Conventions
- **Python Files**: snake_case (e.g., `data_processor.py`)
- **SQL Files/Tables**: snake_case (e.g., `user_events`)
- **Classes**: PascalCase (e.g., `BigQueryConnector`)
- **Functions/Variables**: snake_case (e.g., `execute_query()`)

## Hard Project Rules & Constraints

### 1. Zero-Cost Constraints
- All operations, APIs, and cloud resources must run within the free tier or minimal cost limits.
- No paid API keys or services should be consumed without explicit permission or unless specified in `.env`.
- Optimize queries and data sizes to minimize BigQuery slot usage/cost.

### 2. Mandatory Human-In-The-Loop (HITL) Gates
- **PRD/Spec Approval**: The PRD must be approved by the user before any implementation begins.
- **Schema Changes**: BigQuery schema definitions or changes must be reviewed and approved by the user.
- **Production Deployments / Cost Actions**: Any action triggering external deployments or billing must be approved.

---

## The 3-Layer Architecture

**Layer 1: Directive (What to do)**
- Live in `directives/` as Markdown SOPs.
- Define the goals, inputs, tools/scripts to use, outputs, and edge cases.

**Layer 2: Orchestration (Decision making)**
- The AI agent's role: intelligent routing.
- Read directives, call execution tools in the right order, handle errors, ask for clarification, update directives with learnings.

**Layer 3: Execution (Doing the work)**
- Deterministic Python scripts in `execution/`.
- Environment variables, api tokens, etc., are stored in `.env`.
- Handle API calls, data processing, file operations, database interactions.

## Operating Principles

1. **Check for tools first**: Before writing a script, check `execution/`. Only create new scripts if none exist.
2. **Self-anneal when things break**: Fix scripts, test, and update directives with learnings (e.g. rate limits, edge cases).
3. **Update directives as you learn**: Keep directives as living documents.

## File Organization
- `.tmp/` - Intermediate/temporary files (never commit).
- `execution/` - Python scripts.
- `directives/` - SOPs in Markdown.
- `.env` - Environment variables and keys.

## Coding Preferences
- Prefer simple solutions and avoid code duplication.
- Write code taking envs (dev, test, prod) into account.
- Avoid files over 200-300 lines of code.
- Mocking data is for tests only (never dev or prod).
- Never overwrite `.env` without confirmation.
