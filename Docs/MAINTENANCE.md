# Team Maintenance Guide

How to keep the repository and environment consistent as the team works. The repository is already set up; this covers day-to-day use.

## Joining the project (new teammate)

1. Check your tools (on a Mac, use `python3` if `python` fails):

   ```
   python --version
   git --version
   ```

2. Clone the repository and enter it:

   ```
   git clone <repository link>
   cd <repository name>
   ```

3. Build the environment (on Windows, activate with `.venv\Scripts\activate`):

   ```
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   You should see `(.venv)` at the start of your prompt.

   For local CPU/memory measurements and Excel report exports, also install
   the optional dependencies:

   ```
   pip install -r requirements-experiments.txt
   ```

4. Copy `.env.example` to a new file named `.env` and paste in the real API key. Never commit `.env`.

## Standing rules

1. **Activate the environment** (`source .venv/bin/activate`) each time you open a terminal.
2. **Adding a package:** add its pinned line (`name==exact.version`) to `requirements.txt`, or `requirements-experiments.txt` for optional evaluation/export dependencies, in the same pull request that uses it.
3. **Settings live in `config.yaml`**, never typed into code. This covers model version, temperature, seed and `top_k`.
4. **No direct pushes to `main`.** All changes go through a pull request.

## Day-to-day workflow

1. Update your local copy before starting work:

   ```
   git checkout main
   git pull
   ```

2. Create a branch for your change:

   ```
   git checkout -b <short-description>
   ```

3. Make your changes, then check what will be committed:

   ```
   git status
   ```

   Confirm `.env` and `.venv` are **not** listed.

4. Commit and push your branch, then open a pull request on GitHub:

   ```
   git add .
   git commit -m "<what you changed>"
   git push -u origin <short-description>
   ```

## Keeping your environment in sync

When a teammate's merged pull request changes the requirements, refresh your environment after pulling:

```
git pull
pip install -r requirements.txt
```

If you use the optional evaluation/export tools, also refresh
`requirements-experiments.txt` after its changes.

## Where things go

| Folder        | Purpose                                      |
| ------------- | -------------------------------------------- |
| `data/`       | Datasets (`data/raw/` is git-ignored)        |
| `agents/`     | Agent code                                   |
| `src/`       | Policy retrieval, evidence assessment and policy RAG |
| `scripts/`   | Data preparation and evaluation utilities |
| `evaluation/` | Evaluation scripts and results               |
| `ui/`         | User interface                               |
| `tests/`     | Offline regressions and integration checks |
| `Docs/`      | Current guides, evaluation workflow and change history |
| `logs/usage/` | Local CSV question, cost and policy-outcome history (ignored by Git) |

Use the [pipeline map](end_to_end_overview.md) to find the guide that owns each
stage. Some folders have their own README; others are documented here.

## Keep documentation aligned with changes

Update documentation in the same change as behavior, configuration, CLI or
output-schema changes. Check the implementation and `config.yaml` rather than
copying a default from an older guide.

| Change | Documentation to update |
| --- | --- |
| Routing, synthesis, clarification, nearby-area estimates | [supervisor_guide.md](supervisor_guide.md) and active prompts |
| Policy retrieval, assessor decisions, corpus handoff | [policy_agent_rag.md](policy_agent_rag.md), [data_prep_policy_handoff.md](data_prep_policy_handoff.md) |
| Batch execution, grading, comparisons | [supervisor_ablation.md](supervisor_ablation.md) |
| Stage diagnostics, judge context, compact workbook | [stage_evaluation.md](stage_evaluation.md), [llm_judge_validation.md](llm_judge_validation.md) |
| CSV run/call history or outcome fields | [usage_logging.md](usage_logging.md) |
| New entry point or moved document | [end_to_end_overview.md](end_to_end_overview.md), root README and referring links |

After editing, check relative links, verify documented CLI arguments with
`--help` or an offline dry run, and add a dated [changelog](CHANGELOG.md) entry
with contributor identification, what changed, why and the checks performed.
Keep historical findings labelled as snapshots; do not present old model-judge
scores as current independently verified accuracy. Generated report directories
are chosen outputs, not files guaranteed to exist in every clone.

`python tests/run_all.py` runs the maintained P5/supervisor integration list.
Newer offline report and judge-tool tests can also be run directly:

```
python -m pytest tests/test_stage_diagnostics.py tests/test_stage_review_excel.py tests/test_excel_export.py tests/test_experiment_metadata.py tests/test_judge_tools.py
```

## Secrets and ignored files

- `.env` holds real secrets and is never committed. `.env.example` is the template; if you add a new variable, add it there too (with a placeholder value only).
- `.venv/` and `data/raw/` are git-ignored. Do not force-add them.
