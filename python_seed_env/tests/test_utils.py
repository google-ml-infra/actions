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

import os
import pytest

from seed_env.utils import (
  valid_python_version_format,
  run_command,
  get_latest_project_version_from_pypi,
  generate_minimal_pyproject_toml,
)
from seed_env.git_utils import (
  download_remote_git_file,
  resolve_github_tag_to_commit,
  is_valid_commit_hash,
  looks_like_commit_hash,
)
from seed_env.uv_utils import (
  build_pypi_package,
  build_seed_env,
  lock_to_lower_bound_project,
  _read_pinned_deps_from_a_req_lock_file,
  _convert_pinned_deps_to_lower_bound,
  replace_dependencies_in_project_toml,
)


def test_download_remote_git_file(tmp_path, mocker):
  url = "https://raw.githubusercontent.com/python/cpython/main/README.rst"
  output_dir = tmp_path
  mock_response = mocker.Mock()
  mock_response.content = b"hello world"
  mock_response.raise_for_status = mocker.Mock()
  mocker.patch("seed_env.utils.requests.get", return_value=mock_response)
  out_path = download_remote_git_file(url, str(output_dir))
  assert os.path.isfile(out_path)
  with open(out_path, "rb") as f:
    assert f.read() == b"hello world"


def test_get_latest_project_version_from_pypi(mocker):
  mock_response = mocker.Mock()
  mock_response.raise_for_status = mocker.Mock()
  mock_response.json.return_value = {
    "releases": {"1.0.0": {}, "2.0.0": {}, "1.5.0": {}}
  }
  mocker.patch("seed_env.utils.requests.get", return_value=mock_response)
  version = get_latest_project_version_from_pypi("dummy")
  assert version == "2.0.0"


def test_resolve_github_tag_to_commit(mocker):
  mock_response = mocker.Mock()
  mock_response.raise_for_status = mocker.Mock()
  mock_response.json.return_value = {"object": {"sha": "abc123"}}
  mocker.patch("seed_env.utils.requests.get", return_value=mock_response)
  sha = resolve_github_tag_to_commit("org/repo", "v1.0.0")
  assert sha == "abc123"


def test_is_valid_commit_hash_true(mocker):
  mock_response = mocker.Mock()
  mock_response.status_code = 200
  mocker.patch("seed_env.utils.requests.get", return_value=mock_response)
  assert is_valid_commit_hash("org/repo", "a" * 40) is True


def test_is_valid_commit_hash_false(mocker):
  mock_response = mocker.Mock()
  mock_response.status_code = 404
  mocker.patch("seed_env.utils.requests.get", return_value=mock_response)
  assert is_valid_commit_hash("org/repo", "b" * 40) is False


@pytest.mark.parametrize(
  "commit_hash,expected",
  [
    ("a" * 40, True),
    ("abc123", False),
    ("", False),
    ("g" * 40, False),  # not hex
  ],
)
def test_looks_like_commit_hash(commit_hash, expected):
  assert looks_like_commit_hash(commit_hash) == expected


def test_generate_minimal_pyproject_toml(tmp_path):
  out_path = generate_minimal_pyproject_toml("myproj", "3.12", str(tmp_path))
  assert os.path.isfile(out_path)
  content = open(out_path).read()
  assert 'name = "myproj"' in content
  assert 'requires-python = "==3.12.*"' in content


def test_generate_minimal_pyproject_toml_invalid_version(tmp_path):
  with pytest.raises(ValueError):
    generate_minimal_pyproject_toml("myproj", "3.12.1", str(tmp_path))


def test_generate_minimal_pyproject_toml_empty_name(tmp_path):
  with pytest.raises(ValueError):
    generate_minimal_pyproject_toml("", "3.12", str(tmp_path))


def test_build_seed_env_calls_run_command(mocker, tmp_path):
  # Prepare dummy files
  host_requirements_file = tmp_path / "host.txt"
  seed_lock_file = tmp_path / "seed.txt"
  host_requirements_file.write_text("foo==1.2.3\n")
  seed_lock_file.write_text("bar==4.5.6\n")
  output_dir = tmp_path / "output"
  output_dir.mkdir()
  hardware = "gpu"
  host_lock_file_name = "host_lock.txt"

  # Mock a minimal pyproject.toml in the output_dir
  pyproject_file = output_dir / "pyproject.toml"
  pyproject_file.write_text("""
[project]
name = "dummy"
version = "0.1.0"
""")

  # Mock run_command to track calls
  mock_run_command = mocker.patch("seed_env.uv_utils.run_command")
  mock_os_remove = mocker.patch("os.remove")
  mock_lock_to_lower_bound_project = mocker.patch(
    "seed_env.uv_utils.lock_to_lower_bound_project"
  )
  mock_remove_hardware_specific_deps = mocker.patch(
    "seed_env.uv_utils._remove_hardware_specific_deps"
  )

  build_seed_env(
    str(host_requirements_file),
    str(seed_lock_file),
    str(output_dir),
    hardware,
    host_lock_file_name,
  )

  # Should call run_command at least once
  assert mock_run_command.called
  assert mock_os_remove.called
  assert mock_lock_to_lower_bound_project.called
  # Check for the expected uv remove command
  assert mock_remove_hardware_specific_deps.call_count == 1

  # Collect all commands passed to run_command
  commands = [call.args[0] for call in mock_run_command.call_args_list]
  # Check for the expected uv add command to planting a seed
  assert [
    "uv",
    "add",
    "--managed-python",
    "--no-build",
    "--no-sync",
    "--resolution=highest",
    "--directory",
    str(output_dir),
    "-r",
    str(seed_lock_file),
  ] in commands
  # Check for the command to add the rest of deps from the host
  assert [
    "uv",
    "add",
    "--managed-python",
    "--no-sync",
    "--resolution=highest",
    "--directory",
    str(output_dir),
    "-r",
    str(host_requirements_file),
  ] in commands
  # Check for the command to generate a full host lock file
  assert [
    "uv",
    "export",
    "--managed-python",
    "--locked",
    "--no-hashes",
    "--no-annotate",
    "--resolution=highest",
    "--directory",
    str(output_dir),
    "--output-file",
    str(host_lock_file_name),
  ] in commands
  # Check for the command to regenerate uv.lock but now uses --resolution=lowest strategy
  assert [
    "uv",
    "lock",
    "--managed-python",
    "--resolution=lowest",
    "--directory",
    str(output_dir),
  ] in commands
  # Check for the command to generate a full host lock file with lowest strategy
  assert [
    "uv",
    "export",
    "--managed-python",
    "--locked",
    "--no-hashes",
    "--no-annotate",
    "--resolution=lowest",
    "--directory",
    str(output_dir),
    "--output-file",
    str(host_lock_file_name),
  ] in commands


def test_convert_deps_to_lower_bound():
  pinned = ["foo==1.2.3", "bar==4.5.6"]
  expected = ["foo>=1.2.3", "bar>=4.5.6"]
  assert _convert_pinned_deps_to_lower_bound(pinned) == expected


def test_read_requirements_lock_file(tmp_path):
  content = "foo==1.2.3\nbar==4.5.6\n# comment\nbaz @ git+https://repo.git\n"
  file = tmp_path / "lock.txt"
  file.write_text(content)
  result = _read_pinned_deps_from_a_req_lock_file(str(file))
  assert "foo==1.2.3" in result
  assert "bar==4.5.6" in result
  assert "baz @ git+https://repo.git" in result
  assert "# comment" not in result


def test_replace_dependencies_in_project_toml(tmp_path):
  toml_content = """
[project]
dependencies = [
    "foo==1.2.3",
    "bar==4.5.6",
]
"""
  new_deps_list = ["foo>=1.2.3", "bar>=4.5.6"]
  toml_file = tmp_path / "pyproject.toml"
  toml_file.write_text(toml_content)
  replace_dependencies_in_project_toml(new_deps_list, str(toml_file))
  updated = toml_file.read_text()
  assert "foo>=1.2.3" in updated
  assert "bar>=4.5.6" in updated


@pytest.mark.parametrize(
  "version,expected",
  [
    ("3.8", True),
    ("3.10", True),
    ("3.12", True),
    ("3.12.1", False),
    ("abc", False),
    ("3", False),
    (3.8, False),
    ("", False),
  ],
)
def test_valid_python_version_format(version, expected):
  assert valid_python_version_format(version) == expected


def test_lock_to_lower_bound_project(tmp_path):
  # Prepare a lock file
  lock_content = "foo==1.2.3\nbar==4.5.6\n"
  lock_file = tmp_path / "lock.txt"
  lock_file.write_text(lock_content)
  # Prepare a pyproject.toml file
  toml_content = """
[project]
dependencies = [
    "foo>=1.2.0",
    "bar==4.5.6",
]
"""
  pyproject_file = tmp_path / "pyproject.toml"
  pyproject_file.write_text(toml_content)
  # Run the function
  lock_to_lower_bound_project(str(lock_file), str(pyproject_file))
  updated = pyproject_file.read_text()
  assert "foo>=1.2.3" in updated
  assert "bar>=4.5.6" in updated


def test_run_command_success(tmp_path):
  # Should succeed and return CompletedProcess
  file_path = tmp_path / "test.txt"
  result = run_command(["echo", "hello"], cwd=str(tmp_path), capture_output=True)
  assert result.returncode == 0
  assert "hello" in result.stdout


def test_run_command_failure(tmp_path):
  # Should raise CalledProcessError for a failing command
  with pytest.raises(Exception):
    run_command(["false"], cwd=str(tmp_path), check=True)


def test_build_pypi_package(tmp_path):
  # Create a minimal pyproject.toml
  pyproject_content = """
[project]
name = "dummy"
version = "0.1.0"
"""
  output_dir = tmp_path
  pyproject_file = output_dir / "pyproject.toml"
  pyproject_file.write_text(pyproject_content)
  # Should raise FileNotFoundError if pyproject.toml is missing
  # (already present, so should not raise)
  try:
    build_pypi_package(str(output_dir))
  except FileNotFoundError:
    pytest.fail("build_pypi_package raised FileNotFoundError unexpectedly!")
