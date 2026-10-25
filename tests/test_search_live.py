"""Opt in: $env:RIFFUNA_LIVE_SEARCH='1'; python -m pytest tests/test_search_live.py -s.

Checks studio audio, not the obsolete volume proof for unrestricted video
search. Narrow queries may return fewer than 40 tracks instead of video trash.
No video is downloaded or resolved to a signed stream URL.
"""
import json
import os

import pytest

from musicdesk.youtube import YouTubeSource

pytestmark = pytest.mark.skipif(os.environ.get('RIFFUNA_LIVE_SEARCH') != '1',
                                reason='opt-in YouTube Music network check')


@pytest.mark.parametrize('order', ['relevance', 'views'])
@pytest.mark.parametrize(('query', 'expected_id'), [
    ('Дора ЁК', '1ySTQ_e0SmU'),
    ('Дора', None),
    ('LONOWN worry ultra slowed', 'lCKU-tI-upI'),
])
def test_live_studio_music_search(query, expected_id, order):
    tracks = YouTubeSource().search(query, limit=40, order=order)
    assert tracks
    assert len(tracks) == len({t.video_id for t in tracks}) <= 40
    assert all(0 < t.duration <= 1200 for t in tracks)
    if expected_id:
        assert expected_id in {t.video_id for t in tracks}
    if order == 'views':
        known = [t.view_count for t in tracks if t.view_count is not None]
        assert known == sorted(known, reverse=True)
        assert known
    print(json.dumps({'query': query, 'order': order, 'count': len(tracks),
                      'counts_present': sum(t.view_count is not None for t in tracks),
                      'top': [{'id': t.video_id, 'title': t.title, 'artist': t.artist,
                               'duration': t.duration, 'views': t.view_count} for t in tracks[:6]]}))
