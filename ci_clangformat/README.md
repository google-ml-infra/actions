# CI Clang-format

This composite action helps maintain consistent C/C++ code style by running
`clang-format` on modified files in your pull requests. It checks for
formatting violations and will cause the workflow to fail if any issues are
found, ensuring code quality before merging.

The action uses your .clang-format style file if present in the repository
root; otherwise, it will use the .clang-format.default under this folder.

## Usage

Add this step to your GitHub Actions workflow:

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Run Clang-format Check
        uses: ./ci_clangformat/
```

## Inputs

*   **`clang_format_version`**: (Optional) The exact `clang-format` version to use. Defaults to `20.1.5`.
*   **`filepaths`**: (Optional) A space-separated list of file paths or glob patterns to check.
If not specified, the action defaults to checking all modified `.h` and `.cc` files.

### Example with custom filepaths and version

```yaml
- name: Run Clang-format Check
  uses: ./ci_clangformat/
  with:
    clang_format_version: "18.1.8"
    filepaths: "src/*.cc include/*.h"
```

## Resolving Formatting Failures
If a workflow run fails due to formatting violations, you're expected to
fix the issues locally. Simply run `clang-format` on the problematic
files, e.g., using
`uvx clang-format==20.1.5 -i --verbose --style=file <files>`,
and then commit the formatted code to your pull request.

## UV Requirement
This action leverages `uv` to reliably install and run specific
`clang-format` versions, ensuring consistent behavior across different
environments. `uvx` is a convenience alias that calls `uv tool run`.
If `uv` does not exist, you'll need to include a step to [install](https://docs.astral.sh/uv/getting-started/installation/)
it in your workflow's running environment.
