# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "scripts" / "pii-scan"


def run_scan(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCANNER), *args], cwd=repo, text=True, capture_output=True)


def init_repo(tmp_path: Path, name: str, content: str, *, path: str = "sample.txt") -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    subprocess.run(["git", "add", path], cwd=tmp_path, check=True)
    return tmp_path


def test_staged_scan_blocks_private_path_and_sensitive_added_lines(tmp_path: Path) -> None:
    repo = init_repo(tmp_path, "staged", "safe\n")
    result = run_scan(repo, "--staged")
    assert result.returncode == 0

    (repo / "sample.txt").write_text(
        "BEGIN AI "
        + "TRANSCRIPT\n"
        + "person@"
        + "agency.invalid\n"
        + "212-34-"
        + "5678\n"
        + "202-"
        + "555-"
        + "0147\n"
        + "123456"
        + "789\n"
    )
    subprocess.run(["git", "add", "sample.txt"], cwd=repo, check=True)
    result = run_scan(repo, "--staged")
    assert result.returncode == 1
    assert "AI transcript marker" in result.stdout
    assert "non-mock email address" in result.stdout
    assert "US Social Security number" in result.stdout
    assert "US phone number" in result.stdout
    assert "long ID-like digit run" in result.stdout


def test_all_scan_blocks_private_paths_and_allows_mock_domains(tmp_path: Path) -> None:
    repo = init_repo(tmp_path, "all", "ok@example.com\n", path="tests/fixtures/mock/patient.csv")
    assert run_scan(repo, "--all").returncode == 0

    (repo / "bad.patient.txt").write_text("private")
    subprocess.run(["git", "add", "bad.patient.txt"], cwd=repo, check=True)
    result = run_scan(repo, "--all")
    assert result.returncode == 1
    assert "blocked personal-data path" in result.stdout


def test_staged_scan_blocks_ai_directory(tmp_path: Path) -> None:
    repo = init_repo(tmp_path, "ai-path", "safe\n", path=".ai/x.txt")
    result = run_scan(repo, "--staged")
    assert result.returncode == 1
    assert "blocked private path (.ai/)" in result.stdout


def test_sentinel_examples_marker_exempts_only_the_sentinel_check(tmp_path: Path) -> None:
    marker = "pii-scan: " + "sentinel-examples"
    sentinel = "BEGIN AI " + "TRANSCRIPT"
    repo = init_repo(tmp_path, "doc", f"{marker}\n{sentinel}\n")
    assert run_scan(repo, "--all").returncode == 0
    ssn = "212-34-" + "5678"
    (tmp_path / "b").mkdir()
    repo2 = init_repo(tmp_path / "b", "doc", f"{marker}\n{sentinel}\nSSN {ssn}\n")
    result = run_scan(repo2, "--all")
    assert result.returncode == 1 and "Social Security" in result.stdout
