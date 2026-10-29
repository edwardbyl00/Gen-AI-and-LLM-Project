import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = PROJECT_ROOT / "tests"


# Existing P5 standalone regression tests
SCRIPT_TESTS = [
    "test_retrieval.py",
    "test_dates.py",
    "test_data_integration.py",
    "test_policy_agent.py",
    "test_pipeline.py",
]


# Pytest-based integration / supervisor tests
PYTEST_TESTS = [
    "test_supervisor_checks.py",
    "test_supervisor_evaluate.py",
    "test_supervisor_pipeline.py",
    "test_supervisor_router.py",
    "test_supervisor_synthesis.py",
    "test_supervisor_decomposition.py",
    "test_graph.py",
    "test_graph_decomposition.py",
    "test_usage_log.py",
    "test_experiment_tracking.py",
    "test_p5_integration.py",
    "test_p5_agentic_control.py",
]


failures = []


# --------------------------------------------------
# 1. Existing standalone P5 tests
# --------------------------------------------------

for test_file in SCRIPT_TESTS:
    path = TEST_DIR / test_file

    print("\n" + "=" * 60)
    print(f"RUNNING {test_file}")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=PROJECT_ROOT,
    )

    if result.returncode != 0:
        failures.append(test_file)


# --------------------------------------------------
# 2. Pytest integration / supervisor tests
# --------------------------------------------------

print("\n" + "=" * 60)
print("RUNNING PYTEST INTEGRATION TESTS")
print("=" * 60)

pytest_paths = [
    str(TEST_DIR / test_file)
    for test_file in PYTEST_TESTS
]

result = subprocess.run(
    [
        sys.executable,
        "-m",
        "pytest",
        *pytest_paths,
        "-v",
    ],
    cwd=PROJECT_ROOT,
)

if result.returncode != 0:
    failures.append("pytest integration suite")


# --------------------------------------------------
# Final summary
# --------------------------------------------------

print("\n" + "=" * 60)
print("FULL REGRESSION SUMMARY")
print("=" * 60)

if failures:
    print("FAILED:")

    for item in failures:
        print("-", item)

    sys.exit(1)


print(
    f"All {len(SCRIPT_TESTS)} standalone P5 test files passed."
)

print(
    f"All {len(PYTEST_TESTS)} pytest test files passed."
)

print("FULL REGRESSION SUITE PASSED.")
