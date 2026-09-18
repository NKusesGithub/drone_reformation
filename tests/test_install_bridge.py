"""scripts/install_bridge.sh: copy the CrazySwarm bridge into the workspace.

Every test runs against throwaway git repositories on disk, so nothing here
touches the network or the real CrazySwarm2 workspace.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install_bridge.sh"

# Only the routes the script checks for need to be here.
FAKE_APP = '''\
from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()


@app.get("/health")
def health():
    return {"ready": True}


@router.get("/drones/status")
def status():
    return []


@router.get("/drones/{drone_id}/status")
def one(drone_id: int):
    return {}


@router.post("/drones/{drone_id}/arm")
def arm(drone_id: int):
    return {}


@router.post("/drones/{drone_id}/takeoff")
def takeoff(drone_id: int):
    return {}


@router.post("/drones/{drone_id}/go-to")
def go_to(drone_id: int):
    return {}


@router.post("/drones/{drone_id}/land")
def land(drone_id: int):
    return {}


app.include_router(router)
'''


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def run_script(*args, expect_ok=True):
    result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
    if expect_ok:
        assert result.returncode == 0, result.stderr or result.stdout
    else:
        assert result.returncode != 0, result.stdout
    return result


@pytest.fixture
def fork(tmp_path):
    """A stand-in for the Kojk-STEngg fork, with api/ on a 'kenneth' branch."""
    path = tmp_path / "fork"
    (path / "api").mkdir(parents=True)
    (path / "api" / "app.py").write_text(FAKE_APP)
    (path / "api" / "__init__.py").write_text("")
    (path / "api" / "requirements.txt").write_text("fastapi\n")
    git(path if path.exists() else tmp_path, "init", "-q", "-b", "kenneth", str(path))
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "test")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "bridge")
    return path


@pytest.fixture
def workspace(tmp_path):
    """A stand-in for the CrazySwarm2 workspace: a repo with no api/."""
    path = tmp_path / "CrazySwarm2-with-Mocap"
    path.mkdir()
    git(tmp_path, "init", "-q", str(path))
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "test")
    (path / "README.md").write_text("workspace\n")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "initial")
    return path


def install(workspace, fork, *extra, expect_ok=True):
    return run_script("--repo", str(workspace), "--url", str(fork), *extra, expect_ok=expect_ok)


def test_it_copies_the_bridge_in(workspace, fork):
    result = install(workspace, fork)

    assert (workspace / "api" / "app.py").read_text() == FAKE_APP
    assert (workspace / "api" / "requirements.txt").exists()
    assert "all the routes Docker 1 uses are present" in result.stdout


def test_the_copy_is_staged_not_committed(workspace, fork):
    """Committing another repo is the user's decision, not the script's."""
    install(workspace, fork)

    assert "A  api/app.py" in git(workspace, "status", "--short")
    assert "bridge" not in git(workspace, "log", "--oneline")


def test_running_it_twice_is_fine(workspace, fork):
    install(workspace, fork)
    second = install(workspace, fork)

    assert "already up to date" in second.stdout


def test_it_picks_up_a_newer_bridge(workspace, fork):
    install(workspace, fork)
    (fork / "api" / "app.py").write_text(FAKE_APP + "\n# newer\n")
    git(fork, "commit", "-qam", "update bridge")

    install(workspace, fork)

    assert "# newer" in (workspace / "api" / "app.py").read_text()


def test_your_own_edits_are_not_overwritten(workspace, fork):
    install(workspace, fork)
    git(workspace, "commit", "-qm", "add bridge")
    (workspace / "api" / "app.py").write_text("# my debugging changes\n")

    result = install(workspace, fork, expect_ok=False)

    assert "uncommitted edits" in result.stderr
    assert (workspace / "api" / "app.py").read_text() == "# my debugging changes\n"


def test_force_overwrites_them(workspace, fork):
    install(workspace, fork)
    git(workspace, "commit", "-qm", "add bridge")
    (workspace / "api" / "app.py").write_text("# my debugging changes\n")

    install(workspace, fork, "--force")

    assert (workspace / "api" / "app.py").read_text() == FAKE_APP


def test_a_dry_run_writes_nothing(workspace, fork):
    result = install(workspace, fork, "--dry-run")

    assert not (workspace / "api").exists()
    assert "nothing was written" in result.stdout


def test_a_bridge_missing_our_routes_is_flagged(workspace, fork):
    (fork / "api" / "app.py").write_text('from fastapi import FastAPI\napp = FastAPI()\n')
    git(fork, "commit", "-qam", "gut the bridge")

    result = install(workspace, fork)

    assert "does not expose" in result.stderr
    assert "Docker 1 calls those" in result.stderr


def test_a_branch_without_the_bridge_fails_loudly(workspace, fork):
    result = install(workspace, fork, "--branch", "kenneth", "--remote", "kojk")
    assert result.returncode == 0

    missing = run_script("--repo", str(workspace), "--url", str(fork),
                         "--branch", "nope", "--remote", "other", expect_ok=False)
    assert "couldn't find remote ref nope" in missing.stderr or missing.returncode != 0


def test_a_remote_pointing_elsewhere_is_not_silently_changed(workspace, fork, tmp_path):
    install(workspace, fork)
    other = tmp_path / "other-fork"
    other.mkdir()

    result = install(workspace, other, expect_ok=False)
    assert "already points at" in result.stderr

    forced = install(workspace, fork, "--force")
    assert forced.returncode == 0


def test_a_directory_that_is_not_a_repo_is_refused(tmp_path, fork):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    result = run_script("--repo", str(plain), "--url", str(fork), expect_ok=False)
    assert "Not a git repository" in result.stderr


def test_a_missing_workspace_is_refused(tmp_path, fork):
    result = run_script("--repo", str(tmp_path / "nowhere"), "--url", str(fork), expect_ok=False)
    assert "No such directory" in result.stderr
