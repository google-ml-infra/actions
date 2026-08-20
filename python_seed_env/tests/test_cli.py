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

import pytest
import sys

import seed_env.cli


def test_cli_prints_help_on_no_args(monkeypatch, capsys):
  # Simulate no arguments
  monkeypatch.setattr(sys, "argv", ["seed_env/cli.py"])
  with pytest.raises(SystemExit):
    seed_env.cli.main()
  captured = capsys.readouterr()
  assert "usage" in captured.out.lower() or "usage" in captured.err.lower()


def test_cli_error_on_missing_required(monkeypatch, capsys):
  # Simulate missing required arguments
  monkeypatch.setattr(
    sys, "argv", ["seed_env/cli.py", "--seed-config", "jax_seed.yaml"]
  )
  with pytest.raises(SystemExit):
    seed_env.cli.main()
  captured = capsys.readouterr()
  assert "error" in captured.out.lower() or "error" in captured.err.lower()


def test_cli_local_project(monkeypatch, tmp_path, mocker):
  # Simulate local project path
  requirements = tmp_path / "requirements.txt"
  requirements.write_text("foo==1.2.3\n")
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "seed_env/cli.py",
      "--local-requirements",
      str(tmp_path),
      "--seed-config",
      "jax_seed.yaml",
      "--python-version",
      "3.12",
    ],
  )
  # Mock EnvironmentSeeder and its method
  mock_seeder = mocker.patch("seed_env.cli.EnvironmentSeeder")
  instance = mock_seeder.return_value
  instance.seed_environment.return_value = None
  seed_env.cli.main()
  assert instance.seed_environment.called


def test_cli_remote_project(monkeypatch, mocker):
  # Simulate remote repo
  monkeypatch.setattr(
    sys,
    "argv",
    [
      "seed_env/cli.py",
      "--host-repo",
      "org/repo",
      "--host-requirements",
      "requirements.txt",
      "--host-commit",
      "abc123",
      "--seed-config",
      "jax_seed.yaml",
      "--python-version",
      "3.12",
    ],
  )
  # Mock EnvironmentSeeder and its method
  mock_seeder = mocker.patch("seed_env.cli.EnvironmentSeeder")
  instance = mock_seeder.return_value
  instance.seed_environment.return_value = None
  seed_env.cli.main()
  assert instance.seed_environment.called
