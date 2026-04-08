# Google ML-Infra actions

This repository contains reusable actions, workflows and other tooling for use 
across Google ML projects.

These tools are not intended to be generally reusable outside these projects
and may require specific hardware setups and various prerequisites not fully
documented in this repo.

## Components/tooling

- [`ci_connection`](ci_connection/README.md): Action for pausing and connecting to workflows for debugging/testing.
- [`setup-uv-python`](setup-uv-python/README.md): Action for uv-managed Python setup in workflows.
- [`python_seed_env`](python_seed_env/README.md): Seed-based Python environment CLI tooling.
- [`benchmarking/actions`](benchmarking/docs/onboarding.md): Composite actions used by benchmarking pipelines.
- `ci_dashboard`: CI dashboard.
