# Local CSV usage history

Both `agents.supervisor.pipeline.handle_question()` and `agents.graph.graph.run()`
automatically append a consumption record after each run. The existing CLI
commands work without extra arguments. Logging makes no model calls and does
not change review/retry settings.

Open these local files in Excel, Numbers or another CSV viewer:

| File | Contents |
| --- | --- |
| `logs/usage/runs.csv` | One row per executed question, including failures |
| `logs/usage/calls.csv` | Stage/task usage entries linked by `run_id` |

The files use UTF-8 with a BOM for Excel. Numeric columns can be summed or
filtered. Format `estimated_cost_usd` to six decimal places to see small costs.
Questions containing commas or newlines are quoted correctly; text that looks
like a spreadsheet formula is escaped. History and its lock file are ignored by
Git, so each teammate keeps their own local log.

## What to look at

In `runs.csv`, filter by `pipeline` (`supervisor` or `graph`), `variant`
(`A_baseline` or `B_decomposition`), date, or `self_check`. Compare
`estimated_cost_usd`, `model_calls`, tokens and `seconds`. `status` indicates
whether execution completed, completed with errors, or failed; a completed run
can still have a `weak` self-check. `retry_cycles` is P3's review-loop retry
count, not the number of model calls, and is blank for the sequential pipeline.

Filter `policy_abstained=True` to find runs where a policy attempt returned
`ABSTAIN`. `policy_outcomes` stores each policy task's decision and reason as
JSON, with its task ID and attempt number, including abstentions followed by
successful retries. The returned bundle's `policy_agent` steps also contain
`decision` and `reason`. `answer_declined` records the final answer's separate
decline flag: a mixed question can have a policy abstention and still have
supported price results. Abstention is an expected outcome, not an execution
error. If no policy decision was reported, the policy columns are blank.

Pricing rates and the configured model are saved in every summary row so future
config changes do not obscure how that row was priced. `logged_at_sgt` is the
append time in Singapore time; for imported traces it is the import time, not
the original execution time.

In `calls.csv`, filter by the same `run_id` to see router, price extraction,
policy assessment, synthesis and self-check costs. Task calls include `task_id`
and their `attempt`; other stages use their occurrence number within the run.
Each row represents a usage entry, and `model_calls` may be greater than one
when P5 has aggregated multiple assessor calls. Sum `model_calls`, not CSV rows,
to count reported calls. A code-only check has no model usage row.

`usage_incomplete=True` means usage or pricing may be missing, or execution/review
reported an error. Unknown counts/costs are blank when nothing was reported;
partially reported totals are lower bounds, not complete billing figures.
Unreported failed requests and SDK retries may still cost money. Cache discounts
are not modeled. The configured model/rates describe the application's pricing
assumption; these logs do not retrieve billing records from the provider.

## Settings and per-request override

```yaml
usage_logging:
  enabled: true
  directory: logs/usage
```

Relative directories resolve against the repository root, independent of the
shell's working directory. A different directory starts a separate history.
Existing history is preserved. The previous `runs.csv` header is automatically
upgraded atomically on the next write; the new outcome fields on historical rows
remain blank because their values are unknown. Other mismatched CSV headers are
reported rather than silently mixed with a new schema. Writes are serialized
across threads/processes using a local file lock. Keep CSVs writable while
running questions; if a viewer locks them, close it and reopen after the run.
An actual logging failure emits a warning and preserves the answer or original
pipeline exception.

Disable logging globally with `enabled: false`, or for one call:

```python
from agents.graph.graph import run
state = run(question, log_usage=False)
```

The sequential pipeline accepts the same flag. `log_usage=True` explicitly
enables logging for a call even when the config disables it. Successfully saved
runs return `usage_tracking`, including `run_id`, `summary_csv` and `calls_csv`.
Failures before an answer still record any usage reported to the outer collector;
unreported usage remains unknown. A forced process termination may prevent the
final record from being written.

## Saved trace imports

A saved development trace can be imported without rerunning the model:

```sh
python -m agents.supervisor.usage_log import-trace evaluation/diagnostics/p3_decomposition_smoke_20261029.json --pipeline graph
```

Imported rows use `source=trace_import`; new executions use `source=live_run`.
Reimporting the same trace for the same pipeline does not add a second row.
Imports are priced with the configuration at import time, so they are a
reconstruction rather than the original billing record. The initial example row
is the saved P3 smoke test, not another paid run. To total only new executions,
filter to `source=live_run`. Do not import a trace already recorded automatically
unless you intend to retain a second, explicitly labelled representation.

Ablation runs through the public entry points are logged as ordinary executions.
The ablation's `runs.jsonl` bundles retain `usage_tracking.run_id`; use it to
join the two views. Their costs describe the same executions, so do not add
history totals to ablation totals.

Offline tests disable persistent logging by default so fixture questions do not
enter the user's history. Logging tests enable it only in temporary directories.

For a unified experiment UI, the [MLflow integration](mlflow_experiments.md)
records the same executions with configuration snapshots, local compute metrics
and later quality grades. It keeps CSV as an export, not another billable run.
