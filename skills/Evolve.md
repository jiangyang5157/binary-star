# Protocol: @Evolve

This protocol defines how the Antigravity Agent replicates the Universal Evolver meta-optimization process.

## Usage
`@Evolve(data_root="data/test", sample=10)`

## Parameters
- **data_root**: **REQUIRED**. Path to the directory containing `audits/` and `sessions/`.
- **sample**: Number of latest audit sessions to analyze. Default: taken from `global_config.yaml` (usually 10).

## Agent Execution Logic
1.  **Batch Ingestion**:
    - Scan `data_root/audits/` for the latest `.json` reports.
    - Focus on trades where `outcome` is "SL_HIT", "NEITHER", or "NEUTRAL" (missed opportunities).
2.  **Pathology Diagnosis**:
    - **Logic Anchoring**: All analytical logic MUST be derived exclusively from `src/agent/prompts/evolver.md`. 
    - Evaluate `LOGIC_MACROS` (e.g., `IS_PHANTOM_ORDER_BIAS`) based on the audit reports.
    - Identify systemic failure patterns in the Analyst/Critic debate history.
3.  **Mutation Generation**:
    - Generate a `rationale` for mutation.
    - Produce a `config_patch` (YAML-compatible) or `semantic_refinement` (Markdown-ready).
4.  **Serialization**: 
    - Display the proposed evolution plan in the chat.
    - **Physical Persistence**: Save the resultant JSON to `data_root/evolution/proposals/{symbol}_evolution_{timestamp}.json`.
    - **Format Compliance**: Ensure the output strictly follows the `rationale`, `config_patch`, and `semantic_refinement` schema.
