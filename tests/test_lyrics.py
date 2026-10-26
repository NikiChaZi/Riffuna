import json
from pathlib import Path
import pytest
from musicdesk.lyrics import (LRCLib, LyricsStore, LyricsUnavailable, LyricLine,
                              active_line, packet, parse_lrc)
from musicdesk.models import Track


def track(title="Test Song", duration=180, video_id="aaaaaaaaaaa"):
    return Track(video_id, title, "Test Artist", duration)


def response(**changes):
    value = {"id": 42, "trackName": "Test Song", "artistName": "Test Artist", "duration": 180,
             "instrumental": False, "plainLyrics": "First invented line\nSecond invented line",
             "syncedLyrics": "[00:10.00]First invented line\n[00:20.50]Second invented line"}
    value.update(changes)
    return value


class Response:
    def __init__(self, value, code=200, content_type="application/json"):
        self.value, self.status_code = value, code
        self.headers = {"Content-Type": content_type}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield json.dumps(self.value).encode()


class Session:
    def __init__(self, exact=None, results=()):
        self.exact, self.results, self.calls = exact, results, []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.exact, 404 if self.exact is None else 200) if url.endswith('/get') else Response(list(self.results))


def test_lrc_real_timestamps_repeats_offset_and_seek():
    rows = parse_lrc("[ar:Artist]\n[offset:+100]\n[00:01.1][00:03.004]First\n[00:02.03]Second\n[00:70]bad\n[00:03.004]First")
    assert rows == (LyricLine(1000, "First"), LyricLine(1930, "Second"), LyricLine(2904, "First"))
    assert active_line(rows, 999) == -1
    assert active_line(rows, 1930) == 1
    assert active_line(rows, 60000) == 2
    assert active_line(rows, 1500) == 0  # backwards seek uses actual position
    assert parse_lrc("plain text without timestamps") == ()


def test_lrc_negative_offset_bom_and_empty_timed_line():
    assert parse_lrc("\ufeff[offset:-200]\n[00:00.00]\n[00:01]Words") == (LyricLine(200, ""), LyricLine(1200, "Words"))
    with pytest.raises(ValueError): parse_lrc("x" * (1024 * 1024 + 1))


def test_synced_provider_exact_metadata_and_duration():
    session = Session(response(duration=181))
    result = LRCLib(lambda: session).fetch(track())
    assert result['state'] == 'synced'
    assert result['lines'][1] == {'start_ms': 20500, 'text': 'Second invented line'}
    assert result['match_quality'] == 'metadata_duration'
    assert result['timing_source'] == 'provider_lrc'
    assert len(session.calls) == 3
    assert session.calls[0][1]['params']['duration'] == 180


@pytest.mark.parametrize('title', ['Test Song (Slowed)', 'Test Song (Remix)', 'Test Song (Mashup)', 'Test Song (Sped Up)'])
def test_does_not_apply_original_timestamps_to_different_edition(title):
    session = Session(response(), [response()])
    assert LRCLib(lambda: session).fetch(track(title))['state'] == 'not_found'


def test_matching_slowed_recording_has_own_real_timestamps():
    value = response(trackName='Test Song (Slowed)', duration=220)
    result = LRCLib(lambda: Session(value)).fetch(track('Test Song (Slowed)', 220))
    assert result['state'] == 'synced'


@pytest.mark.parametrize('duration',[0, 160, 200])
def test_wrong_or_unknown_duration_only_allows_plain_text(duration):
    result = LRCLib(lambda: Session(response())).fetch(track(duration=duration))
    assert result['state'] == 'plain'
    assert not result['lines'] and result['timing_source'] == 'none'


def test_search_chooses_recording_with_correct_duration():
    session = Session(None, [response(id=1, duration=240), response(id=2, duration=180)])
    result = LRCLib(lambda: session).fetch(track())
    assert result['state'] == 'synced' and result['source_url'].endswith('/2')
    assert LRCLib(lambda: Session(response(artistName='Wrong Singer'))).fetch(track())['state'] == 'not_found'


def test_instrumental_and_missing_lyrics_are_distinct():
    result = LRCLib(lambda: Session(response(instrumental=True, plainLyrics=None, syncedLyrics=None))).fetch(track())
    assert result['state'] == 'instrumental' and not result['lines']
    assert LRCLib(lambda: Session(None)).fetch(track())['state'] == 'not_found'


@pytest.mark.parametrize('code',[429,503,500])
def test_http_errors_do_not_produce_fake_lyrics(code):
    class Failed(Session):
        def get(self, *args, **kwargs): return Response({},code)
    with pytest.raises(LyricsUnavailable): LRCLib(Failed).fetch(track())


def test_non_json_response_is_reported_cleanly():
    class Failed(Session):
        def get(self,*args,**kwargs):return Response({},content_type='text/html')
    with pytest.raises(LyricsUnavailable):LRCLib(Failed).fetch(track())


def test_recording_cache_force_refresh_and_metadata_change(tmp_path):
    class Provider:
        calls = 0
        def fetch(self, value):
            self.calls += 1
            return packet(value,'synced',lines=(LyricLine(100,'Own invented line'),))
    provider = Provider(); store=LyricsStore(tmp_path,provider)
    assert store.load(track())['state']=='synced'
    store.load(track()); assert provider.calls==1
    store.load(track(),force=True); assert provider.calls==2
    store.load(track(duration=181)); assert provider.calls==3
    store.load(track(video_id='bbbbbbbbbbb')); assert provider.calls==4


def test_local_lrc_wins_over_online_and_survives_restart(tmp_path):
    class Offline:
        def fetch(self, value):raise AssertionError('Local lyrics must not access network')
    source=tmp_path/'input.lrc';source.write_text('[00:05.50]Local invented line',encoding='utf-8')
    store=LyricsStore(tmp_path/'lyrics',Offline())
    result=store.import_lrc(track(),source)
    assert result['match_quality']=='user_import'
    assert LyricsStore(tmp_path/'lyrics',Offline()).load(track())['lines'][0]['start_ms']==5500
    source.write_text('no timing',encoding='utf-8')
    with pytest.raises(LyricsUnavailable):store.import_lrc(track(),source)
    assert store.load(track())['lines'][0]['start_ms']==5500


def test_negative_cache_expires_and_corrupt_cache_is_ignored(tmp_path):
    class Provider:
        calls=0
        def fetch(self,value):self.calls+=1;return packet(value,'not_found')
    clock=[100];provider=Provider();store=LyricsStore(tmp_path,provider,clock=lambda:clock[0])
    store.load(track());store.load(track());assert provider.calls==1
    clock[0]+=3601;store.load(track());assert provider.calls==2
    (tmp_path/'aaaaaaaaaaa.json').write_text('{broken',encoding='utf-8')
    store.load(track());assert provider.calls==3


def test_single_timestamp_record_does_not_hide_complete_timed_search_result():
    broken = response(id=1, syncedLyrics="[00:01]stub", plainLyrics="stub")
    complete = response(id=2)
    result = LRCLib(lambda: Session(broken, [broken, complete])).fetch(track())
    assert result["state"] == "synced" and len(result["lines"]) == 2
    assert result["source_url"].endswith("/2")
    result = LRCLib(lambda: Session(broken)).fetch(track())
    assert result["state"] == "plain" and not result["lines"]


def test_transient_failure_retries_once_and_recovers_without_losing_sync():
    class Flaky(Session):
        calls_count=0
        def get(self,url,**kwargs):
            self.calls_count+=1
            if self.calls_count==1:
                answer=Response({},503);answer.headers["Retry-After"]="300";return answer
            return Response(response(syncedLyrics="[00:10]Invented first line\n[02:45]Invented final line"))
    session=Flaky();delays=[]
    result=LRCLib(lambda:session,sleeper=delays.append).fetch(track())
    assert result["state"]=="synced" and session.calls_count==2
    assert delays==[1.0]


def test_retry_is_bounded_and_error_does_not_become_not_found():
    import requests
    class Offline(Session):
        count=0
        def get(self,*args,**kwargs):self.count+=1;raise requests.ConnectionError()
    session=Offline()
    with pytest.raises(LyricsUnavailable):LRCLib(lambda:session,sleeper=lambda _:None).fetch(track())
    assert session.count==2


def test_refresh_offline_preserves_saved_recording_but_not_other_metadata(tmp_path):
    class Provider:
        offline=False
        def fetch(self,t):
            if self.offline:raise LyricsUnavailable("offline")
            return packet(t,"synced",lines=[LyricLine(100,"Invented line")])
    provider=Provider();store=LyricsStore(tmp_path,provider)
    store.load(track());provider.offline=True
    cached=store.load(track(),force=True)
    assert cached["state"]=="synced" and cached["cache_stale"]
    with pytest.raises(LyricsUnavailable):store.load(track(duration=200))


def test_artist_prefix_unicode_dash_and_yo_e_do_not_hide_lyrics():
    r=response(trackName="Елки")
    result=LRCLib(lambda:Session(r)).fetch(track("Test Artist — Ёлки"))
    assert result["state"]=="synced"


def test_title_only_fallback_matches_exact_artist_transliteration_with_own_duration():
    class Alias(Session):
        def get(self,url,**kwargs):
            self.calls.append((url,kwargs))
            if "artist_name" in kwargs["params"]:return Response(None,404) if url.endswith("/get") else Response([])
            return Response([response(trackName="Понарошку",artistName="Дора",duration=151)])
    session=Alias()
    result=LRCLib(lambda:session).fetch(Track("aaaaaaaaaaa","Понарошку","Dora",151))
    assert result["state"]=="synced"
    assert session.calls[-1][1]["params"]=={"track_name":"Понарошку"}
    assert LRCLib(lambda:Session(None,[response(trackName="Понарошку",artistName="Дора",duration=147)])).fetch(Track("aaaaaaaaaaa","Понарошку","Dora",151))["state"]=="plain"


def test_title_only_fallback_keeps_artist_and_edition_gates():
    for artist,title in [("Other Artist","Понарошку"),("Дора","Понарошку (Slowed)")]:
        result=LRCLib(lambda:Session(None,[response(trackName=title,artistName=artist,duration=151)])).fetch(Track("aaaaaaaaaaa","Понарошку","Dora",151))
        assert result["state"]=="not_found"


def test_artist_suffix_and_upload_declaration_do_not_hide_original_lyrics():
    r=response(trackName="Some Song",artistName="Some Artist",duration=154)
    t=Track("aaaaaaaaaaa","Some Song – Some Artist (без цензуры)","Some Artist",154)
    result=LRCLib(lambda:Session(r)).fetch(t)
    assert result["state"]=="synced"
    assert LRCLib(lambda:Session(r)).fetch(Track("aaaaaaaaaaa","Some Song (Slowed) – Some Artist (без цензуры)","Some Artist",154))["state"]=="not_found"


def test_search_replaces_prematurely_finished_exact_lrc_without_stretching_timestamps():
    bad=response(id=1,duration=146,syncedLyrics="[00:01]Invented first line\n[01:44]Invented final line")
    good=response(id=2,duration=146.422,syncedLyrics="[00:02.61]Invented first line\n[02:14.11]Invented final line")
    result=LRCLib(lambda:Session(bad,[bad,good])).fetch(track(duration=147))
    assert result["source_url"].endswith("/2")
    assert result["lines"][-1]["start_ms"]==134110


def test_valid_early_vocal_ending_is_kept_when_no_better_candidate_exists():
    row=response(duration=180)
    result=LRCLib(lambda:Session(row)).fetch(track())
    assert result["state"]=="synced"  # long instrumental outro alone is not corruption
    assert result["lines"][-1]["start_ms"]==20500


def test_timestamps_beyond_audio_end_are_never_used_for_sync():
    row=response(duration=180,syncedLyrics="[00:10]Invented first\n[04:00]Invented last")
    assert LRCLib(lambda:Session(row)).fetch(track())["state"]=="plain"


def test_player_status_decoration_needs_corroborating_same_song_words():
    bad=response(id=1,duration=146,syncedLyrics="[00:01]Invented first line\n[01:44]Invented final line")
    good=response(id=2,trackName="Test Song (Paused)",duration=146.422,syncedLyrics="[00:02.61]Invented first line\n[02:14.11]Invented final line")
    result=LRCLib(lambda:Session(bad,[bad,good])).fetch(track(duration=147))
    assert result["source_url"].endswith("/2") and result["lines"][-1]["start_ms"]==134110
    other=response(id=3,trackName="Test Song (Paused)",duration=146.422,plainLyrics="Completely unrelated invented content")
    result=LRCLib(lambda:Session(bad,[bad,other])).fetch(track(duration=147))
    assert result["source_url"].endswith("/1")


def test_repeated_lyric_words_are_not_discarded_as_diff_noise():
    words=" ".join(["Придуманный текст для проверки повторяющихся слов"]*30)
    bad=response(id=1,duration=146,plainLyrics=words,syncedLyrics="[00:01]Invented first\n[01:44]Invented last")
    good=response(id=2,trackName="Test Song (Paused)",duration=146.422,plainLyrics="Начало "+words,syncedLyrics="[00:02.61]Invented first\n[02:14.11]Invented last")
    result=LRCLib(lambda:Session(bad,[bad,good])).fetch(track(duration=147))
    assert result["source_url"].endswith("/2")
