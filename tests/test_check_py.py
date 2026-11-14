"""scripts/check.py: `full` must run the real gates, not --help theatre."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_check():
    spec = importlib.util.spec_from_file_location("check_script", ROOT / "scripts" / "check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    def __init__(self, failures=None):
        self.calls = []
        self.failures = failures or {}

    def __call__(self, *args):
        self.calls.append(args)
        joined = " ".join(args)
        for marker, rc in self.failures.items():
            if marker in joined:
                return rc
        return 0


def scripts_called(runner):
    return [" ".join(call) for call in runner.calls]


def test_ci_runs_only_the_offline_suite():
    check = load_check()
    runner = FakeRunner()
    rc = check.main(["ci"], runner=runner, ref_exists=lambda ref: True)
    assert rc == 0
    calls = scripts_called(runner)
    assert any("pytest" in call for call in calls)
    assert not any("check_us_spelling" in call for call in calls)
    assert not any("check_contribution" in call for call in calls)


def test_full_runs_spelling_gate_for_real():
    check = load_check()
    runner = FakeRunner()
    rc = check.main(["full"], runner=runner, ref_exists=lambda ref: True)
    assert rc == 0
    calls = scripts_called(runner)
    assert any("pytest" in call for call in calls)
    spelling = [call for call in calls if "check_us_spelling" in call]
    assert spelling, "full mode never ran the spelling checker"
    assert "--base" in spelling[0]
    assert "--help" not in spelling[0]


def test_full_runs_contribution_gate_when_metadata_supplied(tmp_path):
    check = load_check()
    metadata = tmp_path / "metadata.json"
    metadata.write_text('{"body": "x", "files": []}')
    runner = FakeRunner()
    rc = check.main(["full", "--metadata", str(metadata)],
                    runner=runner, ref_exists=lambda ref: True)
    assert rc == 0
    contribution = [call for call in scripts_called(runner)
                    if "check_contribution" in call]
    assert contribution, "full mode never ran the contribution checker"
    assert "--metadata" in contribution[0]
    assert "--help" not in contribution[0]


def test_full_propagates_spelling_failure():
    check = load_check()
    runner = FakeRunner(failures={"check_us_spelling": 3})
    rc = check.main(["full"], runner=runner, ref_exists=lambda ref: True)
    assert rc == 3


def test_full_propagates_contribution_failure(tmp_path):
    check = load_check()
    metadata = tmp_path / "metadata.json"
    metadata.write_text('{"body": "x", "files": []}')
    runner = FakeRunner(failures={"check_contribution": 4})
    rc = check.main(["full", "--metadata", str(metadata)],
                    runner=runner, ref_exists=lambda ref: True)
    assert rc == 4


def test_full_propagates_test_failure_and_stops():
    check = load_check()
    runner = FakeRunner(failures={"pytest": 5})
    rc = check.main(["full"], runner=runner, ref_exists=lambda ref: True)
    assert rc == 5
    assert not any("check_us_spelling" in call for call in scripts_called(runner))


def test_unknown_mode_is_an_error_and_runs_nothing():
    check = load_check()
    runner = FakeRunner()
    rc = check.main(["bogus"], runner=runner, ref_exists=lambda ref: True)
    assert rc == 2
    assert runner.calls == []
