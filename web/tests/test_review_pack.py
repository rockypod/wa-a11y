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
REVIEW_PACK = ROOT / "scripts" / "review-pack"


def sh(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run([*args], cwd=repo, check=True, env=env)


def test_review_pack_uses_only_the_requested_git_ref(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "scripts").mkdir()
    sh(repo, "git", "init", "-q")

    for name, body in {
        "scripts/verify-export": '#!/usr/bin/env bash\necho "verify-export: PASS $1"\n',
        "scripts/pii-scan": "#!/usr/bin/env bash\necho 'pii-scan: PASS'\n",
        "scripts/license-headers": (
            "#!/usr/bin/env bash\necho 'all source files carry the wa-a11y AGPLv3 header'\n"
        ),
    }.items():
        path = repo / name
        path.write_text(body)
        path.chmod(0o755)
    (repo / "README.md").write_text("committed review fixture\n")
    (repo / "working-tree-only.txt").write_text("must not enter the archive\n")
    (repo / "scripts/review-pack").write_bytes(REVIEW_PACK.read_bytes())
    (repo / "scripts/review-pack").chmod(0o755)
    sh(repo, "git", "add", "scripts", "README.md")
    sh(
        repo,
        "git",
        "-c",
        "user.name=Test",
        "-c",
        "user.email=review@example.com",
        "commit",
        "-qm",
        "fixture",
    )
    sh(repo, "git", "tag", "v-test")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gitleaks = fake_bin / "gitleaks"
    gitleaks.write_text("#!/usr/bin/env bash\necho 'gitleaks: PASS'\n")
    gitleaks.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(repo / "scripts/review-pack"), "v-test"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    pack = repo / "releases" / "review-v-test"
    assert "working-tree-only.txt" not in (pack / "MANIFEST.tsv").read_text()
    archive = pack / "source.tar"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert (pack / "ARCHIVE.sha256").read_text().startswith(digest)
    assert "v-test" in (pack / "VERIFY-EXPORT.txt").read_text()
    assert "pii-scan: PASS" in (pack / "PII-SCAN.txt").read_text()
    assert "gitleaks: PASS" in (pack / "GITLEAKS.txt").read_text()
    assert "review@example.com" not in (pack / "MANIFEST.tsv").read_text()
    signoff = (pack / "SIGNOFF.template.md").read_text()
    assert "Archive SHA-256:" in signoff
    assert "- Reviewer:" in signoff
