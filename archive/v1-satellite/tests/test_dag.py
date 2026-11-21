# DAG wrap
"""The live DAG calls run_date. Importing it is optional; the source is the contract."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DAG_PATH = REPO / "dags" / "field_days_dag.py"


def test_dag_source_calls_the_same_pipeline() -> None:
    text = DAG_PATH.read_text()
    assert "from geopipeline.pipeline import run_scheduled_date" in text
    assert 'dag_id="field_days"' in text
    assert "run_scheduled_date(" in text
    assert "satellite_ingestion" not in text
    assert "PokeReturnValue" not in text


def test_field_days_dag_imports_when_airflow_is_installed() -> None:
    if os.environ.get("GEOPIPELINE_REQUIRE_AIRFLOW") != "1":
        pytest.importorskip("airflow")
    import sys

    sys.path.insert(0, str(DAG_PATH.parent))
    from field_days_dag import dag

    assert dag.dag_id == "field_days"
    assert "run_field_days" in dag.task_dict
    assert dag.catchup is False


def test_ci_and_makefile_wire_airflow_dag_import() -> None:
    makefile = (REPO / "Makefile").read_text()
    ci_workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text()

    def _recipe(target: str) -> str:
        match = re.search(rf"(?m)^{re.escape(target)}:\n((?:\t.*\n?)+)", makefile)
        assert match is not None, f"make target {target} missing"
        return match.group(1)

    install_recipe = _recipe("install")
    assert "--extra dev" in install_recipe
    assert "--extra airflow" not in install_recipe

    airflow_recipe = _recipe("test-airflow")
    assert "--extra airflow" in airflow_recipe
    assert "--frozen" in airflow_recipe
    assert "GEOPIPELINE_REQUIRE_AIRFLOW=1" in airflow_recipe
    assert "tests/test_dag.py" in airflow_recipe

    assert "test-airflow" in _recipe("help")
    _assert_ci_job_runs_command(ci_workflow, "airflow-dag-import", "make test-airflow")


def _strip_yaml_comment(line: str) -> str:
    """Return a YAML line without trailing inline `#` comments outside quotes."""
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif (
            ch == "#"
            and not in_single
            and not in_double
            and (idx == 0 or line[idx - 1].isspace())
        ):
            return line[:idx]
    return line


def _is_block_scalar_header(rhs: str) -> bool:
    """Return True if `rhs` starts a YAML block scalar (`|`, `>`, `|+`, `|-`, `|2`, etc.)."""
    return bool(re.match(r"^[|>](?:\d+[+-]?|[+-]\d*)?$", rhs))


def _ci_job_block(workflow_text: str, job_name: str) -> list[str]:
    """Extract lines belonging to `jobs.<job_name>` using YAML indentation."""
    lines = workflow_text.splitlines()
    jobs_indent: int | None = None
    job_key_indent: int | None = None
    collecting = False
    collected: list[str] = []

    for raw in lines:
        code = _strip_yaml_comment(raw).rstrip()
        if not code.strip():
            if collecting:
                collected.append(raw)
            continue
        indent = len(code) - len(code.lstrip(" "))
        stripped = code.strip()
        if jobs_indent is None:
            if stripped == "jobs:" and indent == 0:
                jobs_indent = indent
            continue
        if indent <= jobs_indent:
            break
        if job_key_indent is None:
            job_key_indent = indent
        if collecting:
            if indent <= job_key_indent:
                break
            collected.append(raw)
        elif indent == job_key_indent and stripped == f"{job_name}:":
            collecting = True

    assert collecting, f"Missing CI job {job_name!r} under jobs:"
    return collected


def _assert_ci_job_runs_command(
    workflow_text: str, job_name: str, command: str
) -> None:
    """Assert `command` appears in an executable `steps[*].run` entry inside `jobs.<job_name>`."""
    block = _ci_job_block(workflow_text, job_name)
    steps_indent: int | None = None
    item_key_indent: int | None = None
    scalar_key: str | None = None
    scalar_indent: int | None = None

    for raw in block:
        raw_stripped = raw.strip()
        if not raw_stripped or raw_stripped.startswith("#"):
            continue
        code = _strip_yaml_comment(raw).rstrip()
        if not code.strip():
            continue
        indent = len(code) - len(code.lstrip(" "))
        stripped = code.strip()

        if scalar_key is not None and scalar_indent is not None:
            if indent > scalar_indent:
                if scalar_key == "run" and command in stripped:
                    return
                continue
            scalar_key = None
            scalar_indent = None

        if steps_indent is None:
            if stripped == "steps:":
                steps_indent = indent
                item_key_indent = None
            continue

        if indent <= steps_indent:
            steps_indent = None
            item_key_indent = None
            continue

        key_indent = indent
        key_text = stripped
        if key_text.startswith("- "):
            after_dash = key_text[2:]
            offset = 2 + (len(after_dash) - len(after_dash.lstrip(" ")))
            key_indent = indent + offset
            key_text = after_dash.lstrip(" ")
            item_key_indent = key_indent
        elif item_key_indent is None:
            item_key_indent = indent

        if key_indent != item_key_indent or ":" not in key_text:
            continue

        key, _, rhs = key_text.partition(":")
        key = key.strip()
        rhs = rhs.strip()
        if _is_block_scalar_header(rhs):
            scalar_key = key
            scalar_indent = key_indent
        elif key == "run" and command in rhs:
            return

    raise AssertionError(f"CI job {job_name!r} does not execute {command!r}")


def test_ci_airflow_guardrail_rejects_misplaced_make_test_airflow() -> None:
    misplaced_ci = (
        "jobs:\n"
        "  local-demo:\n"
        "    steps:\n"
        "      - run: make test-airflow\n"
        "  airflow-dag-import:\n"
        "    steps:\n"
        "      - run: make lint\n"
    )
    with pytest.raises(AssertionError, match="airflow-dag-import"):
        _assert_ci_job_runs_command(
            misplaced_ci, "airflow-dag-import", "make test-airflow"
        )

    commented_ci = (
        "jobs:\n"
        "  airflow-dag-import:\n"
        "    steps:\n"
        "      # - run: make test-airflow\n"
        "      - name: make test-airflow\n"
        "        run: echo nope\n"
    )
    with pytest.raises(AssertionError, match="airflow-dag-import"):
        _assert_ci_job_runs_command(
            commented_ci, "airflow-dag-import", "make test-airflow"
        )

    nested_with_ci = (
        "jobs:\n"
        "  airflow-dag-import:\n"
        "    steps:\n"
        "      - uses: actions/example@v1\n"
        "        with:\n"
        "          run: make test-airflow\n"
        "      - name: |\n"
        "          run: make test-airflow\n"
        "        run: echo nope\n"
        "      - run: |\n"
        "          echo step1\n"
        "        name: make test-airflow\n"
    )
    with pytest.raises(AssertionError, match="airflow-dag-import"):
        _assert_ci_job_runs_command(
            nested_with_ci, "airflow-dag-import", "make test-airflow"
        )

    multiline_valid_ci = (
        "jobs:\n"
        "  airflow-dag-import:\n"
        "    steps:\n"
        "      - name: Verify DAG import\n"
        "        run: |-\n"
        "          echo checking\n"
        "          make test-airflow\n"
    )
    _assert_ci_job_runs_command(
        multiline_valid_ci, "airflow-dag-import", "make test-airflow"
    )
