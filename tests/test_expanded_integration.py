from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog
from test_ui_search import app,make_window,tracks,wait_for
from musicdesk.lyrics import packet,LyricLine
from musicdesk.lyrics_view import LyricsState

def test_cover_opens_actual_window_and_import_drives_position_without_replacing_audio(make_window,monkeypatch,tmp_path):
    window,_=make_window(lambda *args:[]);record=tracks(1)[0]
    player=window.playback.player;output=window.playback.output
    monkeypatch.setattr(window.playback,"_open_current",lambda:None)
    window.playback.play(record)
    window.playback.track_changed.emit(record)
    class Store:
        def load(self,track,force=False):return packet(track,"not_found")
        def import_lrc(self,track,path):return packet(track,"synced",lines=[LyricLine(1000,"Invented first line"),LyricLine(5000,"Invented second line")],source="local",timing_source="local_lrc",match_quality="user_import")
    window.lyrics_controller.store=Store()
    window.motion_policy.set_reduced(True)
    window.current_cover.activated.emit()
    assert window.expanded_player.isVisible()
    wait_for(lambda:not window.lyrics_controller._tasks)
    assert window.expanded_player.track==record
    monkeypatch.setattr(QFileDialog,"getOpenFileName",lambda *args:(str(tmp_path/"words.lrc"),""))
    window.expanded_player.import_requested.emit(record.video_id)
    assert window.expanded_player.lyrics.document.state==LyricsState.SYNCED
    window.playback.position_changed.emit(5500)
    assert window.expanded_player.lyrics.canvas.active_indices==(1,)
    window.expanded_player.like_requested.emit(record.video_id)
    assert record.video_id in window.library.liked_ids()
    window.expanded_player.collapse()
    assert not window.expanded_player.isVisible()
    assert window.playback.player is player and window.playback.output is output

def test_recommendation_page_uses_likes_and_ignores_late_close(make_window,monkeypatch):
    from musicdesk.recommendations import Suggestion
    window,_=make_window(lambda *args:[]);record=tracks(1)[0];window.library.like(record,True)
    captured=[]
    def recommend(seeds,excluded):
        captured.extend(seeds);return dict(status="ok",coverage={"track":1},items=[Suggestion("catalog1","Suggestion","Other Artist")])
    monkeypatch.setattr(window._recommendation_client,"recommend",recommend)
    window.show_view("resonance")
    wait_for(lambda:window._recommendation_result is not None)
    assert [r.video_id for r in captured]==[record.video_id]
    assert window.stack.currentWidget() is window.recommendation_page
    assert len(window.recommendation_page.rows)==1
