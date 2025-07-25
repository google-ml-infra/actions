# Seed-Env CLI Tool

This seed-env command-line tool creates stable, reproducible Python environments for Machine Learning projects.
It's designed to solve complex dependency management challenges, especially for projects built on rapidly evolving
frameworks like JAX.
This seed-env command-line tool creates stable, reproducible Python environments for Machine Learning projects.
It's designed to solve complex dependency management challenges, especially for projects built on rapidly evolving
frameworks like JAX.

## What is seed-env tool?

`seed-env` is a Python command-line tool that automates the creation of consistent development and production environments.
The seed-env CLI tool's design centers around a methodology that bases (i.e. seeds) the Python environment on the thoroughly
tested dependency graph of [JAX](https://github.com/jax-ml/jax). The tool will take project-specific dependencies
(e.g., MaxText's [requirements.txt](https://github.com/AI-Hypercomputer/maxtext/blob/main/requirements.txt))
and intelligently layer them on top of the JAX seed, resolving conflicts to creat a stable final environment.

### Key concepts

- **Seed**: A Seed project (like [JAX](https://github.com/jax-ml/jax)) is the foundational dependency of a Host project.
A Seed project should include a `requirements_lock.txt` with only **pinned** and thoroughly tested dependencies, representing
a stable set for the Host project. For example, a Host project primarily dependent on JAX could use its
[requirements_lock_3_11.txt](https://github.com/jax-ml/jax/blob/main/build/requirements_lock_3_11.txt) as its seed for Python 3.11.
- **Host**: The Host project is your main project that you want to create a stable environment for.
The Host project depends on a foundational Seed project like JAX. The Host repository's `requirements.txt` should be **non-pinned**
(preferably lower-bound) dependencies to prevent conflicts with the Seed. Any dependencies from source links, e.g.,
`git+` prefix followed by the git repository URL, must be pinned to a specific
commit for reproducibility. For example, [MaxText](https://github.com/AI-Hypercomputer/maxtext/tree/main/MaxText) serves as a
Host repository, built upon the [JAX](https://github.com/jax-ml/jax) Seed environment.

### Key artifacts <a id="key-artifacts"></a>

The tool generates several key artifacts:

- **Lock Files**: It creates `uv.lock` and `requirements_lock.txt` files with every package version pinned, ensuring
the environment of the host repository can be recreated perfectly every time.
- **Project Definition File**: It creates a `pyproject.toml` file that defines the host repository's dependencies with
lower-bound version constraints.
- **(Optional) Installable Dependency PyPI Package**: If user specifies the `--build-pypi-package` flag when using the
`seed-env` tool, it builds a distributable Python package (`.whl` file and `tar.gz.` file) containing all of the
host repository's dependencies.

## How to Use It?

### Prerequisites

Before you begin, ensure you have the following:

- Ensure your Seed repo's `requirements_lock.txt` contains only **pinned dependencies**.
- Host Repo's `requirements.txt`: Make sure that your Host repo's `requirements.txt` contains **non-pinned dependencies**.
Additionally, all GitHub-importeddependencies must be pinned to a specific commit
(e.g., `google-jetstream @ https://github.com/AI-Hypercomputer/JetStream/archive/261f25007e4d12bb57cf8d5d61e291ba8f18430f.zip`).

### Install the `seed-env` tool

Clone the repository and install the tool:

```shell
git clone https://github.com/google-ml-infra/actions.git
cd actions/python_seed_env

# Build the seed-env CLI tool by running
pip install .


# Or run the following command if you want to edit and run pytest
# pip install -e . [dev]
```

### Example commands

Here are some common ways to use the seed-env tool:

```shell
# See all the arguments of the tool
seed-env --help


# Run the following command with minimal arguments needed to generate requirement lock files for maxtext based on the latest release jax as seed.
seed-env --host-repo=AI-Hypercomputer/maxtext --host-requirements=requirements.txt


# Run the following command to build lock files and a pypi package for maxtext at a specific commit and use jax at a specific commit/tag.
seed-env --host-repo=AI-Hypercomputer/maxtext --host-requirements=requirements.txt --host-commit=<a maxtext commit> --seed-config=jax_seed.yaml --seed-commit="jax-v0.6.2" --python-version="3.12" --hardware="tpu" --build-pypi-package


# Run the following command build lock files and a pypi package based on a local host requirement file and use the latest release jax as seed.
seed-env --local-requirements=<local path to a requirements.txt file> --build-pypi-package
```

### Utilize the generated artifacts to install host repo's environment

After running the `seed-env` tool, a few [artifacts](#key-artifacts) will be generated in the `generated_env` directory.
The typical structure looks like this:

```
generated_env
├── build
│   └── bdist
├── dist
│   └── <host-repo>-<version>.whl  # generated dependency PyPI package
├── <host-repo>.egg-info
│   ├── PKG-INFO
│   ├── SOURCES.txt
│   ├── dependency_links.txt
│   ├── requires.txt
│   └── top_level.txt
├── <host-repo>_requirements_lock_<python-version>.txt  # generated requirements_lock.txt lock file
├── pyproject.toml  # generated project definition file
└── uv.lock  # generated uv.lock lock file
```

Before installing dependencies with these artifacts, it's **highly recommended** to start with a clean Python environment
(e.g., a new virtual environment) to avoid conflicts and ensure a predictable installation.

For example, you can create a virtual environment with the uv tool like so:

```shell
cd <path/to/your/project>
uv venv --python <python-version> --seed <venv-name>
source <venv-name>/bin/activate
python --version
```

With these generated artifacts, you can set up the development environment for your host repository using either of the following approaches:

#### Option A: Using Lock Files

- For `uv` users: Move the generated `uv.lock` file to your project root and execute `uv sync`.
- For `pip` users: Run `python -m pip install -r <path_to_the_project_requirements_lock_file>`.

#### Option B: Using the Dependency PyPI Packages

```shell
uv pip install <path_to_generated_dependency_package.whl> --resolution=lowest
```

## How to Add a New Seed Project?

To add a new seed project, refer to the [jax_seed.yaml](https://github.com/google-ml-infra/actions/blob/main/python_seed_env/src/seed_env/seeder_configs/jax_seed.yaml) file located in src/seed_env/seeder_configs. This folder stores seeder project configuration YAMLs for runtime data access (currently, only JAX is supported).

Create a similar YAML file, updating the configuration values to match your seeder project. Then, invoke the seed-env CLI tool using the `--seed-config` flag, providing either a relative or absolute path to your new YAML file. The tool will first check its package data, then look for the file locally if not found.

> [!WARNING]
> This tool is still under construction at this time.
