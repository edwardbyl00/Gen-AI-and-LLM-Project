import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TESTS = [
    "test_retrieval.py",
    "test_dates.py",
    "test_data_integration.py",
    "test_policy_agent.py",
    "test_pipeline.py",
]


failures = []


for test_file in TESTS:
    path = PROJECT_ROOT / "tests" / test_file

    print("\n" + "=" * 60)
    print(f"RUNNING {test_file}")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=PROJECT_ROOT,
    )

    if result.returncode != 0:
        failures.append(test_file)


print("\n" + "=" * 60)
print("P5 REGRESSION SUMMARY")
print("=" * 60)


if failures:
    print("FAILED:")

    for test_file in failures:
        print("-", test_file)

    sys.exit(1)


print(f"All {len(TESTS)} test files passed.")