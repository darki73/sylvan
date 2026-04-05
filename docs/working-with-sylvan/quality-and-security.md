# Quality and Security

The server includes a static analysis suite that checks test coverage,
documentation coverage, code smells, security patterns, and code duplication --
without executing any tests or running external tools. Think of it as a lightweight
SonarQube built into your code intelligence layer.


## Running a quality report with `code_health_report`

To get a full quality analysis of a repository:

```
code_health_report(repo="my-project")
```

```json
{
  "repository": "my-project",
  "quality_gate": {
    "passed": false,
    "failures": [
      "Test coverage 50.8% < 60.0% minimum",
      "Documentation coverage 44.4% < 80.0% minimum"
    ]
  },
  "coverage": {
    "test_coverage_percent": 50.8,
    "uncovered_count": 531,
    "covered_count": 548,
    "uncovered_symbols": [
      "src/cli.py::init#function",
      "src/cli.py::status#function",
      "..."
    ]
  },
  "documentation": {
    "doc_coverage_percent": 44.4,
    "type_coverage_percent": 32.5,
    "total_symbols": 3079
  },
  "code_smells": {
    "total": 24,
    "by_severity": {"high": 0, "medium": 24, "low": 0},
    "items": [
      {
        "symbol": "serve",
        "file": "src/cli.py",
        "type": "too_many_parameters",
        "severity": "medium",
        "message": "serve has 16 parameters (max recommended: 8)"
      }
    ]
  },
  "security": {
    "total": 0,
    "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    "findings": []
  },
  "duplication": {
    "duplicate_groups": 0,
    "groups": []
  },
  "dead_code": {
    "total": 713,
    "items": [
      {"name": "run_benchmark", "kind": "function", "file": "benchmarks/compare.py"}
    ]
  }
}
```

The response is structured into sections. Here is what each one covers.


## The quality gate

The `quality_gate` section gives a pass/fail verdict with specific reasons for
failure:

```json
"quality_gate": {
  "passed": false,
  "failures": [
    "Test coverage 50.8% < 60.0% minimum",
    "Documentation coverage 44.4% < 80.0% minimum"
  ]
}
```

The gate checks minimum thresholds for test coverage and documentation coverage.
When both pass, `passed` is `true` and `failures` is empty.


## What it checks

**Test coverage** -- The server matches test files to source symbols using naming
conventions and import analysis. A function is "covered" if a corresponding test
file exists and references it. This is static analysis, not runtime coverage --
it tells you which symbols have no tests at all, not which lines are exercised.

**Documentation coverage** -- The percentage of symbols that have docstrings.
`type_coverage_percent` tracks how many have type annotations.

**Code smells** -- Structural issues detected by pattern matching:

| Smell type | What it catches |
|---|---|
| `too_many_parameters` | Functions with more than 8 parameters |
| `too_long` | Functions or classes exceeding 200 lines |
| `too_many_methods` | Classes with more than 20 methods |

Each smell has a severity (low, medium, high) and a human-readable message.

**Security patterns** -- Static pattern matching for common security issues:
hardcoded credentials, SQL injection patterns, insecure randomness, and similar
findings. Each finding has a severity level (critical, high, medium, low).

**Code duplication** -- Detects blocks of code that are duplicated across files.
Results are grouped by duplicate content, showing all locations where each block
appears.

**Dead code** -- Symbols that are defined but never imported or referenced
anywhere in the indexed codebase. These are candidates for removal.


## Per-symbol quality with `find_tech_debt`

While `code_health_report` gives you the overview, `find_tech_debt` lets you drill
into individual symbols:

```
find_tech_debt(repo="my-project", untested_only=true, limit=20)
```

```json
{
  "symbols": [
    {
      "symbol_id": "src/handlers/auth.py::validate_token#function",
      "name": "validate_token",
      "has_tests": false,
      "has_docs": true,
      "has_types": true,
      "complexity": 12
    }
  ]
}
```

Filters let you focus on what matters:

| Filter | What it shows |
|---|---|
| `untested_only=true` | Only symbols without tests |
| `undocumented_only=true` | Only symbols without docstrings |
| `min_complexity=10` | Only symbols above a complexity threshold |

Use this to target code review or prioritize technical debt. A function that is
untested, undocumented, and highly complex is a higher risk than one that is
merely missing a docstring.


## Using quality data in your workflow

The quality report is most useful at two points:

**Before a code review** -- Run `code_health_report` to see the current state.
Focus review attention on areas with low coverage or code smells. Use
`find_tech_debt(untested_only=true)` to find which functions in the changed files
lack tests.

**After a refactoring** -- Run the report again to confirm you have not introduced
new smells or reduced coverage. Compare dead code counts to verify that removed
code is actually gone from the index.

The report is fast (typically under 2 seconds) because all analysis is static --
it works entirely from the indexed data without hitting the filesystem or running
any tests.
