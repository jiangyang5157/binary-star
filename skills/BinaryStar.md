# Protocol: @BinaryStar

This protocol defines how the Antigravity Agent replicates the Binary Star reasoning loop within the chat window.

## Usage
`@BinaryStar(data_root="data/prod", send_email=False, symbol="BTCUSDT", timestamp=None)`

## Parameters
- **data_root**: Path to the repository data directory. Default: `"data/prod"`.
- **send_email**: Boolean to trigger email dispatch. Default: `False`.
- **symbol**: Trading pair. Default: taken from `global_config.yaml`.
- **timestamp**: ISO string or `None`.
    - If `None`: Agent will perform a Live Recon for "Now" using `scripts/market_recon.py`.
    - If string: Agent will perform a Forensic Recon for that timestamp using `scripts/market_recon.py --timestamp <ts>`.

## Logic Anchoring (Absolute Law)
- **Shared Truth**: Data units and the debate structure MUST align with `src/agent/prompts/binary_star.md`.
- **Analyst Protocol**: Initial planning and synthesis MUST strictly implement the **Confidence Calculus (Dimensions 1-4)** and **Shield Law** from `src/agent/prompts/session.md`.
- **Critic Protocol**: Risk auditing MUST use the `CRITIC_CODES` and Veto levels defined in `src/agent/prompts/critic.md`.

## Agent Execution Logic
1.  **Initialize Context**: Load `strategy_config.yaml` and `global_config.yaml`. Reference the core prompts mentioned above as the "Instructional Ground Truth."
2.  **Data Acquisition**:
    - **ACTION**: Run `python scripts/market_recon.py` to capture the current market topography.
    - **FORENSIC**: Use the `--timestamp` flag if a specific historical moment is requested.
3.  **Adversarial Loop**:
    - **Round 1 (Analyst)**: Follow `src/agent/prompts/session.md`.
    - **Round 1 (Critic)**: Follow `src/agent/prompts/critic.md`.
    - **Reconciliation**: Apply `[TACTICAL_REPAIR_PATTERNS]` from the prompts.
4.  **Serialization**: Save a 100% compliant JSON to `data/test/sessions/`.
5.  **Notification**: If `send_email` is True, use `run_session.py --email` concepts to simulate notification (Agent will not send real emails but will confirm the content).
