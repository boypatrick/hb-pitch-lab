# Fixed quality check execution report

Run: 20260908T193432Z-db2bbfeabb50
Status: FAIL
Selected: None
Source SHA256: 9a1b767404a51650ff8e92b01f9df3a9ff05f1354f4eb18b95958fe7e982fddd

| ID | Check | Status | Detail |
|---|---|---|---|
| Q01 | input_schema_and_provenance | PASS |  |
| Q02 | python_regression_tests | PASS |  |
| Q03 | exhaustive_optimization | FAIL | NO_FEASIBLE_SOLUTION; constraints are not automatically relaxed |
| Q04 | deterministic_replay | NOT_RUN |  |
| Q05 | selected_rtl_integrity | NOT_RUN |  |
| Q06 | rtl_simulation_and_selected_parameters | NOT_RUN |  |
| Q07 | generic_synthesis_and_resource_match | NOT_RUN |  |
| Q08 | constraints_and_thermal_conservation | NOT_RUN |  |
| Q09 | completion_artifacts_and_source_stability | NOT_RUN |  |

Software/RTL/generic synthesis QC; not PPA or thermal signoff.
