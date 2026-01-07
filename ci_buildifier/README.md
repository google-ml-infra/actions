# CI Buildifier

This composite action helps you maintain consistent formatting for your Bazel
`BUILD` and `.bzl` files. It automatically runs `buildifier` on any modified
files in your pull requests, ensuring code quality and adherence to style
conventions. If buildifier detects any formatting violations, your workflow
will fail, preventing unformatted code from being merged.

## Resolving Formatting Failures
If a workflow run fails due to formatting violations, you're expected to
fix the issues locally. Simply run `buildifier` on the problematic
files, e.g., using
`buildifier -v <files>`,
and then commit the formatted code to your pull request.

## Requirements
This action expects `buildifier` to be available in your workflow's runtime
environment. If `buildifier` is not pre-installed in your chosen runner image
or container, you will need to install it before this action runs.
