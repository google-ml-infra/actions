# Configuring runners and containers
This directory contains JSON configuration files that define the available hardware and containers for benchmarking.

## GitHub Actions runners
This file is the single source of truth for all available self-hosted GitHub Actions runners that are officially supported for benchmarking. The matrix generator uses this file to find a suitable runner that satisfies the resource requirements specified in a benchmark's configuration.

The file is a JSON object where each key is a full repository name (e.g., `owner/repo`) and the value is a dictionary of available runners for that repository, grouped by `HardwareCategory`.

### How to update
To add a new runner, find the key for the repository it belongs to (or add a new key for a new repository). Then, add the runner object to the appropriate `HardwareCategory` list with its label, os, and resource properties (vcpu, gpu_count, tpu_topology, etc.).

If creating a new hardware category, ensure the `benchmark_registry.proto` schema is updated as well.

## Containers
This file maps a `HardwareCategory` to the OCI container image that should be used for any benchmark running on that type of hardware.

The file is a JSON object where keys are the `HardwareCategory` and values are the full container image URLs.

### How to update
To change the default image for a hardware type, simply update the value for the corresponding key.
