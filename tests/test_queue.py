from qobuz_downloader.domain import Track
from qobuz_downloader.queue import SqliteQueue


def make_track(track_id="t1"):
    return Track(
        id=track_id, title="Song", artist="Artist", album="Album", track_number=1
    )


def test_pending_and_complete_round_trip(tmp_path):
    queue = SqliteQueue(tmp_path / "queue.sqlite3")
    track = make_track()
    report = queue.add([track])
    assert [t.id for t in report.added] == ["t1"]
    assert queue.pending() == [track]
    queue.complete(track)
    assert queue.pending() == []
    queue.close()


def test_add_skips_pending_and_complete(tmp_path):
    queue = SqliteQueue(tmp_path / "queue.sqlite3")
    track = make_track()
    queue.add([track])
    assert [t.id for t in queue.add([track]).skipped] == ["t1"]
    queue.complete(track)
    assert [t.id for t in queue.add([track]).skipped] == ["t1"]
    queue.close()


def test_failed_track_is_requeued_on_add(tmp_path):
    queue = SqliteQueue(tmp_path / "queue.sqlite3")
    track = make_track()
    queue.add([track])
    queue.fail(track, "stream expired")
    report = queue.add([track])
    assert [t.id for t in report.added] == ["t1"]
    assert queue.pending() == [track]
    queue.close()


def test_queue_survives_across_instances(tmp_path):
    track = make_track()
    first = SqliteQueue(tmp_path / "queue.sqlite3")
    first.add([track])
    first.close()
    second = SqliteQueue(tmp_path / "queue.sqlite3")
    assert second.pending() == [track]
    second.complete(track)
    second.close()
    third = SqliteQueue(tmp_path / "queue.sqlite3")
    assert third.pending() == []
    third.close()


def test_collection_survives_round_trip(tmp_path):
    queue = SqliteQueue(tmp_path / "queue.sqlite3")
    track = Track(
        id="t1", title="Song", artist="Artist", album="Album", collection="Roadtrip Mix"
    )
    queue.add([track])
    assert queue.pending() == [track]
    queue.close()


def test_old_database_without_collection_column_migrates(tmp_path):
    import sqlite3

    path = tmp_path / "queue.sqlite3"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE tracks ("
        "id TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL,"
        " album TEXT NOT NULL, track_number INTEGER, duration_seconds INTEGER,"
        " status TEXT NOT NULL, reason TEXT)"
    )
    db.execute(
        "INSERT INTO tracks VALUES ('t1', 'Song', 'Artist', 'Album', 1, 180, 'PENDING', NULL)"
    )
    db.commit()
    db.close()

    queue = SqliteQueue(path)

    assert [t.id for t in queue.pending()] == ["t1"]
    track = make_track()
    track = Track(
        id="t2", title="S2", artist="A2", album="B2", collection="Playlist X"
    )
    queue.add([track])
    assert queue.pending()[1].collection == "Playlist X"
    queue.close()
