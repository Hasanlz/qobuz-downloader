import qobuz_downloader
from qobuz_downloader.domain import Quality, Track, renumber
from qobuz_downloader.queue import InMemoryQueue


def test_version():
    assert qobuz_downloader.__version__ == "0.1.0"


def test_quality_ladder_is_ordered():
    assert Quality.LOSSY < Quality.CD < Quality.HIRES_96 < Quality.HIRES_192


def test_renumber_assigns_playlist_positions():
    tracks = [
        Track(id="t1", title="A", artist="X", album="Album One", track_number=4),
        Track(id="t2", title="B", artist="Y", album="Album Two", track_number=7),
    ]

    renumbered = renumber(tracks)

    assert [t.track_number for t in renumbered] == [1, 2]
    assert [t.album for t in renumbered] == ["Album One", "Album Two"]
    assert [t.id for t in renumbered] == ["t1", "t2"]


def test_in_memory_queue_dedupes_completed_tracks():
    queue = InMemoryQueue()
    track = Track(id="t1", title="Song", artist="A", album="B")
    first = queue.add([track])
    second = queue.add([track])
    queue.complete(track)
    third = queue.add([track])
    assert [t.id for t in first.added] == ["t1"]
    assert [t.id for t in second.added] == []
    assert [t.id for t in third.added] == []


def test_failed_track_is_requeued_on_add():
    queue = InMemoryQueue()
    track = Track(id="t2", title="Song", artist="A", album="B")
    queue.add([track])
    queue.fail(track, "stream expired")
    report = queue.add([track])
    assert [t.id for t in report.added] == ["t2"]
