import pytest

from qobuz_downloader.domain import Complete, Failed, Quality, Stream, Track
from qobuz_downloader.engine import Engine
from qobuz_downloader.match._catalog import Catalog, stamped
from qobuz_downloader.naming import Naming
from qobuz_downloader.source import Source, parse, qualify

SPOTIFY = Track(
    id="spotify:s1",
    title="خاکستر",
    artist="Hamed Mohammadi",
    album="خاکستر",
    duration_seconds=284,
)


class FakeSource(Source):
    def __init__(self, name, candidates, ladder=(Quality.LOSSY, Quality.CD)):
        self.name = name
        self._candidates = list(candidates)
        self._ladder = list(ladder)
        self.stream_calls: list[tuple[str, Quality]] = []
        self.cover_calls: list[str] = []

    def search_tracks(self, query, limit):
        return list(self._candidates)

    def qualities(self, track):
        return list(self._ladder)

    def stream(self, track, quality):
        _, native = parse(track.id)
        self.stream_calls.append((native, quality))
        return Stream(url=f"https://{self.name}.test/{native}", quality=quality)

    def cover_url(self, track):
        _, native = parse(track.id)
        self.cover_calls.append(native)
        return f"https://{self.name}.test/cover/{native}"


def tidal_candidate():
    return Track(
        id="233554206",
        title="خاکستر",
        artist="Hamed Mohammadi",
        album="خاکستر",
        duration_seconds=284,
    )


# -- id parsing ---------------------------------------------------------


def test_bare_ids_are_qobuz():
    assert parse("12345") == ("qobuz", "12345")


def test_prefixed_ids_parse():
    assert parse("tidal:233554206") == ("tidal", "233554206")
    assert parse("deezer:9") == ("deezer", "9")


def test_qualify_round_trips():
    for source, native in [("qobuz", "5"), ("tidal", "5"), ("deezer", "5")]:
        assert parse(qualify(source, native)) == (source, native)


def test_qualify_keeps_qobuz_bare():
    assert qualify("qobuz", "5") == "5"


def test_stamped_qualifies_non_qobuz():
    stamped_track = stamped(tidal_candidate(), "tidal")
    assert stamped_track.id == "tidal:233554206"


# -- catalog resolution -------------------------------------------------


def qobuz_strategy(track):
    # the matcher's qobuz route: this catalog's qobuz entry is driven
    # through LiveSpotify._best_on_qobuz in production
    return None, 0.0


def test_fallback_rescues_qobuz_missing_track():
    catalog = Catalog(
        [FakeSource("qobuz", []), FakeSource("tidal", [tidal_candidate()])]
    )
    resolved = catalog.resolve(SPOTIFY, qobuz_strategy)
    assert resolved is not None
    assert resolved.id == "tidal:233554206"


def test_first_source_wins_when_it_carries_the_track():
    qobuz_candidate = Track(
        id="77",
        title="خاکستر",
        artist="Hamed Mohammadi",
        album="خاکستر",
        duration_seconds=284,
    )

    def carrying_qobuz(track):
        return qobuz_candidate, 0.95

    catalog = Catalog(
        [
            FakeSource("qobuz", []),
            FakeSource("tidal", [tidal_candidate()]),
        ]
    )
    resolved = catalog.resolve(SPOTIFY, carrying_qobuz)
    assert resolved.id == "77"  # bare: qobuz convention


def test_resolve_best_picks_highest_quality():
    cd_only = FakeSource("qobuz", [Track(id="1", title="خاکستر", artist="Hamed Mohammadi", album="A", duration_seconds=284)])
    hires = FakeSource(
        "tidal",
        [tidal_candidate()],
        ladder=(Quality.LOSSY, Quality.CD, Quality.HIRES_96, Quality.HIRES_192),
    )
    catalog = Catalog([cd_only, hires])
    resolved = catalog.resolve_best(SPOTIFY, qobuz_strategy)
    assert resolved.id == "tidal:233554206"


def test_resolve_best_breaks_quality_tie_on_score():
    bad_title = Track(id="2", title="Totally Different", artist="Hamed Mohammadi", album="A", duration_seconds=284)
    good_title = tidal_candidate()
    qobuz = FakeSource("qobuz", [bad_title])
    tidal = FakeSource("tidal", [good_title])
    catalog = Catalog([qobuz, tidal])
    resolved = catalog.resolve_best(SPOTIFY, qobuz_strategy)
    # equal quality ladders -> higher match score (the real title) wins
    assert resolved.id == "tidal:233554206"


def test_lossy_only_source_skipped_without_allow_lossy():
    lossy = FakeSource("tidal", [tidal_candidate()], ladder=[Quality.LOSSY])
    catalog = Catalog([FakeSource("qobuz", []), lossy])
    assert catalog.resolve(SPOTIFY, qobuz_strategy) is None


def test_lossy_only_source_used_with_allow_lossy():
    lossy = FakeSource("tidal", [tidal_candidate()], ladder=[Quality.LOSSY])
    catalog = Catalog(
        [FakeSource("qobuz", []), lossy], allow_lossy=True
    )
    resolved = catalog.resolve(SPOTIFY, qobuz_strategy)
    assert resolved is not None


def test_qobuz_strategy_is_used_for_qobuz_entry():
    calls = []

    def strategy(track):
        calls.append(track)
        candidate = Track(
            id="55",
            title="خاکستر",
            artist="Hamed Mohammadi",
            album="A",
            duration_seconds=284,
        )
        return candidate, 0.9

    catalog = Catalog([FakeSource("qobuz", [])])
    resolved = catalog.resolve(SPOTIFY, strategy)
    assert resolved.id == "55"
    assert calls == [SPOTIFY]


class FailingSource(Source):
    """A source whose search backend is degraded (every call 400s)."""

    def __init__(self, name):
        self.name = name

    def search_tracks(self, query, limit):
        raise RuntimeError(f"{self.name} search failed after 3 attempts: Algolia down")

    def qualities(self, track):
        raise RuntimeError(f"{self.name} unavailable")

    def stream(self, track, quality):
        raise NotImplementedError

    def cover_url(self, track):
        return None


def test_failing_source_falls_through_to_next():
    """A Tidal blip must not hide a track the next source carries."""
    catalog = Catalog(
        [
            FakeSource("qobuz", []),
            FailingSource("tidal"),
            FakeSource("deezer", [tidal_candidate()]),
        ]
    )

    resolved = catalog.resolve(SPOTIFY, lambda track: (None, 0.0))

    assert resolved is not None
    assert resolved.id == "deezer:233554206"


def test_failing_qobuz_strategy_falls_through_to_next():
    """A Qobuz backend outage fails through to a source that has it."""
    catalog = Catalog([FakeSource("qobuz", []), FakeSource("tidal", [tidal_candidate()])])

    def broken_strategy(track):
        raise RuntimeError("qobuz search failed after 3 attempts: Algolia down")

    resolved = catalog.resolve(SPOTIFY, broken_strategy)

    assert resolved is not None
    assert resolved.id == "tidal:233554206"


def test_all_sources_failing_raises_retryable_not_clean_miss():
    """If every source errored, the miss is not trustworthy."""
    catalog = Catalog([FakeSource("qobuz", []), FailingSource("tidal")])

    def broken_strategy(track):
        raise RuntimeError("qobuz search failed after 3 attempts: Algolia down")

    with pytest.raises(RuntimeError, match="Algolia down"):
        catalog.resolve(SPOTIFY, broken_strategy)


def test_resolve_best_failing_source_still_uses_other():
    catalog = Catalog([FailingSource("tidal"), FakeSource("deezer", [tidal_candidate()])])

    resolved = catalog.resolve_best(SPOTIFY, lambda track: (None, 0.0))

    assert resolved is not None
    assert resolved.id == "deezer:233554206"


def test_resolve_best_all_failing_raises():
    catalog = Catalog([FailingSource("tidal"), FailingSource("deezer")])

    with pytest.raises(RuntimeError, match="Algolia down"):
        catalog.resolve_best(SPOTIFY, lambda track: (None, 0.0))


# -- engine dispatch ----------------------------------------------------


def _flac_bytes() -> bytes:
    import struct

    header = b"fLaC" + bytes([0x80, 0x00, 0x00, 0x22])
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    packed = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    streaminfo += packed.to_bytes(8, "big") + b"\x00" * 16
    return header + streaminfo + b"\x00" * 64


class FakeByteSource:
    def __init__(self, content):
        self.content = content

    def stream(self, url, start):
        from qobuz_downloader.engine._source import ByteResponse

        return ByteResponse(
            status=200,
            length=len(self.content),
            chunks=[self.content],
        )


def test_engine_dispatches_by_id_prefix(tmp_path):
    tidal = FakeSource("tidal", [tidal_candidate()])

    class FakeQobuz:
        def qualities(self, track):
            return [Quality.LOSSY, Quality.CD]

        def stream(self, track, quality):
            raise AssertionError("must not be called for a tidal track")

        def cover_url(self, track):
            raise AssertionError("must not be called for a tidal track")

    from qobuz_downloader.source import QobuzSource

    engine = Engine(
        FakeQobuz(),
        Naming("", "{title}", root=tmp_path),
        source=FakeByteSource(_flac_bytes()),
        retry_delays=(),
        sources={"qobuz": QobuzSource(FakeQobuz()), "tidal": tidal},
    )
    track = Track(
        id="tidal:233554206",
        title="خاکستر",
        artist="Hamed Mohammadi",
        album="A",
    )
    outcome = engine.download(track, Quality.CD)
    assert not isinstance(outcome, Failed), outcome.reason
    assert tidal.stream_calls == [("233554206", Quality.CD)]


def test_engine_unknown_source_fails_cleanly(tmp_path):
    class NullSource:
        pass

    engine = Engine(
        NullSource(),
        Naming("", "{title}", root=tmp_path),
        sources={},
    )
    track = Track(id="deezer:9", title="X", artist="Y", album="Z")
    outcome = engine.download(track, Quality.CD)
    assert isinstance(outcome, Failed)
    assert "deezer" in outcome.reason
