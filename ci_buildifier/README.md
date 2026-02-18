# Buildifier Format Check Action

This composite action ensures that Bazel files 
(`BUILD`, `WORKSPACE`, `MODULE.bazel`, and `.bzl`) are properly 
formatted using [buildifier](https://github.com/bazelbuild/buildtools/tree/master/buildifier). 

It only checks files that have been modified in the current Pull Request or Push.

## Prerequisites

`buildifier` must be installed and available in the system `PATH` for this action to work.

## Usage

Add this step to your GitHub Actions workflow:

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Run Buildifier Check
        uses: ./ci_buildifier/
```

## Inputs

*   **`filepaths`**: (Optional) A space-separated list of file paths or glob patterns to check.
If not specified, the action defaults to checking all modified `BUILD`, `WORKSPACE`, `MODULE.bazel`, and `.bzl` files.

### Example with custom filepaths

```yaml
- name: Run Buildifier Check
  uses: ./ci_buildifier/
  with:
    filepaths: "path/to/my/BUILD path/to/others/*.bzl"
```