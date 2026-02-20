# setup-uv-python

Composite action for installing Python via `uv`.
`uv` itself is also installed, via
[`astral-sh/setup-uv`](https://github.com/astral-sh/setup-uv).

## Requirements

- `bash` must be present on the runner image
  (all `run` steps here use `shell: bash`).

## Inputs

| Input                   | Required | Default   | Description                                     |
|-------------------------|----------|-----------|-------------------------------------------------|
| `python-version`        | Yes      | N/A       | Python version to install.                      |
| `summary-label`         | Yes      | N/A       | Label used in GitHub step-summary output.       |
| `uv-version`            | No       | `0.10.4`  | `uv` version to install.                        |
| `enable-cache`          | No       | `true`    | Enable `uv` cache restore/save behavior.        |
| `cache-python`          | No       | `true`    | Cache uv-managed Python installations.          |
| `cache-dependency-glob` | No       | `''`      | Files used by `setup-uv` to compute cache keys. |
| `cache-suffix`          | No       | `''`      | Optional suffix for cache busting/debugging.    |

## Outputs

| Output       | Description                                                  |
|--------------|--------------------------------------------------------------|
| `python-bin` | Full path to the selected Python interpreter in the CI venv. |

## Ways to run Python from within the workflow

- `python -m <module>`
- `python3 -m <module>`
- `${{ steps.<setup_step_id>.outputs.python-bin }} -m <module>`
- `$PYTHON_BIN -m <module>` (bash) or `$env:PYTHON_BIN -m <module>` (PowerShell)

## Environment changes

- Exports `PYTHON_BIN` and `VIRTUAL_ENV` for subsequent steps.
- Updates `PATH` to include the venv binary directory.

## Usage example (no debug output)

```yaml
- name: Set up uv-managed Python
  id: setup_python
  # Recommended: pin to an immutable commit SHA.
  uses: google-ml-infra/actions/setup-uv-python@<SHA>
  # Optional while iterating: use a branch or tag instead of a SHA.
  # uses: google-ml-infra/actions/setup-uv-python@main
  with:
    python-version: '3.12'
    summary-label: 'unit-tests' # optional
    cache-dependency-glob: |    # optional
      pyproject.toml
      uv.lock

- name: Install dependencies
  run: uv pip install -r requirements.txt

- name: Run tests
  run: |
    python -m pytest
    python3 -c "import sys; print(sys.version)"
```

If you need the explicit interpreter path:

```yaml
- run: ${{ steps.setup_python.outputs.python-bin }} -m pip --version
```

## Notes

- If `cache-dependency-glob` is empty, `setup-uv` default dependency globs are
  used.
