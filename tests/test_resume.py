import pytest

from qobuz_downloader.domain import Track
from qobuz_downloader.queue import InMemoryQueue, SqliteQueue


def make_track(track_id="t1"):
    return Track(
        id=track_id, title="Song", artist="Artist", album="Album", track_number=1
    )


@pytest.mark.parametrize("queue_factory", [InMemoryQueue, SqliteQueue])
def test_requeue_failed_resets_only_failed(queue_factory, tmp_path):
    path = tmp_path / "queue.sqlite3" if queue_factory is SqliteQueue else None
    queue = queue_factory(path) if path else queue_factory()
    done = make_track("done")
    failed = make_track("failed")
    waiting = make_track("waiting")
    queue.add([done, failed, waiting])
    queue.complete(done)
    queue.fail(failed, "connection reset")

    assert queue.requeue_failed() == 1
    pending_ids = [t.id for t in queue.pending()]
    assert sorted(pending_ids) == ["failed", "waiting"]
    queue.complete(failed)
    assert queue.pending() == [waiting]
    if hasattr(queue, "close"):
        queue.close()


@pytest.mark.parametrize("queue_factory", [InMemoryQueue, SqliteQueue])
def test_requeue_failed_with_nothing_failed(queue_factory, tmp_path):
    path = tmp_path / "queue.sqlite3" if queue_factory is SqliteQueue else None
    queue = queue_factory(path) if path else queue_factory()
    assert queue.requeue_failed() == 0
    if hasattr(queue, "close"):
        queue.close()
