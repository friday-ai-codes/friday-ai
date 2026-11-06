"""Guard both backend CI jobs against the unavailable Ubuntu 26.04 patch pin."""

import re
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/ci.yaml"


@pytest.fixture(params=["server-ci", "postgres-queue"])
def job(request):
    return yaml.safe_load(WORKFLOW.read_text())["jobs"][request.param]


def assert_ci_python(job):
    assert job["runs-on"] == "ubuntu-26.04"
    steps = job["steps"]
    (setup,) = (step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
    assert setup["with"].get("python-version") == "3.14"
    assert "python-version-file" not in setup["with"]
    assert not setup["with"].get("allow-prereleases", False)

    binding = (
        f'echo "UV_PYTHON=${{{{ steps.{setup["id"]}.outputs.python-path }}}}" >> "$GITHUB_ENV"'
    )
    commands = [step.get("run", "") for step in steps]
    binding_index = commands.index(binding)
    assert binding_index > steps.index(setup)
    assert "UV_PYTHON" not in job.get("env", {})
    assert any("uv sync --locked --dev" in cmd for cmd in commands)
    for index, (step, script) in enumerate(zip(steps, commands, strict=True)):
        assert "UV_PYTHON" not in step.get("env", {})
        if index != binding_index:
            assert "UV_PYTHON=" not in script
        for command in re.findall(r"(?m)^[ \t]*uv (?:sync|run)\b[^\n]*", script):
            assert index > binding_index
            assert "--locked" in command.split()
            assert "--python" not in command


def test_backend_uses_installed_stable_python(job):
    assert_ci_python(job)


@pytest.mark.parametrize("regression", ["version_file", "exact_patch", "uv_patch"])
def test_rejects_old_patch_selection(job, regression):
    broken = deepcopy(job)
    setup = next(
        s for s in broken["steps"] if s.get("uses", "").startswith("actions/setup-python@")
    )
    if regression == "version_file":
        del setup["with"]["python-version"]
        setup["with"]["python-version-file"] = "server/.python-version"
    elif regression == "exact_patch":
        setup["with"]["python-version"] = "3.14.2"
    else:
        step = next(s for s in broken["steps"] if "uv sync" in s.get("run", ""))
        step["run"] = step["run"].replace("uv sync", "uv sync --python 3.14.2")
    with pytest.raises(AssertionError):
        assert_ci_python(broken)
