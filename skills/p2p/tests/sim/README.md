# p2p stress-simulation

Live multi-agent integration test for the `skills/p2p` skill. Three worker
agents run a token-ring counter under a scripted catalog of 10 disruptions
plus 1 probe. The driver scores from per-worker JSONL logs.

## Layout

See spec at `$OBSIDIAN/plans/p2p-sim-design-2026-05-27.md`.

- `lib/`            — testable Python helpers
- `bin/`            — CLIs invoked by the LLM-driven driver and workers
- `catalog.yaml`    — disruption catalog
- `worker_prompt.md.tmpl` / `driver_prompt.md` — LLM agent prompts
- `runs/<run_id>/`  — per-run JSONLs and run_summary (gitignored)

## How to run

1. Install deps (in a venv or system-wide):

   ```
   cd skills/p2p/tests/sim
   pip install pyyaml ulid-py pytest
   ```

2. Run unit tests:

   ```
   python -m pytest tests/ -v
   ```

   All tests must pass before running the simulation.

3. Launch a sim run:

   ```
   python3 bin/run_sim.py
   ```

   This generates a `run_id`, creates `runs/<run_id>/`, renders
   `driver_prompt.md`, and prints the path. Spawn a fresh `claude` pane
   in cmux (workspace: `p2p-sim`), title it `sim_driver`, and feed it the
   rendered prompt as its first user-turn input. The driver will spawn
   the workers and execute the catalog.

4. After the run completes, read `runs/<run_id>/run_summary.json`.

## Manual baseline smoke (step 1 only)

For a quick check that the harness works without running the full catalog:

1. Launch `run_sim.py` as above.
2. In the rendered driver prompt, comment out steps 2–11 from `catalog.yaml`
   (or pass `--steps 1` if implemented).
3. Verify run_summary shows `pass_fail.step_1_baseline=pass` and the 3
   worker JSONLs contain `event=send_result` for the driver's PRIME bootstrap
   contacts and `event=inbound_frame` for the counter ring lap.
