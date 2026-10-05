# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release-github"


def run(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts" / "release-github"), *args],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "scripts").mkdir()
    (repo / ".gitignore").write_text("releases/\n")
    (repo / ".gitattributes").write_text("private/ export-ignore\n")
    (repo / "README.md").write_text("synthetic release fixture\n")
    (repo / "private").mkdir()
    (repo / "private" / "excluded.txt").write_text("not in the public tree\n")
    for name, body in {
        "check": "#!/usr/bin/env bash\necho 'check: PASS'\n",
        "verify-export": '#!/usr/bin/env bash\necho "verify-export: PASS $1"\n',
    }.items():
        path = repo / "scripts" / name
        path.write_text(body)
        path.chmod(0o755)
    (repo / "scripts" / "release-github").write_bytes(RELEASE.read_bytes())
    (repo / "scripts" / "release-github").chmod(0o755)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=release@example.com",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=release@example.com",
            "tag",
            "-a",
            "v-test",
            "-m",
            "v-test",
        ],
        cwd=repo,
        check=True,
    )
    return repo


def add_review_signoff(
    repo: Path,
    *,
    sha: str,
    reviewer: str = "Owner",
    date: str = "2026-10-04",
    tag: str = "v-test",
) -> None:
    review = repo / "releases" / "review-v-test"
    review.mkdir(parents=True, exist_ok=True)
    archive = review / "source.tar"
    with archive.open("wb") as output:
        subprocess.run(
            ["git", "archive", "--format=tar", "v-test"], cwd=repo, stdout=output, check=True
        )
    (review / "SIGNOFF.md").write_text(
        f"# Sign-off\n\n- Reviewer: {reviewer}\n- Date (YYYY-MM-DD): {date}\n"
        f"- Tag/ref: {tag}\n- Archive SHA-256: {sha}\n"
    )


def fake_gitleaks(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tool = bin_dir / "gitleaks"
    tool.write_text("#!/usr/bin/env bash\necho 'gitleaks: PASS'\n")
    tool.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def archive_sha(repo: Path) -> str:
    archive = repo / "releases" / "review-v-test" / "source.tar"
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def test_release_refuses_without_signoff(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    result = run(repo, "v-test")
    assert result.returncode == 1
    assert "sign-off" in result.stderr


def test_release_refuses_sha_mismatch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    add_review_signoff(repo, sha="0" * 64)
    result = run(repo, "v-test")
    assert result.returncode == 1
    assert "SHA-256" in result.stderr


def test_release_refuses_unfilled_signoff_template(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    add_review_signoff(repo, sha="0" * 64, reviewer="", date="", tag="")
    result = run(repo, "v-test")
    assert result.returncode == 1
    assert "reviewer" in result.stderr


def test_dry_run_builds_only_the_signed_git_archive(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    review = repo / "releases" / "review-v-test"
    review.mkdir(parents=True)
    archive = review / "source.tar"
    with archive.open("wb") as output:
        subprocess.run(
            ["git", "archive", "--format=tar", "v-test"], cwd=repo, stdout=output, check=True
        )
    add_review_signoff(repo, sha=archive_sha(repo))
    result = run(repo, "--dry-run", "v-test", env=fake_gitleaks(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dry-run complete; nothing was published" in result.stdout

    release_repo = repo / "releases" / "github-v-test" / "repo"
    files = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=release_repo, text=True
    )
    assert "private/excluded.txt" not in files
    assert "README.md" in files
    assert "release: wa-a11y v-test" in subprocess.check_output(
        ["git", "log", "-1", "--format=%s"], cwd=release_repo, text=True
    )


def sign(repo: Path, tag: str) -> None:
    review = repo / "releases" / f"review-{tag}"
    review.mkdir(parents=True, exist_ok=True)
    archive = review / "source.tar"
    with archive.open("wb") as output:
        subprocess.run(["git", "archive", "--format=tar", tag], cwd=repo, stdout=output, check=True)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    (review / "SIGNOFF.md").write_text(
        f"# Sign-off\n\n- Reviewer: Owner\n- Date (YYYY-MM-DD): 2026-10-04\n"
        f"- Tag/ref: {tag}\n- Archive SHA-256: {sha}\n"
    )


def publish(repo: Path, remote: Path, tag: str, env: dict[str, str]):
    # A pseudo-terminal answers the interactive y/N confirmation.
    cmd = f"{repo}/scripts/release-github --publish {tag}"
    return subprocess.run(
        ["script", "-qec", cmd, "/dev/null"],
        cwd=repo,
        input="y\n",
        text=True,
        capture_output=True,
        env={**env, "WA_A11Y_GITHUB_REMOTE": str(remote)},
        check=False,
    )


def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "public.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    return remote


def remote_log(remote: Path) -> list[str]:
    out = subprocess.check_output(["git", "--git-dir", str(remote), "log", "--format=%s", "main"])
    return out.decode().splitlines()


def test_publish_first_release_then_fast_forwards_the_next(tmp_path: Path) -> None:
    repo, remote, env = make_repo(tmp_path), bare_remote(tmp_path), fake_gitleaks(tmp_path)
    sign(repo, "v-test")
    first = publish(repo, remote, "v-test", env)
    assert first.returncode == 0, first.stdout + first.stderr
    (repo / "README.md").write_text("second release\n")
    git(repo, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-qam", "next")
    git(
        repo,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@example.com",
        "tag",
        "-a",
        "v-two",
        "-m",
        "two",
    )
    sign(repo, "v-two")
    second = publish(repo, remote, "v-two", env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert remote_log(remote) == [
        "release: wa-a11y v-two [AGPLv3 Corresponding Source]",
        "release: wa-a11y v-test [AGPLv3 Corresponding Source]",
    ]


def test_publish_refuses_foreign_main_and_pushes_nothing(tmp_path: Path) -> None:
    repo, remote, env = make_repo(tmp_path), bare_remote(tmp_path), fake_gitleaks(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "--initial-branch=main")
    (other / "README.md").write_text("created on the website\n")
    git(other, "add", ".")
    git(other, "-c", "user.name=Someone", "-c", "user.email=s@example.com", "commit", "-qm", "init")
    git(other, "push", "-q", str(remote), "main")
    sign(repo, "v-test")
    result = publish(repo, remote, "v-test", env)
    assert result.returncode == 1 and "not made by this script" in result.stdout + result.stderr
    tags = subprocess.check_output(["git", "--git-dir", str(remote), "tag"]).decode()
    assert tags == ""


def test_publish_refuses_an_existing_remote_tag(tmp_path: Path) -> None:
    repo, remote, env = make_repo(tmp_path), bare_remote(tmp_path), fake_gitleaks(tmp_path)
    sign(repo, "v-test")
    assert publish(repo, remote, "v-test", env).returncode == 0
    (repo / "releases" / "github-v-test").rename(tmp_path / "old-build")
    again = publish(repo, remote, "v-test", env)
    assert again.returncode == 1 and "already exists" in again.stdout + again.stderr
