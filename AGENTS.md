# HB Pitch Lab agent execution contract

Read `OPERATIONS_MANUAL.md`, `ROADMAP.md` and `MODULE_RTL.md` before changing this project. Preserve the distinction between module benchmarks, estimated PPA, reported PPA and physical signoff.

## Required workflow

1. Inspect Git status and preserve unrelated user changes.
2. Select explicit design/policy/cost inputs. Change configuration for new objectives; do not rewrite the optimizer to force a preferred result.
3. Use a new output directory for every run:
   `python3 quality_check.py run --design examples/modules.json --policy examples/optimization_ppa.json --out runs/ppa_001`
4. Check its exit code, then execute:
   `python3 quality_check.py verify --run runs/ppa_001`
5. Completion requires both exit codes 0 and Q01–Q09 all PASS. `optimize.py` alone is exploratory and does not satisfy completion.
6. Preserve `execution_logs/history.jsonl` and each run's `events.jsonl`. Never erase failed runs, forge tool output, edit hashes, skip a required check or silently relax constraints. Missing tools, timeout, no feasible solution and NOT_RUN are not PASS.
7. Keep the full run locally. Commit a compact evidence archive under `execution_logs/` when delivering an authorized change, following manual section 10. Never commit `.tooldeps`, virtual environments, caches or large generic netlists.
8. Synchronize ROADMAP.md when capabilities, model scope or quality checks change. Add meaningful regression checks for mathematical/RTL behavior changes.
9. Commit/push only when authorized by the user; do not force-push. Repository visibility and external sharing are not changed by optimization.

## Scientific requirements

- State units, objective direction, normalization, feasible search scope and data provenance.
- The exhaustive optimum is only for the enumerated grid and supplied model; never claim a silicon optimum from synthetic coefficients.
- `area_mm2` is summed module cell/macro area. Never add HB slot area to it and call that die footprint.
- `optimization_binding.json.effective_metrics` contains the selected PPA adapter results. The RTL manifest retains base-model metrics for backward compatibility.
- Resource estimates do not provide setup WNS. Reported-PPA mode requires complete point-table data and a nonnegative WNS constraint, but is still not signoff.
- Any new module/precision/connection needs implementation, valid parameter/port contracts, an evaluation adapter and tests. Floating-point semantics are not achieved by changing integer DATA_W.

## Final handoff

Report run ID/path, input files, objectives/constraints, cost quality, candidate counts, selected point ID and effective metrics, all nine QC outcomes, verify result and material limitations. If commit/push was requested, report the resulting commit and remote branch after verifying them.
