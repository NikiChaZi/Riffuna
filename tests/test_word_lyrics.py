import json
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest, QSignalSpy

from musicdesk.lyric_timing import WordCue, parse_ttml, timestamp, estimated_words
from musicdesk.lyrics import LyricLine, LyricsStore, packet, parse_lrc
from musicdesk.lyrics_view import LyricsCanvas, LyricsDocument, LyricCue, LyricsState, document_from_payload
from musicdesk.lyrics_controller import LyricsController
from musicdesk.models import Track
from musicdesk.motion import MotionPolicy
from musicdesk.word_lyrics import BetterWords, compatible_words, parse_qrc
from test_ui_search import app, wait_for
from test_expanded_player import panel

TTML = '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="00:01.000" end="00:03.000"><span begin="00:01.000" end="00:02.000">Hello </span><span begin="00:02.000" end="00:03.000">world</span></p><p begin="00:04.000" end="00:06.000"><span begin="00:04.000" end="00:05.000">Another</span> <span begin="00:05.000" end="00:06.000">line</span></p></div></body></tt>'
TRACK=Track('aaaaaaaaaaa','Test','Artist',180)
BASE=packet(TRACK,'synced',lines=(LyricLine(1000,'Hello world'),LyricLine(4000,'Another line')),plain_text='Hello world\nAnother line',source='LRCLIB',timing_source='provider_lrc',match_quality='metadata_duration')


def test_ttml_words_preserve_spaces_and_absolute_times():
    rows=parse_ttml(TTML)
    assert [row.text for row in rows]==['Hello world','Another line']
    assert rows[0].words==(WordCue(1000,2000,'Hello '),WordCue(2000,3000,'world'))
    assert rows[1].words[0].text=='Another '
    assert timestamp('1:16.656')==76656
    assert timestamp('00:01:30.500')==90500
    assert timestamp('1500ms')==1500
    assert timestamp('1.5s')==1500


@pytest.mark.parametrize('value',['<!DOCTYPE a [<!ENTITY x "z">]><tt/>','<tt><body><p begin="1:00"><span begin="0:01" end="0:02">bad</span></p></body></tt>','<tt/>'])
def test_ttml_rejects_entities_missing_body_and_outside_timings(value):
    with pytest.raises(ValueError): parse_ttml(value)


def test_enhanced_lrc_strips_tags_and_keeps_real_word_starts():
    rows=parse_lrc('[offset:+100]\n[00:01.00]<00:01.00>Hello <00:02.00>world<00:03.00>\n[00:04.00]Next')
    assert rows[0].text=='Hello world'
    assert rows[0].words==(WordCue(900,1900,'Hello '),WordCue(1900,2900,'world'))
    assert rows[1]==LyricLine(3900,'Next')


def test_qrc_word_timing_and_reference_guard():
    qrc='[1000,2000]Hello (1000,1000)world(2000,1000)\n[4000,2000]Another (4000,1000)line(5000,1000)'
    rows=parse_qrc(qrc)
    assert compatible_words(TRACK,BASE,rows)
    assert not compatible_words(TRACK,dict(BASE,plain_text='Entirely different song'),rows)
    assert not compatible_words(TRACK,dict(BASE,lines=[dict(start_ms=20000,text='Hello world')]),rows)


def test_provider_failure_preserves_first_text_and_never_requires_key():
    class Response:
        status_code=401
        headers={}
        def __enter__(self): return self
        def __exit__(self,*args): pass
    class Session:
        calls=[]
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,*args,**kwargs):
            self.calls.append(kwargs)
            assert kwargs['allow_redirects'] is False
            assert not any('key' in k.lower() for k in kwargs['headers'])
            return Response()
    session=Session()
    assert BetterWords(lambda:session).enrich(TRACK,BASE)==BASE
    assert len(session.calls)==2


def test_provider_accepts_only_matching_bounded_words():
    class Response:
        status_code=200
        headers={'Content-Type':'application/json'}
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def iter_content(self,size): yield json.dumps({'ttml':TTML,'score':.99}).encode()
    class Session:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,*args,**kwargs): return Response()
    value=BetterWords(lambda:Session()).enrich(TRACK,BASE)
    assert value['timing_source']=='provider_words'
    document=document_from_payload(value)
    assert document.word_timing=='provided'
    assert document.cues[0].words[0].end_ms==2000


def test_local_ttml_import_overrides_and_can_be_replaced_by_lrc(tmp_path):
    path=tmp_path/'words.ttml';path.write_text(TTML,encoding='utf-8')
    store=LyricsStore(tmp_path/'cache')
    result=store.import_lrc(TRACK,path)
    assert result['timing_source']=='local_ttml'
    assert store.load(TRACK)==result
    lrc=tmp_path/'words.lrc';lrc.write_text('[00:01]New line\n[00:03]Another',encoding='utf-8')
    store.import_lrc(TRACK,lrc)
    assert not (store.directory/(TRACK.video_id+'.ttml')).exists()
    assert store.load(TRACK)['lines'][0]['text']=='New line'


def test_estimation_is_explicit_and_does_not_span_a_long_outro():
    words=estimated_words('One two three',1000,180000)
    assert words[0].start_ms==1000
    assert words[-1].end_ms<=5000
    assert all(a.end_ms==b.start_ms for a,b in zip(words,words[1:]))
    assert WordCue(1000,2000,'One').progress(1500)==.5


def test_word_progress_uses_real_position_freezes_and_seeks_back(app):
    canvas=LyricsCanvas(MotionPolicy(False))
    canvas.resize(600,450);canvas.show()
    canvas.set_document(document_from_payload(packet(TRACK,'synced',lines=parse_ttml(TTML),timing_source='provider_words',match_quality='metadata_duration')))
    canvas.set_playing(True)
    canvas.set_position(1500)
    QTest.qWait(130)
    assert canvas.word_progress(0)==(.5,0)
    assert canvas.word_progress(0,displayed=True)==(.5,0)
    QTest.qWait(150)
    assert canvas.word_progress(0,displayed=True)==(.5,0)  # never extrapolate audio
    canvas.set_playing(False);canvas.set_position(2500)
    assert canvas.word_progress(0)==(1,.5)
    assert not canvas._word_position.running
    canvas.set_position(1000)
    assert canvas.word_progress(0,displayed=True)==(0,0)
    canvas.close()


def test_unchanged_line_index_still_repaints_word_fill(app):
    canvas=LyricsCanvas(MotionPolicy(True));canvas.resize(600,450);canvas.show()
    canvas.set_document(document_from_payload(BASE));canvas.set_position(1400)
    first=canvas.grab().toImage()
    canvas.set_position(2100)
    second=canvas.grab().toImage()
    assert canvas.active_indices==(0,)
    assert first!=second
    assert canvas.word_progress(0)[0]>0
    canvas.close()


def test_focus_mode_keeps_transport_and_returns_to_cover(panel,app):
    host,source,view=panel
    view.open_from(source);view.set_seekable(True);view.set_duration(10000)
    view.focus_button.click();app.processEvents()
    assert not view.left.isVisible() and view.focus_transport.isVisible()
    assert view.lyrics.width()>900
    toggles=QSignalSpy(view.toggle_requested)
    view.focus_play.click()
    assert toggles.count()==1
    view.set_position(2000)
    assert view.focus_seek.value()==2000
    view.collapse();app.processEvents()
    assert not view.focus_button.isChecked() and not view.isVisible()
    assert source.hasFocus()


def test_background_words_do_not_delay_first_response_or_overwrite_new_track(app,tmp_path):
    started=threading.Event();release=threading.Event()
    class Store:
        def load(self,track,force=False): return dict(BASE,recording_id=track.video_id)
        def enrich_words(self,track,base,force=False):
            started.set();release.wait(3)
            return dict(base,source='Words',lines=packet(track,'synced',lines=parse_ttml(TTML))['lines'])
    controller=LyricsController(tmp_path,store=Store());seen=[]
    controller.changed.connect(lambda key,value:seen.append((key,value)))
    try:
        controller.load(TRACK);wait_for(started.is_set)
        assert any(value['state']=='synced' and value['source']=='LRCLIB' for key,value in seen)
        other=Track('bbbbbbbbbbb','Other','Artist',180)
        controller.load(other);release.set()
        wait_for(lambda:not controller._tasks)
        assert not any(key==TRACK.video_id and value.get('source')=='Words' for key,value in seen)
        assert seen[-1][0]==other.video_id
    finally:
        release.set();controller.shutdown();controller.pool.waitForDone(3000)


def test_word_cache_is_bound_to_recording_and_reference_text(tmp_path,monkeypatch):
    calls=[]
    def enrich(self,track,base):
        calls.append(base)
        return packet(track,'synced',lines=parse_ttml(TTML),plain_text='Hello world\nAnother line',source='Better Lyrics',timing_source='provider_words',match_quality='metadata_duration')
    monkeypatch.setattr(BetterWords,'enrich',enrich)
    store=LyricsStore(tmp_path,clock=lambda:1000)
    first=store.enrich_words(TRACK,BASE)
    assert first['lines'][0]['words']
    assert store.enrich_words(TRACK,BASE)==first
    assert len(calls)==1
    store.enrich_words(TRACK,dict(BASE,plain_text='Updated reference'))
    assert len(calls)==2


def test_returning_identical_enrichment_does_not_reset_view_twice(app,tmp_path):
    class Store:
        def load(self,track,force=False): return BASE
        def enrich_words(self,track,payload,force=False): return payload
    controller=LyricsController(tmp_path,store=Store());seen=[]
    controller.changed.connect(lambda key,payload:seen.append(payload))
    controller.load(TRACK)
    wait_for(lambda:not controller._tasks)
    assert sum(value['state']=='synced' for value in seen)==1
    controller.shutdown()
