import argparse
import json
import string
import sys
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

from google.protobuf import text_format
from benchmarking.proto import benchmark_registry_pb2


class SecurityValidationError(Exception):
  """Raised when security validation fails."""

  def __init__(self, errors: list[str]):
    self.errors = errors
    super().__init__("\n".join(errors))


@dataclass(frozen=True)
class SecurityPolicy:
  """Represents the application security policy."""

  trusted_orgs: list[str]


@cache
def load_security_policy() -> SecurityPolicy:
  """Loads the security policy from the package resources."""
  try:
    # Look for the policy file within the current package
    policy_resource = (
      resources.files("benchmarking.validate_registry") / "security_policy.json"
    )

    if policy_resource.exists():
      with policy_resource.open("r") as f:
        data = json.load(f)
        return SecurityPolicy(trusted_orgs=data.get("trusted_orgs", []))
  except Exception as e:
    print(f"Error loading security policy resource: {e}")

  # Fail if no policy file is found or if it's unreadable
  print("Error: Could not find or read security_policy.json in package resources.")
  sys.exit(1)


def get_trusted_orgs() -> list[str]:
  """Returns the trusted orgs list from the cached policy."""
  policy = load_security_policy()
  return policy.trusted_orgs


def _is_hex(s: str) -> bool:
  """Checks if a string is a valid hexadecimal string."""
  return all(c in string.hexdigits for c in s)


def validate_action_string(action_id: str) -> tuple[bool, str]:
  """Checks if an action reference string meets security requirements."""
  trusted_orgs = get_trusted_orgs()

  # Global Sanity Checks (Apply to both local and remote)
  if any(c.isspace() for c in action_id):
    return False, f"Malformed reference (contains whitespace): {action_id}"

  if "../" in action_id:
    return False, f"Path traversal detected: {action_id}"

  if "\\" in action_id:
    return False, f"Backslashes are not allowed: {action_id}"

  # Handle Local Actions
  if action_id.startswith("./"):
    return True, ""

  # Parse Remote Action (org/repo@ref)
  # Structured parsing without regex for SSCI compliance
  if "@" not in action_id:
    return False, f"Malformed reference (missing @): {action_id}"

  if action_id.count("@") > 1:
    return False, f"Malformed reference (too many @): {action_id}"

  full_repo, ref = action_id.split("@")

  if "/" not in full_repo:
    return False, f"Malformed reference (missing org/repo separator): {action_id}"

  # Split only at the FIRST slash to extract the organization.
  # This allows subdirectories within the repository (e.g., org/repo/path/to/action).
  org, repo_path = full_repo.split("/", 1)

  if not org or not repo_path:
    return False, f"Malformed reference (empty org or repo): {action_id}"

  # Org Allowlist Check
  if org not in trusted_orgs:
    return (
      False,
      f"Untrusted organization '{org}'. Allowed: {', '.join(trusted_orgs)}",
    )

  # SHA Pinning Check
  # SHA-1: 40-char hex
  is_sha1 = len(ref) == 40 and _is_hex(ref)

  # SHA-256: "sha256:" followed by 64-char hex
  is_sha256 = False
  if ref.startswith("sha256:"):
    digest = ref[7:]
    is_sha256 = len(digest) == 64 and _is_hex(digest)

  if not (is_sha1 or is_sha256):
    return (
      False,
      (
        f"Action not pinned to a valid SHA (found tag/branch or invalid digest: @{ref})"
      ),
    )

  return True, ""


def validate_external_file(file_path: Path) -> int:
  """Validates actions in a specific file using Protobuf parsing.

  Returns:
    The number of actions checked on success.

  Raises:
    FileNotFoundError: If the registry file is not found.
    ValueError: If the file cannot be parsed as Protobuf.
    SecurityValidationError: If any actions fail security checks.
  """
  if not file_path.exists():
    raise FileNotFoundError(f"Registry file not found: {file_path}")

  try:
    content = file_path.read_text()
    suite = benchmark_registry_pb2.BenchmarkSuite()
    text_format.Parse(content, suite)
  except Exception as e:
    raise ValueError(f"Failed to parse benchmark registry as Protobuf: {e}") from e

  errors = []
  action_count = 0

  for benchmark in suite.benchmarks:
    if benchmark.HasField("workload"):
      action_id = benchmark.workload.action
      if action_id:
        action_count += 1
        valid, msg = validate_action_string(action_id)
        if not valid:
          errors.append(f"Benchmark '{benchmark.name}': Action '{action_id}': {msg}")

  if errors:
    raise SecurityValidationError(errors)

  return action_count


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Validates a benchmark registry for SSCI security compliance."
  )
  parser.add_argument(
    "registry_path",
    type=Path,
    help="Path to the .pbtxt benchmark registry file.",
  )
  args = parser.parse_args()

  try:
    action_count = validate_external_file(args.registry_path)
    if action_count == 0:
      print(f"Note: No actions found in registry: {args.registry_path}")
    else:
      print(f"Security Validation PASSED ({action_count} actions checked).")
  except FileNotFoundError as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
  except SecurityValidationError as e:
    print("\nSecurity Validation FAILED:", file=sys.stderr)
    for err in e.errors:
      print(f"  - {err}", file=sys.stderr)
    sys.exit(1)
  except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
