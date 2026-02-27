# CI Clang-format

This composite action helps maintain consistent C/C++ code style by running
`clang-format` on modified files in your pull requests. It checks for
formatting violations and will cause the workflow to fail if any issues are
found, ensuring code quality before merging.

The action uses your .clang-format style file if present in the repository
root; otherwise, it will use the .clang-format.default under this folder.

This action offers the following configuration through its inputs:
* `clang_format_version`: Choose the exact clang-format version to use,
 with `20.1.5` as the default to align with recent stable releases.

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
