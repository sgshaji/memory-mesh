"""Internal worker for explicitly requested unittest checks; not a sandbox."""

import json
import os
import platform
import sys
import unittest
from pathlib import Path


class DiscoveryBoundaryError(Exception):
    pass


class BoundedLoader(unittest.TestLoader):
    def __init__(self, workspace: Path, start: Path):
        super().__init__()
        self.workspace = workspace.resolve()
        self.directories = {start.resolve()}

    def _find_test_path(self, full_path, pattern):
        path = Path(full_path)
        try:
            resolved = path.resolve()
            resolved.relative_to(self.workspace)
        except (OSError, ValueError, RuntimeError) as exc:
            raise DiscoveryBoundaryError from exc
        if path.is_dir():
            if resolved in self.directories:
                raise DiscoveryBoundaryError
            self.directories.add(resolved)
        return super()._find_test_path(full_path, pattern)


class ObservedResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.active = None
        self.incomplete = False
        self.checks_executed = 0

    def startTest(self, test):
        super().startTest(test)
        self.active = test
        self.incomplete = False

    def addSkip(self, test, reason):
        if self.active is not None:
            self.incomplete = True
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.incomplete = True
        super().addExpectedFailure(test, err)

    def stopTest(self, test):
        if not self.incomplete:
            self.checks_executed += 1
        self.active = None
        super().stopTest(test)


def main() -> int:
    result_fd = os.dup(1)
    with open(os.devnull, "w", encoding="utf-8") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
        sys.path.insert(0, sys.argv[1])
        result = ObservedResult()
        boundary_violation = False
        try:
            suite = BoundedLoader(Path(sys.argv[1]), Path(sys.argv[2])).discover(sys.argv[2], pattern=sys.argv[3])
            suite.run(result)
        except DiscoveryBoundaryError:
            boundary_violation = True
        payload = {
            "protocol": 1,
            "tests_run": result.testsRun,
            "tests_skipped": len(result.skipped),
            "expected_failures": len(result.expectedFailures),
            "failures": len(result.failures) + len(result.unexpectedSuccesses),
            "errors": len(result.errors),
            "successful": result.wasSuccessful(),
            "tool_version": platform.python_version(),
            "checks_executed": result.checks_executed,
            "boundary_violation": boundary_violation,
        }
        os.write(result_fd, json.dumps(payload, allow_nan=False).encode("utf-8"))
    os.close(result_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
