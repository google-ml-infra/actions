# Onboarding Guide: BAP (Benchmarking Automation Platform)

## Quick Links

-   [GitHub Repository](https://github.com/google-ml-infra/actions)
-   [Reusable Workflow](https://github.com/google-ml-infra/actions/blob/main/.github/workflows/run-benchmarks.yaml)

### Schema Definitions

-   [benchmark_registry.proto](https://github.com/google-ml-infra/actions/blob/main/benchmarking/proto/benchmark_registry.proto)
-   [benchmark_result.proto](https://github.com/google-ml-infra/actions/blob/main/benchmarking/proto/benchmark_result.proto)

## Overview

This guide provides the steps to add a project's benchmarks to BAP (Benchmarking Automation Platform). BAP is GitHub-native and makes use of GitHub Actions to administer benchmarks.

The system is designed to execute any GitHub Action as a workload (e.g., standard Python scripts, Bazel targets, or custom user-defined actions), provided it adheres to the metric reporting contract.

The system follows two simple contracts:

1. **Input**: A benchmark registry (e.g., benchmark_registry.pbtxt) defining the workload action and its inputs, along with environment requirements and other metadata.
2. **Output**: Metric data written via TensorBoard and arbitrary files written to the workload artifacts directory.

Our platform handles the following:

- Provisioning the correct GitHub Actions runners.
- Converting defined benchmarks and environment requirements into GitHub Actions jobs.
- Securely executing the specified workload action.
- TensorBoard log parsing and statistic computation.
- Static threshold analysis.
- Publishing results to Google Cloud Pub/Sub for downstream consumption.

## Step 1: Create a workflow file

First, in your own repository, create a new workflow file in `.github/workflows/` for running benchmarks. 

```yaml
name: Run presubmit benchmarks

on:
  pull_request:
    paths:
      - 'benchmarking/**'

permissions:
  contents: read
  pull-requests: write # Required for A/B testing PR comments

jobs:
  run_benchmarks:
    uses: google-ml-infra/actions/.github/workflows/run_benchmarks.yml@<commit | branch | tag>
    with:
      registry_file: "benchmarking/my_registry.pbtxt"
      workflow_type: "PRESUBMIT"
      ml_actions_ref: <commit | branch | tag>
      publish_metrics: true
```

### Required permissions

`contents: read` and `pull-requests: write` permissions are required in the caller workflow.

### Workflow Inputs

The reusable workflow supports the following inputs:

| Input | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `registry_file` | **Yes** | - | Path to the `.pbtxt` benchmark registry file relative to the repository root. |
| `workflow_type` | **Yes** | - | The workflow type to run (e.g., `PRESUBMIT`, `NIGHTLY`). Matches the configuration in your registry. |
| `ml_actions_ref` | No | `main` | The branch, tag, or SHA of google-ml-infra/actions to use. For production, use the same stable tag or SHA that's used to pin the reusable workflow file version (e.g. "v1.5.0" for "google-ml-infra/actions/.github/workflows/run_benchmarks.yml@v1.5.0"). |
| `job_id` | No | Random | A unique identifier for the top-level job (e.g. `e2e-test`). Used to namespace artifacts. If empty, a random ID is generated. |
| `ab_mode` | No | `false` | If `true`, runs A/B comparison (baseline vs experiment) and generates an A/B report. |
| `experiment_ref` | No | Current SHA | Git ref for the experiment. Defaults to the current commit SHA. |
| `baseline_ref` | No | PR Base or main | Git ref for the baseline. Defaults to PR base or main. |
| `post_pr_comment` | No | `true` | If `true` (and `ab_mode` is enabled), posts the A/B report as a sticky comment on the PR. |
| `publish_metrics` | No | `false` | If `true`, publishes benchmark results to Google Cloud Pub/Sub. |
| `pub_sub_gcp_project_id` | No | `ml-oss-benchmarking-production` | GCP Project ID for Pub/Sub. |
| `pub_sub_gcp_topic_id` | No | `public-results-prod` | Pub/Sub Topic ID to publish results to. |

### Workflow granularity

We recommend creating a dedicated workflow file for each distinct [workflow_type](https://github.com/google-ml-infra/actions/blob/main/benchmarking/proto/benchmark_registry.proto#L112) 
you plan to support (PRESUBMIT, NIGHTLY, PERIODIC, etc.) to better control scheduling, triggers, and resource allocation.


## Step 2: Create benchmark registry

Next, create a benchmark registry file (.pbtxt) based on the [benchmark_registry.proto](https://github.com/google-ml-infra/actions/blob/main/benchmarking/proto/benchmark_registry.proto) schema. This file defines what code to run and how to run it.

### Defining workloads

The registry uses a flexible schema where you define a workload by specifying an Action to execute and a map of inputs to pass to that action.

We provide standard workload executors for Python and Bazel, but you are fully empowered to define your own custom action in your repository and reference it here.

#### Standard Executors

Each of the standard executors can be referenced either via a remote reference or a local reference. The local reference is recommended since the platform ships the standard executors together with the workflow.

**Python**

- Local reference: `./ml_actions/benchmarking/actions/workload_executors/python`
- Remote reference: `google-ml-infra/actions/benchmarking/actions/workload_executors/python@<ref>`

**Bazel**

- Local reference: `./ml_actions/benchmarking/actions/workload_executors/bazel`
- Remote reference: `google-ml-infra/actions/benchmarking/actions/workload_executors/bazel@<ref>`

#### Workload inputs

You can define base inputs in the `workload` block of the benchmark registry and environment-specific overrides or extensions in the `environment_configs` block using `workload_action_inputs`.

For our standard executors, we support "extension" inputs (suffixed with _hw) that allow you to append flags instead of overwriting them.

Note: The platform performs a simple dictionary merge on inputs. If a key in `environment_configs.workload_action_inputs` matches a key in the base `workload.action_inputs`, the value from `environment_configs.workload_action_inputs` will completely overwrite the base value. For best practice, if you are creating your own custom action and want to support appending values (like adding extra flags instead of replacing them), you should define distinct input keys in your action definition (e.g., flags and flags_hw). Your action's script is then responsible for concatenating them.

### Defining metrics

A key part of the registry is defining metrics. You must specify the `metrics.name` field, which must exactly match the tag name used in the TensorBoard logs generated by your benchmark script (covered in the next step). 
Within the metrics block, you specify the statistics (stats) to be calculated (e.g., MEAN, P99) and can optionally configure static threshold analysis using the comparison block.

### Example 1: Bazel workload

This example uses the standard Bazel executor.

Available inputs for Bazel:

- `target` (Required)
- `bazel_run_flags` / `bazel_run_flags_hw` (Passed to bazel run, e.g., compilation options)
- `runtime_flags` / `runtime_flags_hw` (Passed to the binary after --)


```proto
benchmarks {
  name: "my_bazel_benchmark"
  description: "Runs a simple Bazel target."
  owner: "my-team"

  workload {
    # Point to the standard Bazel executor
    action: "./ml_actions/benchmarking/actions/workload_executors/bazel"

    action_inputs { key: "target" value: "//my_project:my_benchmark_binary" }

    # Base runtime flags
    action_inputs { key: "runtime_flags" value: "--model_name=resnet" }
  }

  environment_configs {
    id: "cpu_standard"
    runner_label: "linux-x86-n2-32"
    container_image: "us-docker.pkg.dev/my-project/images/cpu-test:latest"
    workflow_type: [PRESUBMIT]

    # Environment-specific build flags
    workload_action_inputs { key: "bazel_run_flags_hw" value: "--config=linux_cpu_opt" }
    
    # Environment-specific runtime flags
    workload_action_inputs { key: "runtime_flags_hw" value: "--precision=fp32" }
  }

  update_frequency_policy: QUARTERLY

  metrics {
    # REQUIRED: Must match the TensorBoard tag name (e.g., 'wall_time' in the log)
    name: "wall_time"
    unit: "ms"

    stats {
      stat: MEAN
      comparison: {
        # Configures threshold analysis.
        # For static analysis: compares against baseline.value.
        # For A/B testing: compares experiment vs baseline using threshold %.
        baseline { value: 100.0 } 
        threshold { value: 0.1 } # 10% tolerance
        improvement_direction: LESS 
      }
    }

    stats {
      stat: P99 
    }
  }
}
```

### Example 2: Python workload

This example uses the standard Python executor. It defines base dependencies (`test`) and appends environment-specific dependencies (`cuda`) and flags (`--use_gpu`) for the GPU config.

Available inputs for Python:

- `python_version` (Required)
- `script_path` (Required)
- `project_path` (Default: ".")
- `extras` / `extras_hw` (Comma-separated extras)
- `runtime_flags` / `runtime_flags_hw` (Passed to the script)

```proto
benchmarks {
  name: "my_python_benchmark"
  description: "Runs a Python script."
  owner: "my-team"

  workload {
    # Point to the standard Python executor using the local path
    action: "./ml_actions/benchmarking/actions/workload_executors/python"

    # Base inputs
    action_inputs { key: "script_path" value: "benchmarking/scripts/run_pallas.py" }
    action_inputs { key: "python_version" value: "3.11" }
    action_inputs { key: "project_path" value: "." }

    # Base extras (e.g. pip install .[test])
    action_inputs { key: "extras" value: "test" }

    # Base flags
    action_inputs { key: "runtime_flags" value: "--model_name=my_kernel" }
  }
  
  environment_configs {
    id: "gpu_l4"
    runner_label: "linux-x86-a4-224-l4-gpu"
    container_image: "us-docker.pkg.dev/my-project/images/gpu-test:latest"
    workflow_type: [PRESUBMIT]
    
    # Environment extensions (merged into the inputs above)
    # Appends 'cuda' -> pip install .[test,cuda]
    workload_action_inputs { key: "extras_hw" value: "cuda" }

    # Appends flag -> python script.py ... --use_gpu
    workload_action_inputs { key: "runtime_flags_hw" value: "--use_gpu" }
  }

  update_frequency_policy: QUARTERLY

  metrics {
    # REQUIRED: Must match the TensorBoard tag name
    name: "throughput"
    unit: "samples/sec"
    
    stats {
      stat: MEAN
      comparison: {
        baseline { value: 5000.0 }
        threshold { value: 0.05 }
        improvement_direction: GREATER
      }
    }

    stats {
      stat: MIN
    }
  }
}
```

## Step 3: Output Metrics and Artifacts

Your benchmark script will need to log metrics via TensorBoard to integrate with the platform.

The reusable workflow injects two standard environment variables into your workload's execution environment to handle outputs:

| Variable | Required | Description |
| :--- | :---  | :--- |
| `TENSORBOARD_OUTPUT_DIR` | **Yes** | Directory where TensorFlow event files must be written for metric parsing. |
| `WORKLOAD_ARTIFACTS_DIR` | No | Directory where arbitrary files (e.g., logits, images, debug logs) can be written. |

### Logging Metrics (TensorBoard)

The platform parses both V1 (Scalar) and V2 (Tensor) event formats. You can use any standard writer library:

- [TensorFlow](https://pypi.org/project/tensorflow/)(`tf.summary`): Writes V2 Tensor events.
- [tensorboardX](https://pypi.org/project/tensorboardX/): Writes V1 Scalar events (Ideal for PyTorch users).
- [TensorBoard](https://pypi.org/project/tensorboard/): Writes V1 Scalar events (Lightweight, no TensorFlow dependency).

#### Option 1: Using TensorFlow (V2)

Standard approach if your workload already uses TensorFlow.

```python
import tensorflow as tf
import os
import sys
import numpy as np

# Get the output directory from the platform.
tblog_dir = os.environ.get("TENSORBOARD_OUTPUT_DIR")

if not tblog_dir:
    print("Error: TENSORBOARD_OUTPUT_DIR env var not set.", file=sys.stderr)
    sys.exit(1)

fake_data = np.array([101.2, 100.5, 102.1, 99.8, 101.5])

try:
    # Uses the V2 'tensor' bucket
    writer = tf.summary.create_file_writer(tblog_dir)
    with writer.as_default():
        for i, value in enumerate(fake_data):
            # The tag "wall_time" MUST match the "name" in your MetricSpec.
            tf.summary.scalar("wall_time", value, step=i)

    writer.flush()
    writer.close()
    print("Successfully wrote metrics.")

except Exception as e:
    print(f"Error writing TensorBoard logs: {e}", file=sys.stderr)
    sys.exit(1)
```

#### Option 2: Using tensorboardX (V1)

Recommended for PyTorch users or lightweight scripts avoiding a heavy TensorFlow installation.

```python
import os
import sys
from tensorboardX import SummaryWriter

tblog_dir = os.environ.get("TENSORBOARD_OUTPUT_DIR")

if not tblog_dir:
    print("Error: TENSORBOARD_OUTPUT_DIR env var not set.", file=sys.stderr)
    sys.exit(1)

fake_data = [101.2, 100.5, 102.1, 99.8, 101.5]

try:
    # Uses the V1 'simple_value' bucket
    writer = SummaryWriter(log_dir=tblog_dir)
    
    for i, value in enumerate(fake_data):
        # The tag "wall_time" MUST match the "name" in your MetricSpec.
        writer.add_scalar("wall_time", value, global_step=i)

    writer.close()
    print("Successfully wrote metrics.")

except Exception as e:
    print(f"Error writing TensorBoard logs: {e}", file=sys.stderr)
    sys.exit(1)
```

#### Option 3: Using TensorBoard (V1)

Recommended if you want zero heavy dependencies (no tensorflow and no torch). This uses the low-level protobufs directly.

```python
import os
import sys
import time
from tensorboard.compat.proto import event_pb2, summary_pb2
from tensorboard.summary.writer.event_file_writer import EventFileWriter

tblog_dir = os.environ.get("TENSORBOARD_OUTPUT_DIR")
if not tblog_dir:
    sys.exit("Error: TENSORBOARD_OUTPUT_DIR env var not set.")

fake_data = [101.2, 100.5, 102.1, 99.8, 101.5]

try:
    # Manually writes V1 'simple_value' events
    writer = EventFileWriter(tblog_dir)

    for i, value in enumerate(fake_data):
        event = event_pb2.Event(
            step=i,
            wall_time=time.time(),
            summary=summary_pb2.Summary(
              # The tag "wall_time" MUST match the "name" in your MetricSpec.
              value=[summary_pb2.Summary.Value(tag="wall_time", simple_value=value)]
            )
        )
        writer.add_event(event)

    writer.close()
    print("Successfully wrote metrics.")

except Exception as e:
    print(f"Error writing TensorBoard logs: {e}", file=sys.stderr)
    sys.exit(1)
```
### Saving Workload Artifacts

If your workload produces files other than metrics (e.g., raw logits, images, or custom JSON logs), you can save them to `WORKLOAD_ARTIFACTS_DIR`.

Any file written to this directory is automatically zipped and uploaded as a GitHub Actions artifact (retained for 7 days), even if the benchmark workload fails.

```python
import os
import numpy as np

artifact_dir = os.environ.get("WORKLOAD_ARTIFACTS_DIR")

if artifact_dir:
    # Write arbitrary files
    with open(os.path.join(artifact_dir, "logits.npy"), "wb") as f:
        np.save(f, my_logits)
```

## Step 4: A/B Testing

BAP supports native A/B testing, allowing you to detect performance regressions on pull requests before they are merged.

### How it works

When `ab_mode: true` is set, the workflow automatically orchestrates the following:

1.  **Baseline Run**: Checks out the base ref (e.g., `main`) and runs the benchmarks.
2.  **Experiment Run**: Checks out your experiment ref (e.g. PR branch) and runs the same benchmarks.
3.  **Analysis**: Compares the metrics between the two runs.
4.  **Report**: Generates a markdown report and posts it as a "sticky" comment on your PR.

### PR Comment

The workflow posts a comment to the PR summarizing the results.

- **Sticky Behavior**: The comment is updated on subsequent pushes to keep the conversation clean.
- **Run History**: The comment maintains a collapsible history log of previous runs for the PR, allowing you to audit performance over time as you iterate on the code.
- **Status**: The status (PASS/REGRESSION) is determined by the `threshold` and `improvement_direction` defined in your registry.

### Enabling A/B Testing

Set `ab_mode: true` in your workflow file. You can also specify a custom baseline and/or experiment ref if needed.

```yaml
jobs:
  run_benchmarks:
    uses: google-ml-infra/actions/.github/workflows/run-benchmarks.yml@main
    with:
      registry_file: "benchmarking/my_registry.pbtxt"
      workflow_type: "PRESUBMIT"
      ab_mode: true # Enable A/B testing
```

## Step 5: Testing

When adding or modifying benchmarks, it is often useful to verify the configuration in the GitHub environment before merging. To avoid creating unnecessary PRs (which can clutter history) just to trigger a run, we recommend using a push-based workflow for testing.

**Configure a test trigger**: Ensure your workflow file (from Step 1) is configured to trigger on push to your specific testing branch.

```yaml
on:
  push:
    branches:
      - "benchmarking" # or your feature branch name
```

**Push to the testing branch**: Commit your changes to this branch and push to GitHub.

```bash
git checkout -b benchmarking
git add .
git commit -m "Test new benchmark config"
git push origin benchmarking
```

**Verify the run**: Navigate to the Actions tab in your GitHub repository. You should see the workflow triggered by your push.

1. Monitor the "Run benchmark" jobs to ensure the workload executes successfully.
2. Check the "Parse TensorBoard logs" step output to confirm your metrics were found and parsed correctly.
3. Verify the generated "Benchmark Result" and "Workload Artifacts" on the summary page.

## Step 6: Data Consumption (Pub/Sub)

After the benchmark completes and metrics are parsed, the platform serializes the data and will optionally publish it to Google Cloud Pub/Sub. This allows you to build custom dashboards, alerting systems, or historical archives by subscribing to the result stream.

### Enabling Publication

To enable publishing, you must set `publish_metrics: true` in your workflow file inputs (see Step 1). By default, this is disabled.

### Data Format

The message payload is a JSON-serialized BenchmarkResult protocol buffer (UTF-8 encoded).

Schema Definition: [benchmark_result.proto](https://github.com/google-ml-infra/actions/blob/main/benchmarking/proto/benchmark_result.proto)

### Requesting a Subscription

To consume data for your repository, you must be onboarded as a consumer. Our platform manages the subscription resources to ensure reliability (Dead Letter Queues, retention policies, etc.).

**To onboard, please [raise an issue](https://github.com/google-ml-infra/actions/issues) with the following details:**

1. **Repository Name**: The full repository name including the owner/organization (e.g., google/jax).

2. **Principal**: The service account email that will consume the data (e.g., my-dashboard-sa@my-project.iam.gserviceaccount.com).

3. **Confidentiality**: All benchmarks run via this platform are published to a single shared public topic. We will configure a filter on your repository name so you only receive your own data. **Note:** If your data cannot be made public (e.g., private repo, confidential results), please specify in the issue that you require a private topic.

### Connecting to your Subscription

Once your onboarding is processed, the platform team will provide you with a **Subscription ID**.

If you are using the public topic, the details will be:

- **GCP Project:** `ml-oss-benchmarking-production`
- **Topic ID:** `public-results-prod`

You can then configure your client to listen to this subscription using the standard [Google Cloud Pub/Sub libraries](https://docs.cloud.google.com/pubsub/docs/reference/libraries).

**Security Note**: Consumers are strongly encouraged to validate incoming messages before processing them. The [BenchmarkResult]((https://github.com/google-ml-infra/actions/blob/main/benchmarking/proto/benchmark_result.proto)) protocol buffer definition is compatible with [protovalidate](https://github.com/bufbuild/protovalidate), allowing for robust constraints checking.
