import threading
from PySide6.QtTest import QTest
from test_ui_search import app, wait_for
from musicdesk.lyrics import packet
from musicdesk.lyrics_controller import LyricsController
from musicdesk.models import Track


def record(index):return Track(f'{index:011d}',f'Track {index}')


def test_late_lyrics_do_not_replace_current_recording(app,tmp_path):
    first=threading.Event();release=threading.Event()
    class Store:
        def load(self,track,force=False):
            if track.video_id==record(1).video_id:first.set();release.wait(3)
            return packet(track,'plain',plain_text='Invented test words')
    controller=LyricsController(tmp_path,store=Store());seen=[]
    controller.changed.connect(lambda key,value:seen.append((key,value['state'])))
    try:
        controller.load(record(1));wait_for(first.is_set)
        controller.load(record(2));wait_for(lambda:(record(2).video_id,'plain') in seen)
        release.set();wait_for(lambda:not controller._tasks)
        assert (record(1).video_id,'plain') not in seen
    finally:
        release.set();controller.shutdown();controller.pool.waitForDone(3000)


def test_rapid_switches_keep_two_workers_and_only_latest_pending(app,tmp_path):
    release=threading.Event();started=[]
    class Store:
        def load(self,track,force=False):
            started.append(track.video_id);release.wait(3)
            return packet(track,'not_found')
    controller=LyricsController(tmp_path,store=Store());seen=[]
    controller.changed.connect(lambda key,value:seen.append((key,value['state'])))
    try:
        controller.load(record(1));controller.load(record(2));wait_for(lambda:len(started)==2)
        controller.load(record(3));controller.load(record(4))
        assert len(controller._tasks)==2 and controller._pending[1]==record(4)
        release.set();wait_for(lambda:(record(4).video_id,'not_found') in seen)
        assert record(3).video_id not in started
        assert not any(key!=record(4).video_id and state=='not_found' for key,state in seen)
    finally:
        release.set();controller.shutdown();controller.pool.waitForDone(3000)


def test_import_invalidates_late_online_request(app,tmp_path):
    release=threading.Event();started=threading.Event()
    class Store:
        def load(self,track,force=False):started.set();release.wait(3);return packet(track,'plain',plain_text='Online')
        def import_lrc(self,track,path):return packet(track,'synced',plain_text='Local')
    controller=LyricsController(tmp_path,store=Store());seen=[]
    controller.changed.connect(lambda key,value:seen.append(value))
    try:
        controller.load(record(1));wait_for(started.is_set)
        controller.import_lrc(record(1),tmp_path/'input.lrc')
        release.set();wait_for(lambda:not controller._tasks)
        assert seen[-1]['state']=='synced' and seen[-1]['plain_text']=='Local'
    finally:
        release.set();controller.shutdown();controller.pool.waitForDone(3000)
