import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from build import build_metadata


class BuildMetadataTest(unittest.TestCase):
    def test_manual_semver_and_product_commit_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.git(root, "init", "-q", "-b", "main")
            self.git(root, "config", "user.name", "OctoPus test")
            self.git(root, "config", "user.email", "octopus@example.invalid")
            (root / "VERSION").write_text("1.0.0-beta\n", encoding="utf-8")

            self.commit(root, "first")
            self.git(root, "tag", "v1.2.3-beta.1")
            version, build, sha = build_metadata(root)
            self.assertEqual(version, "1.0.0-beta")
            self.assertEqual(build, "1")
            self.assertEqual(sha, self.git(root, "rev-parse", "--short", "HEAD"))

            self.git(root, "checkout", "-qb", "octopus-dev")
            self.commit(root, "dev-only commit")
            self.git(root, "tag", "v9.9.9")
            self.git(root, "checkout", "-q", "main")
            self.assertEqual(build_metadata(root), ("1.0.0-beta", "1", sha))

            self.commit(root, "second")
            version, build, sha = build_metadata(root)
            self.assertEqual((version, build), ("1.0.0-beta", "2"))
            self.assertEqual(sha, self.git(root, "rev-parse", "--short", "HEAD"))

    @staticmethod
    def git(root: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    @classmethod
    def commit(cls, root: Path, content: str) -> None:
        (root / "source.txt").write_text(content, encoding="utf-8")
        cls.git(root, "add", "--all")
        subprocess.run(["git", "commit", "-qm", content], cwd=root, check=True, env={
            **os.environ, "GIT_AUTHOR_DATE": "2026-10-03T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-10-03T00:00:00Z",
        })


if __name__ == "__main__":
    unittest.main()
