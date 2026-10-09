import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from build import build_metadata


class BuildMetadataTest(unittest.TestCase):
    def test_release_tag_fallback_and_default(self) -> None:
        now = datetime(2026, 10, 7, 1, 17, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.git(root, "init", "-q", "-b", "main")
            self.git(root, "config", "user.name", "OctoPus test")
            self.git(root, "config", "user.email", "octopus@example.invalid")

            self.commit(root, "first")
            self.git(root, "tag", "v1.2.3-beta.1")
            version, build = build_metadata(root, now)
            self.assertEqual(version, "1.2.3-beta.1")
            self.assertEqual(build, self.git(root, "rev-parse", "--short", "HEAD"))

            self.git(root, "checkout", "-qb", "other")
            self.commit(root, "other branch")
            self.git(root, "tag", "v9.9.9")
            self.git(root, "checkout", "-q", "main")
            self.commit(root, "second")
            self.assertEqual(build_metadata(root, now)[0], "1.2.3-beta.1-97")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.git(root, "init", "-q", "-b", "main")
            self.git(root, "config", "user.name", "OctoPus test")
            self.git(root, "config", "user.email", "octopus@example.invalid")
            self.commit(root, "untagged")
            self.assertEqual(build_metadata(root, now)[0], "0.0.0-97")

    @staticmethod
    def git(root: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    @classmethod
    def commit(cls, root: Path, content: str) -> None:
        (root / "source.txt").write_text(content, encoding="utf-8")
        cls.git(root, "add", "source.txt")
        subprocess.run(["git", "commit", "-qm", content], cwd=root, check=True, env={
            **os.environ, "GIT_AUTHOR_DATE": "2026-10-03T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-10-03T00:00:00Z",
        })


if __name__ == "__main__":
    unittest.main()
