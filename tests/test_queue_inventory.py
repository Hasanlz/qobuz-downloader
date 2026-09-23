import sqlite3

import pytest

from scripts.queue_inventory import _read_queue, build_report


def test_inventory_reports_missing_positions_and_replacement_rows():
    spotify = [
        {"id": "a", "name": "A", "artists": [{"name": "Artist A"}]},
        {"id": "b", "name": "B", "artists": [{"name": "Artist B"}]},
        {"id": "c", "name": "C", "artists": [{"name": "Artist C"}]},
    ]
    queue = [
        {
            "id": "a",
            "track_number": 1,
            "status": "PENDING",
            "title": "A",
            "artist": "Artist A",
            "track_total": 3,
        },
        {
            "id": "old-b",
            "track_number": 1,
            "status": "PENDING",
            "title": "B",
            "artist": "Artist B",
            "track_total": 3,
        },
        {
            "id": "c",
            "track_number": 3,
            "status": "PENDING",
            "title": "C",
            "artist": "Artist C",
            "track_total": 3,
        },
    ]

    report = build_report(spotify, queue)

    assert report["covered_positions"] == 2
    assert report["missing_positions"] == [2]
    assert report["duplicate_positions"][0]["position"] == 1
    assert report["gaps"][0]["title"] == "B"


def test_inventory_read_only_does_not_create_a_missing_database(tmp_path):
    path = tmp_path / "missing.sqlite3"

    with pytest.raises(sqlite3.OperationalError):
        _read_queue(path, track_total=None)

    assert not path.exists()
