"""Git hygiene for the laboratory's sensitive runtime artifacts.

The console writes transcripts, manual submissions, LLM judgments and caller
audio under its results root. `evaluator/.gitignore` already covers the default
`experiments/results/`, but `--results` may point anywhere inside the package,
so the directory names themselves must stay untracked. This check fails if a
rule is dropped, because a leaked transcript is not recoverable by review.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parent

# Directory name -> a representative file the laboratory writes there.
SENSITIVE_ARTIFACTS = {
    "_history": "calls-v1.json",
    "_chat-sessions": "manual-agent.json",
    "_manual-calls": "mic-abc.json",
    "_live-audio": "mic-abc/caller.wav",
    "_judgments": "fingerprint.json",
}


def _guarded_by_git(path: Path) -> bool:
    return subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "-q", str(path)],
        capture_output=True,
        check=False,
    ).returncode == 0


@pytest.mark.parametrize("directory,artifact", SENSITIVE_ARTIFACTS.items())
def test_laboratory_runtime_artifacts_stay_untracked(directory: str, artifact: str) -> None:
    if not (REPO / ".git").exists():
        pytest.skip("no hay checkout de Git para comprobar las reglas de ignore")
    assert _guarded_by_git(PACKAGE / directory / artifact), (
        f"evaluator/{directory}/ no está ignorado por Git"
    )


def test_default_results_root_is_ignored() -> None:
    if not (REPO / ".git").exists():
        pytest.skip("no hay checkout de Git para comprobar las reglas de ignore")
    assert _guarded_by_git(PACKAGE / "experiments" / "results" / "_history" / "calls-v1.json")
