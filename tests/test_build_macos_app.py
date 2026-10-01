"""`is_running` decides whether the installer may rmtree an existing bundle.

Both halves matter: a false positive refuses a legitimate build, and a false
negative deletes a bundle that is still running.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "build_macos_app.py"


@pytest.fixture(scope="module")
def build_module():
    spec = importlib.util.spec_from_file_location("build_macos_app", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def app_path(build_module):
    return Path("/Applications") / f"{build_module.APP_NAME}.app"


def executable_of(build_module, app_path):
    return str(app_path / "Contents" / "MacOS" / build_module.APP_NAME)


def with_ps_output(monkeypatch, build_module, lines, exc=None):
    def fake_run(argv, **kwargs):
        if exc is not None:
            raise exc
        return subprocess.CompletedProcess(argv, 0, stdout="\n".join(lines), stderr="")

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)


class TestIsRunning:
    def test_finds_the_bare_command(self, build_module, app_path, monkeypatch):
        exe = executable_of(build_module, app_path)
        with_ps_output(monkeypatch, build_module, ["/sbin/launchd", exe])
        assert build_module.is_running(app_path)

    def test_finds_the_command_with_arguments(self, build_module, app_path, monkeypatch):
        exe = executable_of(build_module, app_path)
        with_ps_output(monkeypatch, build_module, [f"{exe} --debug"])
        assert build_module.is_running(app_path)

    def test_finds_it_when_ps_pads_the_line(self, build_module, app_path, monkeypatch):
        exe = executable_of(build_module, app_path)
        with_ps_output(monkeypatch, build_module, [f"   {exe} --debug"])
        assert build_module.is_running(app_path)

    def test_ignores_a_process_that_merely_mentions_the_path(
        self, build_module, app_path, monkeypatch
    ):
        """The reason for dropping `pgrep -f`: an editor or tail must not count."""
        exe = executable_of(build_module, app_path)
        with_ps_output(monkeypatch, build_module, [f"tail -f {exe}", f"vim {exe}.c"])
        assert not build_module.is_running(app_path)

    def test_says_not_running_when_nothing_matches(
        self, build_module, app_path, monkeypatch
    ):
        with_ps_output(monkeypatch, build_module, ["/sbin/launchd", "/usr/sbin/cupsd"])
        assert not build_module.is_running(app_path)


class TestIsRunningCannotAnswer:
    """A failed `ps` must not be read as "not running" -- install() would then
    rmtree a live bundle -- and must not escape as a traceback either."""

    def test_a_failing_ps_raises_build_error(self, build_module, app_path, monkeypatch):
        with_ps_output(
            monkeypatch, build_module, [],
            exc=subprocess.CalledProcessError(1, ["ps", "-axo", "command="]),
        )
        with pytest.raises(build_module.BuildError, match="Could not check"):
            build_module.is_running(app_path)

    def test_a_missing_ps_raises_build_error(self, build_module, app_path, monkeypatch):
        with_ps_output(
            monkeypatch, build_module, [], exc=FileNotFoundError("ps")
        )
        with pytest.raises(build_module.BuildError, match="Could not check"):
            build_module.is_running(app_path)

    def test_build_error_is_what_main_already_handles(self, build_module):
        """main() catches (BuildError, ImportError, OSError); CalledProcessError
        is a SubprocessError and would have escaped it."""
        assert not issubclass(subprocess.CalledProcessError, OSError)
        assert issubclass(build_module.BuildError, Exception)
