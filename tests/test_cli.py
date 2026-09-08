import sqlite3
from pathlib import Path

from qobuz_downloader import cli
from qobuz_downloader.domain import Complete, Playlist, Quality, Track
from qobuz_downloader.qobuz import Qobuz


class FakeQobuz(Qobuz):
    tracks_returned: list[Track] = []

    @classmethod
    def from_token(cls, app_id: str, app_secret: str, token: str) -> "FakeQobuz":
        return cls()

    def item(self, url):
        return Playlist(id="p1", title="Mix")

    def tracks(self, item):
        return list(self.tracks_returned)

    def qualities(self, track):
        raise NotImplementedError

    def stream(self, track, quality):
        raise NotImplementedError

    def search_tracks(self, query, limit):
        raise NotImplementedError

    def search_albums(self, query, limit):
        raise NotImplementedError


class FakeEngine:
    def __init__(self, *args, **kwargs):
        self.downloaded: list[str] = []

    def download(self, track, preferred):
        self.downloaded.append(track.id)
        return Complete(path=Path("/nowhere"), quality=Quality.CD, fell_back=False)


def make_tracks(count):
    return [
        Track(
            id=f"t{i}",
            title=f"Song {i}",
            artist="Artist",
            album="Album",
            track_number=i,
            collection="Mix",
        )
        for i in range(1, count + 1)
    ]


def test_limit_queues_everything_but_downloads_only_limit(tmp_path, monkeypatch, capsys):
    FakeQobuz.tracks_returned = make_tracks(5)
    engine = FakeEngine()
    monkeypatch.setenv("QOBUZ_USER_AUTH_TOKEN", "token")
    monkeypatch.setenv("QOBUZ_APP_ID", "app-id")
    monkeypatch.setenv("QOBUZ_APP_SECRET", "secret")
    monkeypatch.setattr(cli, "LiveQobuz", FakeQobuz)
    monkeypatch.setattr(cli, "Engine", lambda *a, **k: engine)

    exit_code = cli.main(
        [
            "https://play.qobuz.com/playlist/77",
            "--dir",
            str(tmp_path),
            "--db",
            str(tmp_path / "q.sqlite3"),
            "--no-lyrics",
            "--limit",
            "2",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "queued 5 track(s)" in captured.out
    assert "downloading 2 track(s) at hires (3 more queued)" in captured.out
    assert engine.downloaded == ["t1", "t2"]

    rows = dict(
        sqlite3.connect(tmp_path / "q.sqlite3").execute("SELECT id, status FROM tracks")
    )
    assert len(rows) == 5
    assert [key for key, status in rows.items() if status == "COMPLETE"] == ["t1", "t2"]
    assert [key for key, status in rows.items() if status == "PENDING"] == [
        "t3",
        "t4",
        "t5",
    ]


def test_without_limit_downloads_everything_queued(tmp_path, monkeypatch, capsys):
    FakeQobuz.tracks_returned = make_tracks(3)
    engine = FakeEngine()
    monkeypatch.setenv("QOBUZ_USER_AUTH_TOKEN", "token")
    monkeypatch.setenv("QOBUZ_APP_ID", "app-id")
    monkeypatch.setenv("QOBUZ_APP_SECRET", "secret")
    monkeypatch.setattr(cli, "LiveQobuz", FakeQobuz)
    monkeypatch.setattr(cli, "Engine", lambda *a, **k: engine)

    exit_code = cli.main(
        [
            "https://play.qobuz.com/playlist/77",
            "--dir",
            str(tmp_path),
            "--db",
            str(tmp_path / "q.sqlite3"),
            "--no-lyrics",
        ]
    )

    assert exit_code == 0
    assert engine.downloaded == ["t1", "t2", "t3"]
    assert "downloading 3 track(s) at hires" in capsys.readouterr().out


def test_rerun_with_limit_continues_where_the_last_run_stopped(
    tmp_path, monkeypatch, capsys
):
    FakeQobuz.tracks_returned = make_tracks(4)
    engine = FakeEngine()
    monkeypatch.setenv("QOBUZ_USER_AUTH_TOKEN", "token")
    monkeypatch.setenv("QOBUZ_APP_ID", "app-id")
    monkeypatch.setenv("QOBUZ_APP_SECRET", "secret")
    monkeypatch.setattr(cli, "LiveQobuz", FakeQobuz)
    monkeypatch.setattr(cli, "Engine", lambda *a, **k: engine)

    base = [
        "https://play.qobuz.com/playlist/77",
        "--dir",
        str(tmp_path),
        "--db",
        str(tmp_path / "q.sqlite3"),
        "--no-lyrics",
    ]

    assert cli.main([*base, "--limit", "2"]) == 0
    assert engine.downloaded == ["t1", "t2"]

    assert cli.main([*base, "--limit", "2"]) == 0
    assert engine.downloaded == ["t1", "t2", "t3", "t4"]
