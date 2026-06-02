# Check License Headers

This composite action helps maintain consistent licensing headers across your codebase by running `addlicense` on source and configuration files. It checks for missing license declarations and causes the workflow to fail if any unlicensed files are found, ensuring strict code compliance.

The action dynamically prunes standard non-source and metadata files (like Lockfiles, JSON configs, Doxygen configurations, and documentation structures) by default, and allows full customization of target paths, exclusions, and copyright signatures.

## Usage

Add this step to your GitHub Actions workflow:

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Set up Go
        uses: actions/setup-go@v5
        with:
          go-version: 'stable'

      - name: Run License Header Check
        uses: ./.github/actions/check-license/
```

## Inputs

*   **`copyright-holder`**: (Optional) The copyright holder name to check in the header. Defaults to `The TensorFlow Authors`.
*   **`license-type`**: (Optional) The license type to verify (e.g., `apache`, `mit`, `bsd`). Defaults to `apache`.
*   **`exclude-paths`**: (Optional) Comma-separated list of folder paths to prune/exclude from the scan. Defaults to `third_party`.
*   **`exclude-extensions`**: (Optional) Comma-separated list of additional file extensions to exclude (e.g., `tflite, tfrecord, lite`).
*   **`exclude-files`**: (Optional) Comma-separated list of additional specific filenames or patterns to exclude (e.g., `tensorflow_issue_template.yaml`).
*   **`scan-path`**: (Optional) The directory path where the scan should begin. Defaults to directory root (`.`).

### Example with custom exclusions and license type

```yaml
- name: Run License Header Check
  uses: ./.github/actions/check-license/
  with:
    copyright-holder: "Google LLC"
    license-type: "mit"
    scan-path: "src"
    exclude-paths: "src/external, src/generated"
    exclude-extensions: "json, xml"
```

## Resolving License Failures
If a workflow run fails due to missing licenses, you're expected to add headers to the problematic files. Simply run `addlicense` locally on the flagged files:
`addlicense -c "<copyright_holder>" -l <license_type> <files>`
and then commit the modified files back to your branch/pull request.

## Default Exclusions

`addlicense` only processes file types it recognises (those with a defined comment style). Binary, image, data, and other unrecognised extensions are silently skipped by the tool itself, so they don't need to appear in the ignore list. The action only explicitly excludes file types that `addlicense` would otherwise process but that don't require license headers:

| Category | Extensions / Files |
|----------|-------------------|
| **Build System** | `.bazel`, `.bzl`, `.BUILD` |
| **Config / Markup** | `.Dockerfile`, `Dockerfile`, `.html`, `.xml`, `.proto` |
| **Python** | `__init__.py` (typically empty or auto-generated) |

You can add additional exclusions using the `exclude-extensions` and `exclude-files` inputs.


## Go Requirement
This action leverages `go install` to reliably install and run `addlicense` (if it is not already present in your runner environment), ensuring exact tool consistency. If Go is not yet installed in your job runner, you will need to include a step to set it up beforehand, such as using `actions/setup-go`.
