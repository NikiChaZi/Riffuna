import threading

import pytest

import musicdesk.youtube as youtube
from musicdesk.models import Track
from musicdesk.youtube import AudioStream, SourceError, YouTubeSource, _query_score, _studio_audio, track_from_extract, track_from_music


_REAL_MUSIC_FALLBACK = YouTubeSource._music_fallback


def song(index=1, title='ЁК', artist='Дора', duration=160, **extra):
    row = {'resultType': 'song', 'videoType': 'MUSIC_VIDEO_TYPE_ATV',
           'videoId': f'{index:011d}', 'title': title, 'artists': [{'name': artist}],
           'duration_seconds': duration, 'album': {'name': 'Studio album', 'id': 'MPREb_album'},
           'isAvailable': True}
    row.update(extra)
    return row


def fake_music(monkeypatch, rows, details=None):
    calls = {'search': [], 'song': []}
    monkeypatch.setattr(YouTubeSource, '_music_fallback', lambda self, query: [])
    lock = threading.Lock()
    class Music:
        def __init__(self, requests_session):
            self.session = requests_session
        def search(self, query, **kwargs):
            calls['search'].append((query, kwargs))
            if isinstance(rows, Exception):
                raise rows
            return rows(query, kwargs) if callable(rows) else rows
        def get_song(self, video_id):
            with lock:
                calls['song'].append(video_id)
            if callable(details):
                return details(video_id)
            if isinstance(details, Exception):
                raise details
            if details is not None:
                return details
            return {'videoDetails': {'musicVideoType': 'MUSIC_VIDEO_TYPE_ATV',
                                      'viewCount': str(int(video_id) + 100), 'isLiveContent': False}}
    monkeypatch.setattr(youtube, 'YTMusic', Music)
    # A catalog failure must never silently fall back to general videos.
    monkeypatch.setattr(youtube, 'YoutubeDL', lambda *a, **k: pytest.fail('general video search is forbidden'))
    return calls


def test_flat_search_metadata_missing_duration():
    result = track_from_extract({'id': 'ewCPQeAtICk', 'title': 'Втюрилась', 'channel': 'Дора'})
    assert result.artist == 'Дора'
    assert result.duration == 0
    assert result.view_count is None
    assert result.published == ''


def test_music_metadata_does_not_merge_version():
    result = track_from_music({'videoId': 'lCKU-tI-upI', 'title': 'worry (ultra slowed)',
                               'duration': '4:16', 'artists': [{'name': 'LONOWN'}, {'name': 'riserayss'}]})
    assert result.version == 'ULTRA SLOWED'
    assert result.artist == 'LONOWN, riserayss'
    assert result.duration == 256


@pytest.mark.parametrize('row', [None, {}, {'id': 'channel', 'title': 'channel'},
                                {'id': 'ewCPQeAtICk', 'title': 42}])
def test_non_video_rows_are_ignored(row):
    assert track_from_extract(row) is None


@pytest.mark.parametrize('row', [None, {}, {'videoId': 'bad', 'title': 'Song'},
                                {'videoId': 'ewCPQeAtICk', 'title': 'Song', 'artists': [None]}])
def test_malformed_music_metadata_is_ignored(row):
    assert track_from_music(row) is None


@pytest.mark.parametrize(('count', 'expected'), [(0, 0), (456, 456), ('1234', 1234),
                                               (None, None), ('4.2M', None), (-1, None), (True, None)])
def test_extract_preserves_only_real_numeric_counts(count, expected):
    result = track_from_extract({'id': 'ewCPQeAtICk', 'title': 'Song', 'view_count': count,
                                 'published': '2 days ago', 'timestamp': 1735689600})
    assert result.view_count == expected
    assert result.published == '2 days ago'


def test_extract_preserves_upload_date_and_nullable_thumbnails():
    result = track_from_extract({'id': 'ewCPQeAtICk', 'title': 'Song', 'duration': 125.5,
                                 'thumbnails': [{'height': None}, {'height': 120, 'url': 'thumb'}],
                                 'upload_date': '20261024'})
    assert (result.duration, result.thumbnail, result.published) == (125, 'thumb', '20261024')


def test_publication_is_not_invented_from_a_timestamp():
    result = track_from_extract({'id': 'ewCPQeAtICk', 'title': 'Song', 'timestamp': 1735689600})
    assert result.published == ''


@pytest.mark.parametrize(('title', 'duration', 'video_type', 'keep'), [
    ('Дора — ЁК', 160, 'MUSIC_VIDEO_TYPE_ATV', True),
    ('Дора — ЁК (Премьера клипа, 2025)', 208, 'MUSIC_VIDEO_TYPE_OMV', False),
    ('Дора | ЁК Live (Ростов-на-Дону...)', 158, 'MUSIC_VIDEO_TYPE_UGC', False),
    ('Дора — ЁК | Разбор трека', 1573, 'MUSIC_VIDEO_TYPE_UGC', False),
    ('Дора — ЁК 1 час', 3664, 'MUSIC_VIDEO_TYPE_UGC', False),
    ('BY_OWL СМОТРИТ - Дора — ЁК (Премьера клипа...)', 1200, 'MUSIC_VIDEO_TYPE_UGC', False),
])
def test_all_six_screenshot_examples(title, duration, video_type, keep):
    row = song(title=title, duration=duration, videoType=video_type)
    assert (_studio_audio(row, 'Дора ЁК') is not None) is keep


@pytest.mark.parametrize('title', [
    'ЁК (Премьера клипа, 2025)', 'ЁК Live', 'ЁК концерт', 'ЁК | Разбор трека',
    'BY_OWL СМОТРИТ — ЁК', 'ЁК reaction', 'ЁК official music video', 'ЁК (1 час)',
    'ЁК 1 Hour Loop', 'ЁК Looped', 'ЁК review', 'ЁК мультфильм', 'ЁК episode 1',
])
def test_catalog_classification_does_not_override_explicit_exclusions(title):
    assert _studio_audio(song(title=title), 'Дора ЁК') is None


@pytest.mark.parametrize('video_type', ['MUSIC_VIDEO_TYPE_OMV', 'MUSIC_VIDEO_TYPE_UGC', None, ''])
def test_title_alone_never_proves_studio_music(video_type):
    # Even a clean title/short duration can belong to cartoons or video clips.
    assert _studio_audio(song(title='ЁК', videoType=video_type), 'Дора ЁК') is None


@pytest.mark.parametrize('title', ['worry (ultra slowed)', 'worry (Mashup)', 'worry (Remix)',
                                  'worry (Sped Up)', 'worry (Slowed + Reverb)'])
def test_catalog_musical_variants_remain_allowed(title):
    assert _studio_audio(song(title=title, artist='LONOWN'), 'LONOWN worry') is not None


def test_exact_slowed_variant_is_not_merged_with_other_versions():
    assert _studio_audio(song(title='worry (ultra slowed)', artist='LONOWN'), 'LONOWN worry ultra slowed')
    assert _studio_audio(song(title='worry (Super Slowed)', artist='LONOWN'), 'LONOWN worry ultra slowed') is None


def test_query_words_are_matched_across_artist_and_title_without_order_dependency():
    assert _studio_audio(song(title='ЁК'), 'ек дора')
    assert _studio_audio(song(title='ЁК'), 'Дора ЁК official audio')
    assert _studio_audio(song(title='worry (Mashup)', artist='LONOWN'), 'LONOWN worry мэшап')
    assert _studio_audio(song(title='𝖜𝖔𝖗𝖗𝖞 (ultra slowed)', artist='LONOWN'), 'LONOWN worry ultra slowed')


def test_unrelated_spelling_expansions_are_not_backfilled():
    assert _studio_audio(song(title='Zemer', artist='Dhurata Dora'), 'Дора') is None
    assert _studio_audio(song(title='ЗНАК'), 'Дора ЁК') is None


@pytest.mark.parametrize('extra', [{'isAvailable': False}, {'live': True}, {'isLiveContent': True},
                                  {'duration_seconds': 0}, {'duration_seconds': 1201},
                                  {'album': {'name': 'Live in Moscow'}}, {'resultType': 'video'}])
def test_unavailable_live_or_long_catalog_rows_are_excluded(extra):
    assert _studio_audio(song(**extra), 'Дора ЁК') is None


def test_duration_boundary_and_live_substring():
    assert _studio_audio(song(title='Deliver', duration=1200), 'Дора')


@pytest.mark.parametrize('limit', [40, 80, 120])
def test_songs_filter_and_continuation_limit_expand(monkeypatch, limit):
    calls = fake_music(monkeypatch, [song(i, title=f'Song {i}') for i in range(400)])
    tracks = YouTubeSource().search('Дора', limit=limit)
    assert len(tracks) == len({t.video_id for t in tracks}) == limit
    assert calls['search'] == [('"Дора"', {'filter': 'songs', 'limit': limit * 3, 'ignore_spelling': False})]
    assert calls['song'] == []  # Relevance does not fetch per-song counts.


def test_search_default_is_40(monkeypatch):
    fake_music(monkeypatch, [song(i, title=f'Song {i}') for i in range(100)])
    assert len(YouTubeSource().search('Дора')) == 40


def test_fewer_clean_results_is_valid_and_never_filled_with_video_trash(monkeypatch):
    fake_music(monkeypatch, [song(), song(), song(2, title='ЁК Live'),
                             song(3, title='Дора — ЁК', videoType='MUSIC_VIDEO_TYPE_OMV'),
                             song(4, title='Some other song')])
    assert len(YouTubeSource().search('Дора ЁК', limit=40)) == 1


@pytest.mark.parametrize(('query', 'expected'), [
    ('Дора', '"Дора"'), ('ёлка', '"ёлка"'), ('Україна', '"Україна"'),
    ('Дора ЁК', 'Дора ЁК'), ('Дора mashup', 'Дора mashup'), ('Dora', 'Dora'),
    ('"Дора"', '"Дора"'), ('Мэйби-бэйби', 'Мэйби-бэйби'),
])
def test_only_one_unquoted_cyrillic_word_is_quoted(monkeypatch, query, expected):
    calls = fake_music(monkeypatch, [])
    YouTubeSource().search(query)
    assert calls['search'][0][0] == expected


def test_relevance_preserves_catalog_order_and_fetches_no_counts(monkeypatch):
    calls = fake_music(monkeypatch, [song(2), song(1), song(3)])
    assert [t.video_id for t in YouTubeSource().search('Дора ЁК')] == ['00000000002', '00000000001', '00000000003']
    assert calls['song'] == []


def test_views_ranks_real_counts_and_caches_metadata(monkeypatch):
    calls = fake_music(monkeypatch, [song(1), song(3), song(2)])
    source = YouTubeSource()
    for _ in range(2):
        tracks = source.search('Дора ЁК', order='views')
        assert [t.view_count for t in tracks] == [103, 102, 101]
    assert sorted(calls['song']) == ['00000000001', '00000000002', '00000000003']


def test_views_overfetches_clean_candidates_before_ranking(monkeypatch):
    fake_music(monkeypatch, [song(1), song(3), song(2)])
    assert YouTubeSource().search('Дора ЁК', limit=1, order='views')[0].view_count == 103


def test_views_does_not_invent_counts_from_abbreviated_album_plays(monkeypatch):
    fake_music(monkeypatch, [song(1, views='76M')], OSError('unavailable'))
    with pytest.raises(SourceError, match='просмотры'):
        YouTubeSource().search('Дора ЁК', order='views')


def test_views_rejects_video_or_live_classification_from_song_details(monkeypatch):
    fake_music(monkeypatch, [song(1)], {'videoDetails': {'musicVideoType': 'MUSIC_VIDEO_TYPE_OMV', 'viewCount': '1000'}})
    assert YouTubeSource().search('Дора ЁК', order='views') == []


def test_views_places_unknown_counts_after_real_zero(monkeypatch):
    def details(video_id):
        return {'videoDetails': {'musicVideoType': 'MUSIC_VIDEO_TYPE_ATV',
                                 'viewCount': '0' if video_id.endswith('2') else None}}
    fake_music(monkeypatch, [song(1), song(2)], details)
    assert [t.view_count for t in YouTubeSource().search('Дора ЁК', order='views')] == [0, None]


def test_count_metadata_concurrency_is_bounded_and_sessions_are_not_shared(monkeypatch):
    active, peak = 0, 0
    clients = {}
    lock = threading.Lock()
    import time
    class Music:
        def __init__(self, requests_session):
            self.session = requests_session
        def get_song(self, video_id):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                clients.setdefault(threading.get_ident(), set()).add(id(self.session))
            time.sleep(0.005)
            with lock:
                active -= 1
            return {'videoDetails': {'musicVideoType': 'MUSIC_VIDEO_TYPE_ATV', 'viewCount': '10'}}
    monkeypatch.setattr(youtube, 'YTMusic', Music)
    tracks = [track_from_music(song(i)) for i in range(20)]
    assert len(YouTubeSource()._with_view_counts(tracks)) == 20
    assert 1 < peak <= 4
    assert all(len(sessions) == 1 for sessions in clients.values())
    assert len({session for sessions in clients.values() for session in sessions}) == len(clients)


def test_catalog_network_error_is_wrapped_without_general_video_fallback(monkeypatch):
    fake_music(monkeypatch, OSError('offline'))
    with pytest.raises(SourceError) as error:
        YouTubeSource().search('Дора')
    assert isinstance(error.value.__cause__, OSError)


@pytest.mark.parametrize(('query', 'limit'), [('', 40), ('  ', 40), ('Дора', 0), ('Дора', -1)])
def test_empty_search_does_not_use_network(monkeypatch, query, limit):
    monkeypatch.setattr(youtube, 'YTMusic', lambda **kw: pytest.fail('unexpected network'))
    assert YouTubeSource().search(query, limit) == []


@pytest.mark.parametrize('limit', [1.5, '40', True])
def test_invalid_limit_is_rejected(limit):
    with pytest.raises(ValueError, match='limit'):
        YouTubeSource().search('Дора', limit=limit)


def test_unknown_sort_is_rejected():
    with pytest.raises(ValueError, match='order'):
        YouTubeSource().search('Дора', order='fake-popularity')


def test_date_does_not_silently_return_relevance():
    with pytest.raises(SourceError, match='по дате'):
        YouTubeSource().search('Дора', order='date')


def test_arbitrary_url_is_rejected_before_network():
    with pytest.raises(SourceError):
        YouTubeSource().search('https://youtube.com.attacker.example/watch?v=ewCPQeAtICk')


def test_direct_audio_link_is_checked_and_preserved(monkeypatch):
    fake_music(monkeypatch, [], {'videoDetails': {'musicVideoType': 'MUSIC_VIDEO_TYPE_ATV',
               'title': 'ЁК', 'author': 'Дора', 'lengthSeconds': '160', 'viewCount': '123'}})
    tracks = YouTubeSource().search('https://youtu.be/1ySTQ_e0SmU')
    assert len(tracks) == 1
    assert (tracks[0].duration, tracks[0].view_count) == (160, 123)


def test_direct_music_video_link_is_rejected(monkeypatch):
    fake_music(monkeypatch, [], {'videoDetails': {'musicVideoType': 'MUSIC_VIDEO_TYPE_OMV',
               'title': 'ЁК', 'author': 'Дора', 'lengthSeconds': '208'}})
    with pytest.raises(SourceError, match='аудиозаписи'):
        YouTubeSource().search('https://youtu.be/1ySTQ_e0SmU')


def test_music_display_plays_are_not_mistaken_for_video_view_count():
    assert track_from_music(song(views='123')).view_count is None
    assert track_from_music(song(viewCount='123')).view_count == 123


def test_nullable_album_metadata_does_not_break_audio_parsing():
    assert _studio_audio(song(album=None), 'Дора ЁК')
    assert _studio_audio(song(album='unknown'), 'Дора ЁК')


def music_upload_payload(video_id='N3472Q6kvg0', title='Rules of Nature Extended', category='Music', video_type='MUSIC_VIDEO_TYPE_UGC'):
    return {'videoDetails': {'videoId': video_id, 'title': title, 'author': 'Crimson',
            'musicVideoType': video_type, 'lengthSeconds': '266', 'viewCount': '35079511', 'isLiveContent': False},
            'microformat': {'microformatDataRenderer': {'category': category, 'uploadDate': '2013-02-20'}}}


@pytest.mark.parametrize('query', ['rule of nature', 'rules of nature',
    'Metal Gear Rising Revengeance OST Rules of Nature Extended Crimson'])
def test_ost_extended_upload_is_allowed_with_positive_music_metadata(query):
    payload = music_upload_payload(title='Metal Gear Rising: Revengeance OST - Rules of Nature Extended')
    track = YouTubeSource._audio_from_metadata(payload, 'N3472Q6kvg0', query)
    assert track and track.video_id == 'N3472Q6kvg0'
    assert track.view_count == 35079511


@pytest.mark.parametrize('query', ['rule of nature', 'rules of nature'])
def test_reversed_word_bag_nature_soundscapes_does_not_match(query):
    assert _query_score(query, 'The Sounds of Calm Water and Nature Rule', 'Water Soundscapes') < 0
    assert _query_score(query, 'Rules of Nature', 'Jason Charles Miller') >= 0


def test_approximate_matching_is_general_and_preserves_artist_title_reordering():
    assert _query_score('сан лоран дора', 'Сан Ларан', 'Платина, Дора') >= 0
    assert _query_score('доар', 'ЁК', 'Дора') < 0  # small words are not guessed
    assert _query_score('LONOWN worry mashup', 'worry (Mashup)', 'LONOWN') >= 0


@pytest.mark.parametrize(('title', 'category', 'video_type'), [
    ('Rules of Nature Extended', 'Gaming', 'MUSIC_VIDEO_TYPE_UGC'),
    ('Rules of Nature Extended', 'Music', 'MUSIC_VIDEO_TYPE_OMV'),
    ('Rules of Nature Extended Reaction', 'Music', 'MUSIC_VIDEO_TYPE_UGC'),
    ('Rules of Nature Extended Live', 'Music', 'MUSIC_VIDEO_TYPE_UGC'),
    ('Rules of Nature Extended 1 hour loop', 'Music', 'MUSIC_VIDEO_TYPE_UGC'),
    ('Rules of Nature Extended SFM', 'Music', 'MUSIC_VIDEO_TYPE_UGC'),
])
def test_music_fallback_still_rejects_nonmusic_clips_live_and_loops(title, category, video_type):
    assert YouTubeSource._audio_from_metadata(music_upload_payload(title=title, category=category,
           video_type=video_type), 'N3472Q6kvg0', 'rules of nature') is None


@pytest.mark.parametrize('title', ['worry (slowed)', 'worry (mashup)', 'worry (remix)', 'worry (extended)'])
def test_music_classified_user_versions_are_allowed(title):
    assert YouTubeSource._audio_from_metadata(music_upload_payload(title=title), 'N3472Q6kvg0', 'worry')


def test_verified_ost_fallback_appears_even_when_catalog_has_exact_song(monkeypatch):
    fake_music(monkeypatch, [song(1, 'Rules of Nature', 'Jason Charles Miller'),
                            song(2, 'The Sounds of Water and Nature Rule', 'Water Soundscapes')])
    upload = Track('N3472Q6kvg0', 'Metal Gear Rising: Revengeance OST - Rules of Nature Extended', 'Crimson', 266)
    monkeypatch.setattr(YouTubeSource, '_music_fallback', lambda self, query: [upload])
    tracks = YouTubeSource().search('rule of nature')
    assert upload in tracks
    assert not any(t.artist == 'Water Soundscapes' for t in tracks)


def test_music_fallback_requires_independent_category_validation(monkeypatch):
    calls = fake_music(monkeypatch, [], music_upload_payload())
    monkeypatch.setattr(YouTubeSource, '_music_fallback', _REAL_MUSIC_FALLBACK)
    class Extractor:
        def __init__(self, options):
            assert options['extract_flat']
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, query, **kwargs):
            assert query == 'ytsearch16:rule of nature'
            assert kwargs == {'download': False, 'process': False}
            return {'entries': [
                {'id': 'N3472Q6kvg0', 'title': 'Rules of Nature Extended', 'channel': 'Crimson', 'duration': 266},
                {'id': '00000000002', 'title': 'Rules of Nature Extended Reaction', 'duration': 200},
                {'id': '00000000003', 'title': 'Rules of Nature Extended 1 hour', 'duration': 3600},
            ]}
    monkeypatch.setattr(youtube, 'YoutubeDL', Extractor)
    tracks = YouTubeSource().search('rule of nature')
    assert [t.video_id for t in tracks] == ['N3472Q6kvg0']
    assert calls['song'] == ['N3472Q6kvg0']


def install_resolver(monkeypatch, outcomes):
    calls = []
    class Extractor:
        def __init__(self, options):
            calls.append(options)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            assert download is False
            result = outcomes[len(calls)-1]
            if isinstance(result, Exception):
                raise result
            return result(url) if callable(result) else result
    monkeypatch.setattr(youtube, 'YoutubeDL', Extractor)
    return calls


def resolved(video_id='1lv1h3LWbNk', url='https://sample.googlevideo.com/videoplayback'):
    return {'id': video_id, 'url': url, 'http_headers': {'User-Agent': 'Fixture', 'Referer': 'https://youtube.com/',
            'Cookie': 'private', 'Authorization': 'private', 'X-Not-Allowed': 'private'}}


def test_resolve_fast_path_keeps_webpage_and_audio_stream_contract(monkeypatch):
    calls = install_resolver(monkeypatch, [resolved()])
    stream = YouTubeSource().resolve(Track('1lv1h3LWbNk', 'Paparazzi (Dubstep) (Slowed)'))
    assert isinstance(stream, AudioStream)
    assert stream.headers == {'User-Agent': 'Fixture', 'Referer': 'https://youtube.com/'}
    assert calls[0]['extractor_args']['youtube'] == {'player_client': ['visionos'],
           'player_skip': ['configs', 'initial_data'], 'skip': ['hls', 'dash']}
    assert 'webpage' not in calls[0]['extractor_args']['youtube']['player_skip']
    assert len(calls) == 1


def test_fast_extraction_error_falls_back_to_default_clients(monkeypatch):
    calls = install_resolver(monkeypatch, [OSError('fast unavailable'), resolved()])
    assert YouTubeSource().resolve(Track('1lv1h3LWbNk', 'Paparazzi')).url.startswith('https://')
    assert len(calls) == 2
    assert 'extractor_args' not in calls[1]


@pytest.mark.parametrize('bad', [resolved('5Hb3tJYtK8Q'), resolved(url='http://sample.googlevideo.com/test'),
    resolved(url='https://googlevideo.com.attacker.example/test'), {}, None])
def test_invalid_fast_stream_or_changed_id_triggers_default_fallback(monkeypatch, bad):
    calls = install_resolver(monkeypatch, [bad, resolved()])
    assert YouTubeSource().resolve(Track('1lv1h3LWbNk', 'Paparazzi')).url.endswith('/videoplayback')
    assert len(calls) == 2


def test_both_extraction_failures_preserve_friendly_error(monkeypatch):
    install_resolver(monkeypatch, [OSError('first'), OSError('second')])
    with pytest.raises(SourceError, match='аудиопоток') as error:
        YouTubeSource().resolve(Track('1lv1h3LWbNk', 'Paparazzi'))
    assert isinstance(error.value.__cause__, OSError)


@pytest.mark.parametrize('video_id', ['1lv1h3LWbNk', 'SzHXW_vK93U', '5Hb3tJYtK8Q', 'P_IyRIiNlrY',
                                    'mARxo7WRIr8', 'JIv8AUcuBOE', 'N3472Q6kvg0'])
def test_resolve_preserves_each_paparazzi_and_ost_id(monkeypatch, video_id):
    def extract(url):
        assert url == f'https://www.youtube.com/watch?v={video_id}'
        return resolved(video_id)
    install_resolver(monkeypatch, [extract])
    YouTubeSource().resolve(Track(video_id, 'Recording'))


def audio_format(format_id, language_preference, ext='m4a', abr=128):
    return {'format_id': format_id, 'language_preference': language_preference, 'ext': ext,
            'abr': abr, 'tbr': abr, 'vcodec': 'none', 'acodec': 'opus' if ext == 'webm' else 'mp4a.40.2',
            'protocol': 'https', 'url': f'https://sample.googlevideo.com/{format_id}'}


@pytest.mark.parametrize(('formats', 'expected'), [
    ([audio_format('original', 10, 'webm', 64), audio_format('alternate', -1, 'm4a', 256)], 'original'),
    ([audio_format('default', 5, 'webm', 64), audio_format('alternate', -1, 'm4a', 256)], 'default'),
    ([audio_format('default', 5), audio_format('original', 10, 'webm', 64)], 'original'),
    ([audio_format('low', -1, abr=48), audio_format('medium', -1)], 'medium'),
])
def test_real_ytdlp_selector_prefers_original_then_default_before_container_or_bitrate(formats, expected):
    from yt_dlp import YoutubeDL
    with YoutubeDL({'quiet': True, 'no_warnings': True}) as extractor:
        selector = extractor.build_format_selector(YouTubeSource._audio_format())
        selected = list(selector({'formats': formats, 'has_merged_format': False, 'incomplete_formats': False}))
    assert [item['format_id'] for item in selected] == [expected]


def test_music_ugc_with_plain_matching_title_does_not_need_version_keyword():
    assert YouTubeSource._audio_from_metadata(music_upload_payload(title='КАРТА В БЛОКЕ'),
                                             'N3472Q6kvg0', 'карта в блоке')


def test_official_audio_omv_and_featured_artist_survive_player_canonicalization():
    payload = music_upload_payload(title='Сан Ларан', video_type='MUSIC_VIDEO_TYPE_OMV')
    payload['videoDetails']['author'] = 'Платина & Dora'
    upload = Track('N3472Q6kvg0', 'Платина & дора - Сан Ларан (Official Audio)', 'Платина', 206)
    track = YouTubeSource._audio_from_metadata(payload, 'N3472Q6kvg0', 'сан лоран дора', upload)
    assert track and track.artist == 'Платина & дора'
    assert 'Сан Ларан' in track.title


def test_raw_live_or_clip_evidence_wins_over_canonical_player_title():
    payload = music_upload_payload(title='ЁК', video_type='MUSIC_VIDEO_TYPE_OMV')
    for title, channel in [('Дора — ЁК (Премьера клипа)', 'Дора'),
                           ('Дора — ЁК Official Audio', 'Концерты LIVE')]:
        assert YouTubeSource._audio_from_metadata(payload, 'N3472Q6kvg0', 'Дора ЁК',
                   Track('N3472Q6kvg0', title, channel, 200)) is None


def test_exact_original_title_ranks_above_extended_name_and_unrequested_processing():
    exact = _query_score('карта в блоке', 'КАРТА В БЛОКЕ', 'главный герой')
    imitation = _query_score('карта в блоке', 'карта в блоке, герой', 'главный по рэпу, whole flow')
    processed = _query_score('карта в блоке', 'карта в блоке (фаст-флоу)', 'Artist')
    assert exact > imitation
    assert exact > processed


def test_metadata_from_a_different_id_is_not_used_for_music_validation():
    assert YouTubeSource._audio_from_metadata(music_upload_payload(video_id='ewCPQeAtICk'),
                                              'N3472Q6kvg0', 'rules of nature') is None


def test_reversed_title_artist_credit_is_not_misidentified_as_artist():
    payload = music_upload_payload(title='Сан Ларан - Платина, Дора (speed up)')
    upload = Track('N3472Q6kvg0', payload['videoDetails']['title'], 'spedyx', 174)
    track = YouTubeSource._audio_from_metadata(payload, 'N3472Q6kvg0', 'сан ларан дора', upload)
    assert track and track.artist == 'spedyx'


@pytest.mark.parametrize('title', ['Сан Ларан [второе исполнение] (Морзе, СПб 20.05.2022)',
    'Сан Ларан | Summer Sound | 8.08.2025', 'Сан Ларан (выступление)', 'Rules of Nature visualizer'])
def test_performance_venue_evidence_is_rejected_without_the_literal_live_word(title):
    payload = music_upload_payload(title=title)
    upload = Track('N3472Q6kvg0', title, 'Uploader', 200)
    assert YouTubeSource._audio_from_metadata(payload, 'N3472Q6kvg0', '', upload) is None


def test_studio_artist_and_exact_title_rank_above_query_stuffed_upload_title():
    assert _query_score('Дора ЁК', 'ЁК', 'Дора') > _query_score('Дора ЁК', 'Дора ЁК Official audio', 'Rhymes Music')
    assert _query_score('LONOWN worry ultra slowed', 'worry (ultra slowed)', 'LONOWN, riserayss') > _query_score(
        'LONOWN worry ultra slowed', 'LONOWN worry ultra slowed', 'Unknown uploader')


def test_short_year_vkfest_recording_is_not_treated_as_studio_audio():
    title = 'Дора — ЁК (05.07.26, @VKfest, Санкт-Петербург)'
    assert YouTubeSource._audio_from_metadata(music_upload_payload(title=title), 'N3472Q6kvg0',
            'Дора ЁК', Track('N3472Q6kvg0', title, 'Fan', 180)) is None


# Synthetic storyboard sheets exercise the real decoder and comparison gate,
# without downloading images or relying on a particular upload's ID.
def storyboard_info(video_id='00000000002', frame_count=25, rows=3, columns=3):
    fragments = [{'url': f'https://i.ytimg.com/sb/{video_id}/storyboard/M{i}.jpg'}
                 for i in range((frame_count + rows * columns - 1) // (rows * columns))]
    return {'id': video_id, 'duration': 180, 'formats': [{
        'protocol': 'mhtml', 'width': 120, 'height': 90, 'rows': rows, 'columns': columns,
        'fps': frame_count / 180, 'fragments': fragments}]}


def storyboard_sheet(index, frame_count=25, moving=False, blank=False, rows=3, columns=3):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage, QPainter
    image = QImage(120 * columns, 90 * rows, QImage.Format.Format_RGB32)
    image.fill(QColor('navy') if blank else QColor('black'))
    if not blank:
        painter = QPainter(image)
        for cell in range(rows * columns):
            if index * rows * columns + cell >= frame_count:
                continue  # Unused trailing grid cells are genuinely padding.
            x, y = (cell % columns) * 120, (cell // columns) * 90
            painter.fillRect(x + 14, y + 10, 37, 66, QColor('white'))
            painter.fillRect(x + 57, y + 18, 45, 33, QColor('coral'))
            if moving and cell == 1:
                painter.fillRect(x + 10, y + 10, 90, 70, QColor('lime'))
        painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, 'PNG')
    return bytes(buffer.data())


class StoryboardTransport:
    def __init__(self, images):
        self.images, self.calls, self.read_sizes = images, [], []
    def urlopen(self, url):
        from io import BytesIO
        self.calls.append(url)
        owner = self
        class Response(BytesIO):
            def read(self, size=-1):
                owner.read_sizes.append(size)
                return super().read(size)
        index = int(url.rsplit('/M', 1)[1].split('.')[0])
        return Response(self.images[index])


def test_static_nonempty_storyboards_include_all_valid_end_frames_but_skip_padding():
    info = storyboard_info()
    transport = StoryboardTransport([storyboard_sheet(i) for i in range(3)])
    evidence = YouTubeSource._static_storyboard_evidence(transport, info)
    assert evidence and '25 storyboard-кадрах' in evidence
    assert 'не проверено' in evidence
    assert len(transport.calls) == 3
    assert transport.read_sizes == [2 * 1024 * 1024 + 1] * 3


@pytest.mark.parametrize('kind', ['moving', 'blank', 'corrupt', 'oversized', 'wrong_dimensions'])
def test_storyboards_fail_closed_for_motion_blank_corruption_or_resource_limits(kind):
    images = [storyboard_sheet(i, moving=(kind == 'moving' and i == 1), blank=(kind == 'blank'))
              for i in range(3)]
    if kind == 'corrupt':
        images[1] = b'not an image'
    elif kind == 'oversized':
        images[1] = b'x' * (2 * 1024 * 1024 + 1)
    elif kind == 'wrong_dimensions':
        images[1] = storyboard_sheet(0, rows=1, columns=1)
    assert YouTubeSource._static_storyboard_evidence(StoryboardTransport(images), storyboard_info()) is None


def test_long_storyboard_uses_only_first_middle_and_last_sheets():
    info = storyboard_info(frame_count=88)
    transport = StoryboardTransport([storyboard_sheet(i, frame_count=88) for i in range(10)])
    assert YouTubeSource._static_storyboard_evidence(transport, info)
    assert ['/M0.', '/M5.', '/M9.'] == [url[url.rfind('/M'):url.rfind('/M') + 4] for url in transport.calls]


@pytest.mark.parametrize('mutation', ['missing', 'bad_fps', 'too_few_frames', 'foreign_host', 'other_video'])
def test_storyboard_requires_valid_timing_grid_and_video_bound_urls(mutation):
    info = storyboard_info()
    if mutation == 'missing':
        info['formats'] = []
    elif mutation == 'bad_fps':
        info['formats'][0]['fps'] = 0
    elif mutation == 'too_few_frames':
        info = storyboard_info(frame_count=5)
    else:
        url = 'https://example.com/sb/00000000002/M0.jpg' if mutation == 'foreign_host' else 'https://i.ytimg.com/sb/00000000009/M0.jpg'
        info['formats'][0]['fragments'][0]['url'] = url
    transport = StoryboardTransport([])
    assert YouTubeSource._static_storyboard_evidence(transport, info) is None
    assert not transport.calls


def reference_upload_setup(monkeypatch, *, rows=None, transform=None, visual='25 static frames'):
    calls = []
    def raw(index):
        return {'id': f'{index:011d}', 'title': 'Песня — Артист (без цензуры)',
                'uploader': 'Upload channel', 'duration': 180}
    class Extractor:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, **kwargs):
            calls.append((url, kwargs))
            if url.startswith('ytsearch'):
                return {'entries': rows if rows is not None else [raw(2)]}
            index = int(url.rsplit('=', 1)[1])
            result = dict(raw(index), live_status='not_live', availability='public',
                          categories=['People & Blogs'], view_count=123,
                          formats=[{'acodec': 'aac', 'vcodec': 'none'}])
            return transform(result) if transform else result
    monkeypatch.setattr(youtube, 'YoutubeDL', Extractor)
    monkeypatch.setattr(YouTubeSource, '_static_storyboard_evidence', staticmethod(lambda extractor, info: visual))
    return calls, raw


def test_reference_only_people_and_blogs_preserves_real_category_and_upload_identity(monkeypatch):
    calls, _ = reference_upload_setup(monkeypatch)
    result, = YouTubeSource().recording_candidates(Track('00000000001', 'Песня', 'Артист', 180))
    assert result.track.artist == 'Upload channel'
    assert result.track.title == 'Песня — Артист (без цензуры)'
    assert result.track.view_count == 123
    assert 'People & Blogs' in result.evidence and '25 static frames' in result.evidence
    assert all(call[1]['download'] is False for call in calls)
    assert len(calls) == 2


@pytest.mark.parametrize('change', [
    {'id': '00000000009'}, {'title': 'Другая песня — Артист'}, {'duration': 220},
    {'title': 'Песня — Другой артист'}, {'uploader': 'LIVE archive'},
    {'title': 'Песня — Артист (reaction)'}, {'live_status': 'was_live'},
    {'is_live': True}, {'availability': 'subscriber_only'}, {'categories': ['Entertainment']},
    {'categories': ['Music', 'People & Blogs']}, {'formats': []},
    {'formats': [{'acodec': 'aac', 'vcodec': 'none', 'has_drm': True}]},
])
def test_reference_upload_rechecks_full_metadata_before_visual_gate(monkeypatch, change):
    reference_upload_setup(monkeypatch, transform=lambda info: dict(info, **change))
    assert YouTubeSource().recording_candidates(Track('00000000001', 'Песня', 'Артист', 180)) == []


def test_reference_upload_never_admits_people_and_blogs_without_visual_evidence(monkeypatch):
    reference_upload_setup(monkeypatch, visual=None)
    assert YouTubeSource().recording_candidates(Track('00000000001', 'Песня', 'Артист', 180)) == []


def test_reference_lookup_deduplicates_and_caps_full_metadata_checks(monkeypatch):
    _, raw = reference_upload_setup(monkeypatch)
    rows = [raw(1), raw(2), raw(2)] + [raw(i) for i in range(3, 100)]
    calls, _ = reference_upload_setup(monkeypatch, rows=rows, visual=None)
    assert YouTubeSource().recording_candidates(Track('00000000001', 'Песня', 'Артист', 180)) == []
    assert len(calls) == 5
    assert all('00000000001' not in url for url, _ in calls)


def test_reference_lookup_does_no_network_for_missing_reference_identity(monkeypatch):
    monkeypatch.setattr(youtube, 'YoutubeDL', lambda options: pytest.fail('network is forbidden'))
    source = YouTubeSource()
    assert source.recording_candidates(Track('00000000001', 'Песня', 'YouTube', 180)) == []
    assert source.recording_candidates(Track('00000000001', 'Песня', 'Артист', 0)) == []
    assert source.recording_candidates(Track('00000000001', 'Песня', 'Артист', 180), limit=0) == []


@pytest.mark.parametrize('stage', ['metadata', 'storyboard'])
def test_reference_upload_network_failure_is_reported_as_retryable_not_empty(monkeypatch, stage):
    def unavailable(*args):
        raise OSError('network unavailable')
    reference_upload_setup(monkeypatch, transform=unavailable if stage == 'metadata' else None)
    if stage == 'storyboard':
        monkeypatch.setattr(YouTubeSource, '_static_storyboard_evidence', staticmethod(unavailable))
    with pytest.raises(SourceError, match='Попробуй ещё раз'):
        YouTubeSource().recording_candidates(Track('00000000001', 'Песня', 'Артист', 180))
