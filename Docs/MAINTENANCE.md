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

4. Copy `.env.example` to a new file named `.env` and paste in the real API key. Never commit `.env`.

## Standing rules

1. **Activate the environment** (`source .venv/bin/activate`) each time you open a terminal.
2. **Adding a package:** add its pinned line (`name==exact.version`) to `requirements.txt` in the same pull request that uses it.
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

When a teammate's merged pull request changes `requirements.txt`, refresh your environment after pulling:

```
git pull
pip install -r requirements.txt
```

## Where things go

| Folder        | Purpose                                      |
| ------------- | -------------------------------------------- |
| `data/`       | Datasets (`data/raw/` is git-ignored)        |
| `agents/`     | Agent code                                   |
| `rag/`        | Retrieval-augmented generation code          |
| `evaluation/` | Evaluation scripts and results               |
| `ui/`         | User interface                               |

Each folder has its own `README.md`; keep it updated as the folder grows.

## Secrets and ignored files

- `.env` holds real secrets and is never committed. `.env.example` is the template; if you add a new variable, add it there too (with a placeholder value only).
- `.venv/` and `data/raw/` are git-ignored. Do not force-add them.
