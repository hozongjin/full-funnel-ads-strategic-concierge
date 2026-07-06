# Project DNA PRD: Full-Funnel Ads Strategic Scenario Concierge
**Subtitle**: Collapsing Strategic Latency via Specialized Agentic SQL and Deterministic Modeling

## 1. Executive Summary & Business Statement
*   **Problem**: High-velocity ads businesses face "Strategic Latency" and "Analytical Inconsistency." FP&A managers lose hours to manual data pulls, while probabilistic LLMs often generate inconsistent SQL or visual conclusions for identical queries.
*   **The Solution**: A specialized multi-agent factory that uses MCP for data reach, Persistent Memory for visual consistency, and a Dedicated SQL Specialist Agent to ensure 100% mathematical and structural accuracy.

## 2. Technical Architecture (The Factory Model)
The system is built as a Level 3 Collaborative Multi-Agent System using the Google Agent Development Kit (ADK).
*   **IntegrityAgent (The Forensic Specialist)**: Hunts for "data smells" (NULLs) in critical fields. It serves as the initial gatekeeper for data trust.
*   **DataArchitectAgent (The SQL Specialist)**: Translates fuzzy user intent into precise BigQuery SQL via the BigQuery MCP server. It utilizes a "Tool-as-Template" pattern to minimize syntax errors.
*   **CalculationAgent (The Deterministic Core)**: Bypasses probabilistic reasoning to execute fixed financial algorithms for ROAS and revenue projections.
*   **ConciergeAgent (Consistency Orchestrator)**: Translates retrieved data into Deterministic A2UI templates. It relies on Memory Anchors to ensure the same query type always yields the same visual layout.
*   **PolicyAgent (The HITL Gatekeeper)**: Manages high-stakes actions by generating a plain-English "Vibe Diff" and requiring explicit human sign-off via `request_confirmation()`.

## 3. Project Scope & Tech Stack (Kaggle-Native Requirements)
*   **Infrastructure**: Must run entirely within a Kaggle Notebook using `InMemorySessionService` for free state management.
*   **Data Tier**: Must use the BigQuery Sandbox with the GA4 public dataset in read-only mode to ensure zero cost.
*   **Model Routing**: Default execution is routed to Gemini 1.5 Flash for low-cost routing and integrity tasks.

## 4. Mapping the Multi-Agent Flow & Human Intervention
The following flowchart describes the Sequential Orchestration of your agents. Each step includes a "Validation Check" that defines the path for failure or human intervention.

*   **Stage 1: Intent Entry**
    *   *User Action*: Inputs a strategic "What-If" scenario (e.g., "If we shift 20% of Awareness spend to Conversion, what is the ROI impact?").
*   **Stage 2: Forensic Data Check (IntegrityAgent)**
    *   *Process*: Agent queries BigQuery via MCP to check for NULLs in `purchase_revenue` or `session_start` events.
    *   *Validation Check*: Does the dataset meet the trust threshold (e.g., <20% NULL values)?
        *   **PASS**: Move to Stage 3.
        *   **FAIL (Human Intervention Required)**: The agent triggers a "Data Integrity Warning" and pauses the session. The user must choose to: (A) Abort, (B) Use 30-day averages to fill gaps, or (C) Exclude null rows.
*   **Stage 3: SQL Translation (DataArchitectAgent)**
    *   *Process*: Translates the intent into a BigQuery SQL script using pre-defined templates in its `SKILL.md`.
    *   *Validation Check*: Is the intent clear enough to generate a valid SQL query?
        *   **PASS**: Move to Stage 4.
        *   **FAIL (Inversion & Recovery)**: If the intent is ambiguous (e.g., "Which 'sources' do you mean?"), the agent invokes Inversion & Recovery to force the human to clarify assumptions before execution.
    *   *Transparency Step*: The agent must display the specific SQL query for human auditing.
*   **Stage 4: Deterministic Modeling (CalculationAgent)**
    *   *Process*: Receives the retrieved dataset and runs fixed financial math (ROAS = Revenue / Spend).
    *   *Guaranty*: Identical inputs always produce identical scores to maintain trust.
*   **Stage 5: Generative UI Composition (ConciergeAgent)**
    *   *Process*: Retrieves a Visual Anchor from the Memory Bank. If a "Funnel Comparison" was used for this query before, it uses the same A2UI template.
    *   *Validation Check*: Does the generated A2UI pass the JSON-Schema validator for your catalog?
        *   **PASS**: Render the interactive dashboard with "Spend Sliders."
        *   **FAIL**: The agent enters an Auto-Refactoring loop to fix the malformed JSON without bothering the user.
*   **Stage 6: Strategic Sign-Off (PolicyAgent & HITL)**
    *   *Process*: Generates a "Vibe Diff"—a plain-English summary of the proposed budget reallocation.
    *   *HITL Gate*: Invokes `request_confirmation()`. The entire workflow pauses and saves state.
    *   *Final Decision*:
        *   **APPROVE**: The user clicks "Approve," and the agent finalizes the simulation and generates a "Budget Memo" artifact.
        *   **REJECT**: The user provides a correction (e.g., "Try it with 15% instead"), which clusters as a labeled failure for future agent training.
