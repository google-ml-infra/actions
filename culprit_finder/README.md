# Culprit Finder

A tool to find the exact commit in an open-source GitHub repository responsible for a Continuous Integration (CI) failure.

Culprit Finder helps developers identify regression commits by automating the bisection process. It interacts with GitHub Actions to run workflows on specific commits between a known "good" state and a known "bad" state.

## Installation

This tool requires Python 3.11 or higher.

You can install the package locally using pip:


```shell
pip install .
```

## Authentication

To use this tool, you must be authenticated with GitHub. You can do this in one of two ways:

1.  **GitHub CLI**: Ensure you are logged in via the GitHub CLI.
    ```shell
    gh auth login
    ```

2.  **Environment Variable**: Set the `GH_TOKEN` environment variable with a personal access token.
To avoid saving the token in your shell's history, it is recommended to
        disable history before setting the environment variable and re-enable it
        afterward.


```bash
# Disable shell history
set +o history

# Set the token
export GH_TOKEN="token"

# Re-enable shell history
set -o history
```


## Usage

After installation, you can run the tool using the `culprit-finder` command.

```shell
culprit-finder [URL] --repo <OWNER/REPO> --start <GOOD_SHA> --end <BAD_SHA> --workflow <WORKFLOW_FILE> [FLAGS]
```


### Arguments

- `URL`: (Optional) A GitHub Actions Run or Job URL
(e.g., `https://github.com/owner/repo/actions/runs/12345` or `.../job/67890`) from a failed workflow run.
If provided, the tool infers the repository, workflow name, job name (if applicable), and the start and end SHAs.
- `--repo`: The target GitHub repository in the format `owner/repo`. (Optional if URL is provided).
- `--start`: The full or short SHA of the last known **good** commit. (Optional if URL is provided).
- `--end`: The full or short SHA of the first known **bad** commit. (Optional URL is provided).
- `--workflow`: The filename of the GitHub Actions workflow to run (e.g., `ci.yml`, `tests.yaml`).
(Optional if URL is provided).
- `--job` (Optional): The specific job name within the workflow to monitor for pass/fail.
If not provided, the tool checks the overall workflow conclusion.
- `--clear-cache`: (Optional) Deletes the local state file before execution to start a fresh bisection.
- `--no-cache`: (Optional) Disabled cached results. This will run the workflow on all commits.

### State Persistence and Resuming

Culprit Finder automatically saves its progress after each commit is tested. If the process is interrupted (e.g., via `CTRL+C`) or fails due to network issues, you can resume from where you left off.

1. **Automatic Save**: The state is stored locally in `~/.github_culprit_finder/`.
2. **Resume**: When you restart the tool with the same `--repo` and `--workflow`, it will prompt you to resume from the saved state.
3. **Caching**: Results for individual commits are cached. If the bisection hits a commit that was already tested in a previous session, it will use the cached "PASS" or "FAIL" result instead of triggering a new GitHub Action.


### Example

```shell
culprit-finder
--repo google-ml-infra/actions
--start a1b2c3d
--end e5f6g7h
--workflow build_and_test.yml
```

Using a URL to infer details (e.g., starting with a known bad run):
```shell
culprit-finder https://github.com/google-ml-infra/actions/actions/runs/123456789
```

Using a Job URL to target a specific failure:
```shell
culprit-finder https://github.com/google-ml-infra/actions/actions/runs/123456789/job/987654321
```

## Developer Notes

### Prerequisites

- **Python**: >= 3.11
- - **uv**: The project uses `uv` for dependency management.
- **GitHub CLI (`gh`)**: This tool relies on the GitHub CLI to interact with the GitHub API and trigger workflows. Ensure `gh` is installed and you are authenticated (`gh auth login`).

### Setting up the Development Environment

1. Clone the repository.
2. Install the package in editable mode with development dependencies:

```shell
uv sync
```

### Pre-commit Hooks

This project uses `pre-commit` to enforce code quality and formatting.

1.  **Install the git hooks:**
    ```shell
    uv run pre-commit install
    ```

2.  **Run hooks manually (optional):**
    ```shell
    uv run pre-commit run --all-files
    ```


### Running Tests

The project uses `pytest` for testing. You can run it via `uv`:

```shell
uv run pytest
```
