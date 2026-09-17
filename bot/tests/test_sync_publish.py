"""Whether a sync published, and -- when it did not -- why.

The dashboard reads Firestore. A sync that writes the local snapshot and skips
Firestore therefore changes nothing anyone can see, which is fine when there is
no Firebase project and a fault when there is one. Both used to print the same
sentence, in the middle of a block of output that otherwise reads like success,
and exit 0. These tests hold the two apart.
"""

import builtins

import pytest

from edgelord import config, db, sync


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(sync, "SNAPSHOT_DIR", tmp_path / "snapshot")
    db.init()
    with db.session() as c:
        yield c


class TestCredentialReasons:
    def test_unset_is_the_development_mode_reason(self, monkeypatch):
        monkeypatch.delenv("FIREBASE_CREDENTIALS", raising=False)
        path, reason = sync._credentials()
        assert path is None
        assert reason == sync.UNSET

    def test_blank_is_not_configuration(self, monkeypatch):
        monkeypatch.setenv("FIREBASE_CREDENTIALS", "   ")
        assert sync._credentials() == (None, sync.UNSET)

    def test_a_path_that_does_not_exist_names_itself(self, monkeypatch, tmp_path):
        missing = tmp_path / "serviceAccount.json"
        monkeypatch.setenv("FIREBASE_CREDENTIALS", str(missing))
        path, reason = sync._credentials()
        assert path is None
        # The whole point: not the same reason as having no project at all.
        assert reason != sync.UNSET
        assert str(missing) in reason

    def test_a_quoted_path_still_resolves(self, monkeypatch, tmp_path):
        """Copied out of Windows Explorer, a path arrives wrapped in quotes."""
        key = tmp_path / "serviceAccount.json"
        key.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("FIREBASE_CREDENTIALS", f'"{key}"')
        assert sync._credentials() == (key, None)

    def test_a_relative_path_resolves_against_the_bot_root(self, monkeypatch):
        key = config.ROOT / "serviceAccount.json"
        key.write_text("{}", encoding="utf-8")
        try:
            monkeypatch.setenv("FIREBASE_CREDENTIALS", "serviceAccount.json")
            assert sync._credentials() == (key, None)
        finally:
            key.unlink()


class TestMissingPackage:
    def test_an_absent_firebase_admin_is_not_a_credential_problem(
        self, monkeypatch, tmp_path
    ):
        key = tmp_path / "serviceAccount.json"
        key.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("FIREBASE_CREDENTIALS", str(key))

        real_import = builtins.__import__

        def no_firebase(name, *a, **kw):
            if name.startswith("firebase_admin"):
                raise ImportError("No module named 'firebase_admin'")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", no_firebase)

        client, reason = sync._client()
        assert client is None
        assert "firebase-admin" in reason and "pip install" in reason
        assert reason != sync.UNSET


class TestPushReporting:
    def test_no_project_reports_unpublished_and_unconfigured(self, conn, monkeypatch):
        monkeypatch.delenv("FIREBASE_CREDENTIALS", raising=False)
        out = sync.push(conn, 2026)
        assert out["published"] is False
        # Nothing was misconfigured -- there is no project to talk to.
        assert out["configured"] is False
        assert out["firestore"] == sync.UNSET

    def test_a_broken_key_path_reports_configured_but_unpublished(
        self, conn, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("FIREBASE_CREDENTIALS", str(tmp_path / "gone.json"))
        out = sync.push(conn, 2026)
        assert out["published"] is False
        assert out["configured"] is True

    def test_the_snapshot_is_still_written_when_publishing_fails(
        self, conn, monkeypatch, tmp_path
    ):
        """Losing the mirror must not also lose the local fallback."""
        monkeypatch.setenv("FIREBASE_CREDENTIALS", str(tmp_path / "gone.json"))
        out = sync.push(conn, 2026)
        assert out["snapshot"] is not None
        assert (sync.SNAPSHOT_DIR / "season-2026.json").exists()


class TestExitCode:
    """`sync` is called by the scheduled jobs, which log a non-zero exit."""

    def _run(self, monkeypatch, tmp_path):
        from edgelord import cli

        monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(sync, "SNAPSHOT_DIR", tmp_path / "snapshot")
        return cli.main(["sync", "--season", "2026"])

    def test_development_mode_is_not_an_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FIREBASE_CREDENTIALS", raising=False)
        assert self._run(monkeypatch, tmp_path) == 0

    def test_meaning_to_publish_and_failing_is_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FIREBASE_CREDENTIALS", str(tmp_path / "gone.json"))
        assert self._run(monkeypatch, tmp_path) == 2
