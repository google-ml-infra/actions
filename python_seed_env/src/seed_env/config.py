"""
Copyright 2025 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

DEFAULT_PROJECT_COMMIT = "main"
DEFAULT_SEED_FRAMEWORK = "jax"
DEFAULT_SEED_CONFIG_FILE = "jax_seed.yaml"
DEFAULT_PYTHON_VERSION = "3.12"
DEFAULT_HARDWARE = "tpu"
DEFAULT_BUILD_PROJECT = False
SUPPORTED_HARDWARE = ["tpu", "gpu", "cuda12", "cuda13"]

TENSORFLOW_DEPS = [
  "tensorflow",
  "wrapt",
  "tensorboard",
  "protobuf",
  "setuptools",
]

TPU_SPECIFIC_DEPS = [
  "libtpu",
]

CUDA12_SPECIFIC_DEPS = [
  "jax-cuda12-plugin",
  "jax-cuda12-pjrt",
  "^nvidia-.*-cu12$",
]

CUDA13_SPECIFIC_DEPS = [
  "jax-cuda13-plugin",
  "jax-cuda13-pjrt",
  "^nvidia-.*-cu13$",
  "nvidia-cublas",
  "nvidia-cuda-crt",
  "nvidia-cuda-cupti",
  "nvidia-cuda-nvcc",
  "nvidia-cuda-nvrtc",
  "nvidia-cuda-runtime",
  "nvidia-cufft",
  "nvidia-cusolver",
  "nvidia-cusparse",
  "nvidia-nvjitlink",
  "nvidia-nvvm",
]
