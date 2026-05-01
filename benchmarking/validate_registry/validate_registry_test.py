import sys
from unittest import mock

import pytest

from benchmarking.validate_registry import validate_registry
from benchmarking.validate_registry.validate_registry import (
  SecurityValidationError,
  validate_action_string,
  validate_external_file,
)


@pytest.fixture(autouse=True)
def clear_cache():
  """Fixture to clear the cached security policy before each test."""
  validate_registry.load_security_policy.cache_clear()
  yield


def test_missing_policy_exits():
  """Verifies that a missing security policy triggers a fatal error."""
  with mock.patch("importlib.resources.files") as mock_files:
    # Simulate the policy resource not existing
    mock_files.return_value.__truediv__.return_value.exists.return_value = False
    with pytest.raises(SystemExit) as cm:
      validate_action_string("some/action@sha")
    assert cm.value.code == 1


def test_local_actions():
  """Verifies that local actions are trusted and path traversal is blocked."""
  assert validate_action_string("./ml_actions/bazel")[0] is True

  # Path traversal in local action
  valid, msg = validate_action_string("./../secrets")
  assert valid is False
  assert "Path traversal" in msg

  # Whitespace in local action
  assert validate_action_string("./ml_actions/bazel ")[0] is False


def test_organization_allowlist():
  """Verifies that only actions from trusted organizations are allowed."""
  sha = "0123456789abcdef0123456789abcdef01234567"
  assert validate_action_string(f"actions/checkout@{sha}")[0] is True
  assert validate_action_string(f"google-ml-infra/actions@{sha}")[0] is True

  valid, msg = validate_action_string(f"malicious-user/miner@{sha}")
  assert valid is False
  assert "Untrusted organization" in msg


def test_sha_pinning_enforcement():
  """Verifies that remote actions must be pinned to a valid SHA-1 or SHA-256."""
  valid_sha1 = "0123456789abcdef0123456789abcdef01234567"
  valid_sha256 = "sha256:" + "a" * 64

  assert validate_action_string(f"actions/checkout@{valid_sha1}")[0] is True
  assert validate_action_string(f"actions/checkout@{valid_sha256}")[0] is True

  # Tags and branches are blocked
  valid, msg = validate_action_string("actions/checkout@v4")
  assert valid is False
  assert "not pinned to a valid SHA" in msg

  # Invalid digests are blocked
  assert validate_action_string("actions/checkout@sha256:short")[0] is False


def test_action_identifier_format():
  """Verifies the structured parsing of the action identifier string."""
  assert validate_action_string("actions/checkout")[0] is False  # Missing @
  assert validate_action_string("actions/checkout@sha@extra")[0] is False  # Double @
  assert validate_action_string("actions@sha1")[0] is False  # Missing repo
  assert validate_action_string("org/repo/path@sha 123")[0] is False  # Whitespace


def test_full_registry_validation(tmp_path):
  """Verifies end-to-end validation of a Protobuf registry file."""
  sha = "0123456789abcdef0123456789abcdef01234567"
  content = f"""
        benchmarks {{
            name: "pass_benchmark"
            workload {{ action: "actions/checkout@{sha}" }}
            environment_configs {{ id: "test" }}
        }}
        benchmarks {{
            name: "fail_benchmark"
            workload {{ action: "actions/checkout@v4" }}
            environment_configs {{ id: "test" }}
        }}
        """
  registry_file = tmp_path / "test_registry.pbtxt"
  registry_file.write_text(content)

  # Should raise SecurityValidationError because of the second benchmark
  with pytest.raises(SecurityValidationError):
    validate_external_file(registry_file)


def test_invalid_protobuf_is_rejected(tmp_path):
  """Verifies that malformed Protobuf files are rejected."""
  registry_file = tmp_path / "garbage.pbtxt"
  registry_file.write_text("invalid_field: 123")

  with pytest.raises(ValueError):
    validate_external_file(registry_file)


@pytest.mark.parametrize(
  "name, content, expected_count, expected_exception",
  [
    (
      "valid_with_comments",
      (
        "# Global comment\n"
        "benchmarks {\n"
        '  name: "b1"\n'
        "  workload {\n"
        '    action: "actions/checkout@0123456789abcdef0123456789abcdef01234567" # inline comment\n'
        "  }\n"
        '  environment_configs { id: "test" }\n'
        "}"
      ),
      1,
      None,
    ),
    (
      "action_in_subdirectory",
      (
        "benchmarks {\n"
        '  name: "b2"\n'
        "  workload {\n"
        '    action: "google-ml-infra/actions/benchmarking/bazel@0123456789abcdef0123456789abcdef01234567"\n'
        "  }\n"
        '  environment_configs { id: "test" }\n'
        "}"
      ),
      1,
      None,
    ),
    (
      "empty_action_is_skipped",
      (
        "benchmarks {\n"
        '  name: "b3"\n'
        '  workload { action: "" }\n'
        '  environment_configs { id: "test" }\n'
        "}"
      ),
      0,
      None,
    ),
    (
      "missing_workload_is_skipped",
      ('benchmarks {\n  name: "b4"\n  environment_configs { id: "test" }\n}'),
      0,
      None,
    ),
    (
      "escaped_quotes_and_whitespace",
      (
        "benchmarks {\n"
        '  name: "b5"\n'
        "  workload {\n"
        '    action: "actions/checkout@0123456789abcdef0123456789abcdef01234567"\n'
        "  }\n"
        '  environment_configs { id: "test" }\n'
        "}"
      ),
      1,
      None,
    ),
    (
      "malformed_sha_hex_overflow",
      (
        "benchmarks {\n"
        '  name: "b6"\n'
        "  workload {\n"
        '    action: "actions/checkout@0123456789abcdef0123456789abcdef01234567abcdef" # Too long\n'
        "  }\n"
        '  environment_configs { id: "test" }\n'
        "}"
      ),
      None,
      SecurityValidationError,
    ),
    (
      "path_traversal_in_remote_action",
      (
        "benchmarks {\n"
        '  name: "b7"\n'
        "  workload {\n"
        '    action: "actions/checkout/../malicious@0123456789abcdef0123456789abcdef01234567"\n'
        "  }\n"
        '  environment_configs { id: "test" }\n'
        "}"
      ),
      None,
      SecurityValidationError,
    ),
    (
      "backslash_evasion",
      (
        "benchmarks {\n"
        '  name: "b8"\n'
        "  workload {\n"
        '    action: "actions\\\\checkout@0123456789abcdef0123456789abcdef01234567"\n'
        "  }\n"
        '  environment_configs { id: "test" }\n'
        "}"
      ),
      None,
      SecurityValidationError,
    ),
  ],
)
def test_comprehensive_registry_scenarios(
  name, content, expected_count, expected_exception, tmp_path
):
  """Exhaustive check of various Protobuf formatting and edge cases."""
  registry_file = tmp_path / f"{name}.pbtxt"
  registry_file.write_text(content)

  if expected_exception:
    with pytest.raises(expected_exception):
      validate_external_file(registry_file)
  else:
    count = validate_external_file(registry_file)
    assert count == expected_count


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
