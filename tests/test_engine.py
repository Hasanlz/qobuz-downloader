import struct

from qobuz_downloader.domain import Complete, Failed, Quality, Stream, Track
from qobuz_downloader.engine import Engine
from qobuz_downloader.engine._source import ByteResponse, ByteSource
from qobuz_downloader.lyrics import LyricsSource
from qobuz_downloader.naming import Naming
from qobuz_downloader.qobuz import Qobuz
from qobuz_downloader.tidal import Tidal

TRACK = Track(id="t1", title="Song", artist="Artist", album="Album", track_number=1)


def _flac_bytes(size: int = 0, sample_rate: int = 44100, bit_depth: int = 16) -> bytes:
    header = b"fLaC" + bytes([0x80, 0x00, 0x00, 0x22])
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    packed = (sample_rate << 44) | (1 << 41) | ((bit_depth - 1) << 36) | sample_rate
    streaminfo += packed.to_bytes(8, "big") + b"\x00" * 16
    data = header + streaminfo
    return data + b"\x00" * max(0, size - len(data))


class FakeQobuz(Qobuz):
    def __init__(self, qualities, delivered=(16, 44.1)):
        self._qualities = list(qualities)
        self._delivered = delivered
        self.stream_calls = 0

    def item(self, url):
        raise NotImplementedError

    def tracks(self, item):
        raise NotImplementedError

    def search_tracks(self, query, limit):
        return []

    def search_albums(self, query, limit):
        return []

    def qualities(self, track):
        return list(self._qualities)

    def stream(self, track, quality):
        self.stream_calls += 1
        return Stream(
            url=f"https://cdn.test/{track.id}/{self.stream_calls}",
            quality=quality,
            sampling_rate=self._delivered[1],
            bit_depth=self._delivered[0],
        )


class FakeByteSource(ByteSource):
    def __init__(self, content, fail_after=None, ignore_range=False):
        self.content = content
        self.fail_after = fail_after
        self.ignore_range = ignore_range
        self.calls = []
        self._failed = False

    def stream(self, url, start):
        self.calls.append(start)
        if self.fail_after is not None and not self._failed:
            self._failed = True
            prefix = self.content[start : start + self.fail_after]
            return ByteResponse(
                status=200,
                length=len(self.content),
                chunks=self._raise_after(prefix),
            )
        if start and self.ignore_range:
            return ByteResponse(
                status=200, length=len(self.content), chunks=iter([self.content])
            )
        if start:
            return ByteResponse(
                status=206,
                length=len(self.content) - start,
                chunks=iter([self.content[start:]]),
            )
        return ByteResponse(
            status=200, length=len(self.content), chunks=iter([self.content])
        )

    def _raise_after(self, prefix):
        yield prefix
        raise ConnectionError("connection reset")


class RoutingSource(FakeByteSource):
    """Serves different content for the tidal stream url."""

    def __init__(self, qobuz_content, tidal_content):
        super().__init__(qobuz_content)
        self.tidal_content = tidal_content

    def stream(self, url, start):
        if url.startswith("https://tidal.test"):
            self.calls.append(start)
            return ByteResponse(
                status=200,
                length=len(self.tidal_content),
                chunks=iter([self.tidal_content]),
            )
        return super().stream(url, start)


class FakeTidal(Tidal):
    def __init__(self, match="9", stream_error=None):
        self.match = match
        self.stream_error = stream_error
        self.logins = 0
        self.lookups: list[str] = []
        self.stream_calls: list[str] = []

    def hires_match_for(self, track):
        self.lookups.append(track.id)
        return self.match

    def ensure_login(self):
        self.logins += 1

    def stream(self, tidal_track_id):
        self.stream_calls.append(tidal_track_id)
        if self.stream_error is not None:
            raise self.stream_error
        return Stream(
            url=f"https://tidal.test/{tidal_track_id}",
            quality=Quality.HIRES_192,
        )


class FakeLyrics(LyricsSource):
    def __init__(self, text=None):
        self.text = text
        self.asked = []

    def lrc(self, track):
        self.asked.append(track.id)
        return self.text


def make_engine(qobuz, source, tmp_path, retry_delays=(), lyrics=None, tidal=None):
    naming = Naming("{artist}", "{tracknumber} - {title}", root=tmp_path)
    engine = Engine(
        qobuz, naming, source=source, retry_delays=retry_delays, lyrics=lyrics, tidal=tidal
    )
    return engine, tmp_path


def test_happy_path_downloads_and_renames(tmp_path):
    qobuz = FakeQobuz([Quality.LOSSY, Quality.CD, Quality.HIRES_96, Quality.HIRES_192])
    content = _flac_bytes(2048)
    source = FakeByteSource(content)
    engine, target = make_engine(qobuz, source, tmp_path)

    outcome = engine.download(TRACK, Quality.HIRES_192)

    assert isinstance(outcome, Complete)
    assert outcome.quality == Quality.HIRES_192
    assert not outcome.fell_back
    final = target / "Artist/01 - Song.flac"
    assert final.read_bytes() == content
    assert not final.with_suffix(".flac.part").exists()
    assert source.calls == [0]
    assert qobuz.stream_calls == 1


def test_falls_back_to_best_available_rung(tmp_path):
    qobuz = FakeQobuz([Quality.LOSSY, Quality.CD])
    source = FakeByteSource(_flac_bytes(512))
    engine, _ = make_engine(qobuz, source, tmp_path)

    outcome = engine.download(TRACK, Quality.HIRES_96)

    assert isinstance(outcome, Complete)
    assert outcome.quality == Quality.CD
    assert outcome.fell_back


def test_only_lossy_available_fails(tmp_path):
    qobuz = FakeQobuz([Quality.LOSSY])
    source = FakeByteSource(_flac_bytes(512))
    engine, _ = make_engine(qobuz, source, tmp_path)

    outcome = engine.download(TRACK, Quality.HIRES_192)

    assert isinstance(outcome, Failed)
    assert "lossy" in outcome.reason


def test_resumes_from_partial_after_mid_stream_failure(tmp_path):
    content = _flac_bytes(1024)
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(content, fail_after=10)
    engine, target = make_engine(qobuz, source, tmp_path, retry_delays=(0.0,))

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert source.calls == [0, 10]
    assert qobuz.stream_calls == 2
    final = target / "Artist/01 - Song.flac"
    assert final.read_bytes() == content
    assert not final.with_suffix(".flac.part").exists()


def test_restarts_when_server_ignores_range(tmp_path):
    content = _flac_bytes(1024)
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(content, fail_after=5, ignore_range=True)
    engine, target = make_engine(qobuz, source, tmp_path, retry_delays=(0.0,))

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert source.calls == [0, 5, 0]
    assert (target / "Artist/01 - Song.flac").read_bytes() == content


def test_corrupt_file_exhausts_retries_and_cleans_up(tmp_path):
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(b"garbage" * 100)
    engine, target = make_engine(qobuz, source, tmp_path, retry_delays=(0.0, 0.0))

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Failed)
    assert "corrupt" in outcome.reason
    assert source.calls == [0, 0, 0]
    assert not (target / "Artist/01 - Song.flac").exists()
    assert not (target / "Artist/01 - Song.flac.part").exists()


def test_partial_remains_for_next_run_on_final_network_failure(tmp_path):
    content = _flac_bytes(1024)
    qobuz = FakeQobuz([Quality.CD])

    class AlwaysBreaks(FakeByteSource):
        def stream(self, url, start):
            self.calls.append(start)
            prefix = self.content[start : start + 7]
            return ByteResponse(
                status=200, length=len(self.content), chunks=self._raise_after(prefix)
            )

    source = AlwaysBreaks(content)
    engine, target = make_engine(qobuz, source, tmp_path, retry_delays=(0.0,))

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Failed)
    assert (target / "Artist/01 - Song.flac.part").exists()


def test_lyrics_sidecar_saved_next_to_flac(tmp_path):
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(_flac_bytes(512))
    lyrics = FakeLyrics("[00:01.24] They tried to make me go to rehab")
    engine, target = make_engine(qobuz, source, tmp_path, lyrics=lyrics)

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert outcome.lyrics_saved
    sidecar = target / "Artist/01 - Song.lrc"
    assert sidecar.read_text(encoding="utf-8").startswith("[00:01.24]")
    assert lyrics.asked == ["t1"]


def test_lyrics_failure_never_blocks_download(tmp_path):
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(_flac_bytes(512))

    class ExplodingLyrics(FakeLyrics):
        def lrc(self, track):
            raise RuntimeError("lrclib down")

    engine, target = make_engine(qobuz, source, tmp_path, lyrics=ExplodingLyrics())

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert not outcome.lyrics_saved
    assert not (target / "Artist/01 - Song.lrc").exists()


def test_no_lyrics_when_none_found(tmp_path):
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(_flac_bytes(512))
    lyrics = FakeLyrics(text=None)
    engine, target = make_engine(qobuz, source, tmp_path, lyrics=lyrics)

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert not outcome.lyrics_saved


def test_tidal_upgrade_replaces_file_when_higher(tmp_path):
    qobuz = FakeQobuz([Quality.CD], delivered=(24, 44.1))
    tidal_content = _flac_bytes(2048, sample_rate=96000, bit_depth=24)
    source = RoutingSource(_flac_bytes(512), tidal_content)
    tidal = FakeTidal()
    engine, target = make_engine(qobuz, source, tmp_path, tidal=tidal)

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert outcome.upgraded
    assert outcome.bit_depth == 24
    assert outcome.sampling_rate == 96.0
    assert not outcome.fell_back
    final = target / "Artist/01 - Song.flac"
    assert final.read_bytes() == tidal_content
    assert not final.with_suffix(".flac.tidal.part").exists()
    assert tidal.lookups == ["t1"]
    assert tidal.stream_calls == ["9"]


def test_tidal_upgrade_keeps_qobuz_when_not_higher(tmp_path):
    qobuz = FakeQobuz([Quality.CD], delivered=(24, 44.1))
    qobuz_content = _flac_bytes(512, sample_rate=44100, bit_depth=24)
    source = RoutingSource(qobuz_content, _flac_bytes(512, sample_rate=44100))
    tidal = FakeTidal()
    engine, target = make_engine(qobuz, source, tmp_path, tidal=tidal)

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert not outcome.upgraded
    assert (target / "Artist/01 - Song.flac").read_bytes() == qobuz_content
    assert not (target / "Artist/01 - Song.flac.tidal.part").exists()


def test_tidal_upgrade_skipped_outside_quality_gate(tmp_path):
    for delivered in [(16, 44.1), (24, 96.0)]:
        qobuz = FakeQobuz([Quality.CD], delivered=delivered)
        source = FakeByteSource(_flac_bytes(512))
        tidal = FakeTidal()
        engine, _ = make_engine(qobuz, source, tmp_path, tidal=tidal)

        outcome = engine.download(TRACK, Quality.CD)

        assert isinstance(outcome, Complete)
        assert not outcome.upgraded
        assert tidal.lookups == []


def test_tidal_failure_never_fails_the_track(tmp_path):
    qobuz = FakeQobuz([Quality.CD], delivered=(24, 44.1))
    qobuz_content = _flac_bytes(512, sample_rate=44100, bit_depth=24)
    source = RoutingSource(qobuz_content, b"garbage")
    tidal = FakeTidal(stream_error=RuntimeError("tidal down"))
    engine, target = make_engine(qobuz, source, tmp_path, tidal=tidal)

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert not outcome.upgraded
    assert (target / "Artist/01 - Song.flac").read_bytes() == qobuz_content


def test_tidal_corrupt_flac_cleans_up_part(tmp_path):
    qobuz = FakeQobuz([Quality.CD], delivered=(24, 44.1))
    qobuz_content = _flac_bytes(512, sample_rate=44100, bit_depth=24)
    source = RoutingSource(qobuz_content, b"not a flac" * 10)
    tidal = FakeTidal()
    engine, target = make_engine(qobuz, source, tmp_path, tidal=tidal)

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert not outcome.upgraded
    assert (target / "Artist/01 - Song.flac").read_bytes() == qobuz_content
    assert not (target / "Artist/01 - Song.flac.tidal.part").exists()


def test_tidal_no_match_keeps_qobuz_file(tmp_path):
    qobuz = FakeQobuz([Quality.CD], delivered=(24, 44.1))
    source = FakeByteSource(_flac_bytes(512, sample_rate=44100, bit_depth=24))
    tidal = FakeTidal(match=None)
    engine, _ = make_engine(qobuz, source, tmp_path, tidal=tidal)

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert not outcome.upgraded
    assert tidal.stream_calls == []


def test_no_tidal_client_never_looks_up(tmp_path):
    qobuz = FakeQobuz([Quality.CD], delivered=(24, 44.1))
    source = FakeByteSource(_flac_bytes(512))
    engine, _ = make_engine(qobuz, source, tmp_path)

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert not outcome.upgraded
