from musicdesk.models import Track
from musicdesk.storage import Library

def test_choice_survives_restart_without_rewriting_likes_history_or_queue(tmp_path):
    from musicdesk.models import PlayQueue
    path=tmp_path/"library.sqlite3";library=Library(path)
    original=Track("aaaaaaaaaaa","Test Song","Artist",180);replacement=Track("bbbbbbbbbbb","Test Song (Uncensored)","Artist",181)
    slowed=Track("ccccccccccc","Test Song (Slowed)","Artist",210)
    library.like(original,True);library.record_play(original);library.save_queue(PlayQueue([original],0))
    library.prefer_recording(original,replacement)
    assert library.liked_ids()=={original.video_id}
    assert library.history()==[original]
    assert library.load_queue().tracks==[original]
    library.close();library=Library(path)
    assert library.preferred_recording(original)==replacement
    assert library.preferred_recording(slowed)==slowed
    library.close()
