from dataclasses import FrozenInstanceError

import pytest

from musicdesk.models import Track
from musicdesk.recording_versions import RecordingVersion, VersionFinder, work_key
from musicdesk.youtube import SourceError


def track(index=1, title='Песня', artist='Слава КПСС', duration=180):
    return Track(f'{index:011d}', title, artist, duration)


class FakeSource:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []

    def search(self, query, limit=40, order='relevance'):
        self.calls.append((query, limit, order))
        result = self.rows(query) if callable(self.rows) else self.rows
        if isinstance(result, Exception):
            raise result
        return result


def find(rows, reference=None, limit=12):
    return VersionFinder(FakeSource(rows)).find(reference or track(), limit)


def test_dataclass_matches_integration_contract_and_is_immutable():
    version = RecordingVersion(track(2), 'Другая загрузка', 'Метаданные')
    assert version.verified_uncensored is False
    with pytest.raises(FrozenInstanceError):
        version.label = 'Changed'


def test_current_id_and_duplicates_are_excluded_but_other_uploads_are_kept():
    current, candidate, duplicate_master = track(), track(2), track(3)
    versions = find([current, candidate, candidate, duplicate_master])
    assert [version.track.video_id for version in versions] == [candidate.video_id, duplicate_master.video_id]
    assert all(version.label == 'Другая загрузка' for version in versions)
    assert all(version.verified_uncensored is False for version in versions)


def test_title_uncensored_claim_is_disclosed_and_never_verified():
    version, = find([track(2, 'Песня (Без цензуры)')])
    assert 'заявлено' in version.label
    assert 'заявлено в названии' in version.evidence
    assert 'не проверены' in version.evidence
    assert version.verified_uncensored is False


@pytest.mark.parametrize('declaration', ['uncensored', 'uncut', 'EXPLICIT', 'без цензуры'])
def test_multiple_uncensored_declarations_remain_unverified(declaration):
    version, = find([track(2, f'Песня ({declaration})')])
    assert 'заявлено в названии' in version.evidence
    assert not version.verified_uncensored


def test_original_claim_does_not_promise_original_or_uncensored_content():
    version, = find([track(2, 'Песня (Original Version)')])
    assert version.label == '«Оригинал» — заявлено'
    assert '«оригинал»: заявлено в названии' in version.evidence
    assert not version.verified_uncensored


def test_clean_version_is_labeled_without_verifying_its_content():
    version, = find([track(2, 'Песня (Clean Version)')])
    assert version.label == 'Clean — заявлено'
    assert not version.verified_uncensored


def test_only_real_source_searches_are_used_with_finite_budgets():
    source = FakeSource([])
    assert VersionFinder(source).find(track()) == []
    assert [query for query, _, _ in source.calls] == [
        'Слава КПСС Песня', 'Слава КПСС Песня uncensored',
        'Слава КПСС Песня без цензуры', 'Слава КПСС Песня original']
    assert all(limit == 36 and order == 'relevance' for _, limit, order in source.calls)


def test_claim_does_not_increase_identity_or_duration_rank():
    source = FakeSource([track(2, 'Песня (uncensored)', duration=188), track(3, duration=180)])
    versions = VersionFinder(source).find(track())
    assert versions[0].track.video_id == track(3).video_id


def test_later_title_evidence_for_same_id_is_not_lost():
    def rows(query):
        return [track(2, 'Песня (uncensored)')] if 'uncensored' in query else [track(2)]
    version, = VersionFinder(FakeSource(rows)).find(track())
    assert 'заявлено в названии' in version.evidence


@pytest.mark.parametrize(('title', 'duration', 'label'), [
    ('Песня (Remix)', 200, 'REMIX'), ('Песня (Mashup)', 210, 'MASHUP'),
    ('Песня (Slowed)', 230, 'SLOWED'), ('Песня (Ultra Slowed)', 270, 'ULTRA SLOWED'),
    ('Песня (Super Slowed)', 250, 'SUPER SLOWED'), ('Песня (Sped Up)', 140, 'SPED UP'),
    ('Песня (Nightcore)', 145, 'SPED UP'), ('Песня (Instrumental)', 181, 'INSTRUMENTAL'),
    ('Песня (Extended)', 250, 'EXTENDED'), ('Песня (Remastered)', 181, 'REMASTER'),
])
def test_processing_versions_have_separate_labels(title, duration, label):
    version, = find([track(2, title, duration=duration)])
    assert version.label == label
    assert version.track.title == title
    assert not version.verified_uncensored


def test_same_recording_family_is_ranked_before_processing_variants():
    versions = find([track(2, 'Песня (Remix)', duration=200), track(3), track(4, 'Песня (Slowed)', duration=230)])
    assert versions[0].track.video_id == track(3).video_id
    assert {version.label for version in versions} == {'Другая загрузка', 'REMIX', 'SLOWED'}


def test_compound_processing_is_not_collapsed():
    version, = find([track(2, 'Песня (Remix Slowed)', duration=240)])
    assert version.label == 'SLOWED · REMIX'


def test_processed_reference_does_not_turn_unprocessed_original_into_same_processing():
    versions = find([track(2), track(3, 'Песня (Slowed)', duration=231)],
                    reference=track(1, 'Песня (Slowed)', duration=230))
    assert versions[0].track.video_id == track(3).video_id
    assert {version.label for version in versions} == {'Другая загрузка', 'SLOWED'}


@pytest.mark.parametrize(('title', 'duration'), [
    ('Песня Live', 180), ('Песня (концерт)', 180), ('Песня (Премьера клипа)', 180),
    ('Песня (Official Music Video)', 180), ('Песня reaction', 180),
    ('Песня | Разбор трека', 180), ('Песня 1 час', 3600), ('Песня (1 hour loop)', 180),
    ('Песня (05.07.26, @VKfest)', 180),
])
def test_forbidden_content_cannot_enter_from_an_overbroad_source(title, duration):
    assert find([track(2, title, duration=duration)]) == []


def test_other_composition_or_performer_is_rejected_even_when_duration_is_identical():
    assert find([track(2, 'Другая песня'), track(3, artist='Другой артист'),
                 track(4, 'Песня (cover)', artist='Другой артист')]) == []


def test_explicit_delimited_performer_credit_can_establish_a_reupload_match():
    candidate = track(2, 'Слава КПСС — Песня (uncensored)', artist='Music Archive')
    version, = find([candidate])
    assert version.track == candidate
    assert 'исполнитель указан в заголовке' in version.evidence
    assert not version.verified_uncensored


def test_artist_mentioned_somewhere_in_title_is_not_enough_for_a_reupload():
    assert find([track(2, 'Песня о Славе КПСС', artist='Archive')]) == []


def test_featured_artists_and_topic_suffix_do_not_erase_matching_performer():
    candidate = track(2, artist='Слава КПСС, Замай - Topic')
    assert len(find([candidate])) == 1


@pytest.mark.parametrize('duration', [0, 1201, 25, 3600])
def test_unknown_long_or_unrelated_duration_is_rejected(duration):
    assert find([track(2, duration=duration)]) == []


def test_duration_boundary_for_same_processing():
    assert len(find([track(2, duration=194)])) == 1
    assert find([track(2, duration=195)]) == []


def test_labeled_processing_is_still_subject_to_duration_bounds():
    assert find([track(2, 'Песня (Slowed)', duration=361)]) == []
    assert find([track(2, 'Песня (Remix)', duration=320)]) == []


def test_limit_is_respected_without_title_deduplication_or_catalog_download():
    source = FakeSource([track(i) for i in range(2, 300)])
    versions = VersionFinder(source).find(track(), limit=2)
    assert len(versions) == 2
    assert len(source.calls) == 4
    assert all(limit == 24 for _, limit, _ in source.calls)


@pytest.mark.parametrize('limit', [0, -1])
def test_nonpositive_limit_avoids_network(limit):
    source = FakeSource([])
    assert VersionFinder(source).find(track(), limit) == []
    assert not source.calls


@pytest.mark.parametrize('limit', [True, 1.2, '12'])
def test_invalid_limit_is_rejected(limit):
    with pytest.raises(ValueError, match='limit'):
        VersionFinder(FakeSource()).find(track(), limit)


@pytest.mark.parametrize(('artist', 'duration'), [('YouTube', 180), ('', 180), ('Unknown', 180), ('Artist', 0)])
def test_missing_identity_or_duration_does_not_produce_guessed_alternatives(artist, duration):
    source = FakeSource([track(2)])
    assert VersionFinder(source).find(track(artist=artist, duration=duration)) == []
    assert not source.calls


def test_all_source_failures_produce_a_meaningful_error():
    source = FakeSource(SourceError('offline'))
    with pytest.raises(SourceError, match='источник недоступен'):
        VersionFinder(source).find(track())


def test_partial_search_failure_preserves_verified_identity_matches():
    source = FakeSource(lambda query: [track(2)] if query.endswith('Песня') else SourceError('offline'))
    version, = VersionFinder(source).find(track())
    assert version.track.video_id == track(2).video_id


def test_unexpected_programming_errors_are_not_silently_swallowed():
    with pytest.raises(RuntimeError):
        VersionFinder(FakeSource(RuntimeError('bug'))).find(track())


def test_work_key_normalizes_service_metadata_without_erasing_processing():
    reference = track(title='ЁК', artist='Дора')
    decorated = track(2, 'ДОРА — ЁК [Official Audio]', 'Дора - Topic')
    assert work_key(reference) == work_key(decorated)
    assert work_key(track(3, 'ЁК (uncensored)', 'Дора')) == work_key(reference)
    assert work_key(track(4, 'ЁК (Remix)', 'Дора')) != work_key(reference)
    assert work_key(track(5, 'ЁК (Ultra Slowed)', 'Дора')) != work_key(reference)
    assert work_key(track(6, 'ЁК (Remix by One)', 'Дора')) != work_key(track(7, 'ЁК (Remix by Two)', 'Дора'))


def test_work_key_retains_meaningful_words_in_original_song_names():
    assert 'original sin' in work_key(track(title='Original Sin'))
    assert 'remix of my life' in work_key(track(title='Remix of My Life'))


def test_no_audio_resolution_or_content_confirmation_is_ever_invoked():
    class Source(FakeSource):
        def resolve(self, *args):
            pytest.fail('finder must never resolve or download streams')
    versions = VersionFinder(Source([track(2, 'Песня (uncensored)')])).find(track())
    assert len(versions) == 1
    assert all(version.verified_uncensored is False for version in versions)


def test_original_inside_a_song_name_is_not_a_master_claim():
    reference = track(title='Original Sin')
    version, = find([track(2, 'Original Sin')], reference)
    assert version.label == 'Другая загрузка'
    assert 'заявлено в названии' not in version.evidence


def test_uncensored_as_the_song_name_alone_is_not_a_claim():
    version, = find([track(2, 'Uncensored')], track(title='Uncensored'))
    assert version.label == 'Другая загрузка'
    assert not version.verified_uncensored


def test_service_and_archive_year_annotations_do_not_hide_a_matching_recording():
    versions = find([track(2, 'Песня [Official Audio, 2014]'), track(3, 'Песня (2014)'),
                     track(4, 'Песня (Original 2014)')])
    assert len(versions) == 3
    assert 'заявлено в названии' in versions[2].evidence
    assert work_key(track(2, 'Песня [Official Audio, 2014]')) == work_key(track())


def test_meaningful_title_year_and_remastered_release_are_not_erased_from_key():
    assert '1984' in work_key(track(title='1984'))
    assert work_key(track(title='Песня (Remastered 2024)')) != work_key(track())


@pytest.mark.parametrize('name', ['Песня (Original Sin)', 'Песня (Uncensored Love)'])
def test_meaningful_parenthetical_titles_are_not_marketing_claims(name):
    version, = find([track(2, name)], track(title=name))
    assert version.label == 'Другая загрузка'
    assert 'заявлено в названии' not in version.evidence


def test_uncensored_claim_combined_with_remix_keeps_both_distinct_disclosures():
    version, = find([track(2, 'Песня (Remix, Uncensored)', duration=200)])
    assert version.label == 'REMIX · «Без цензуры» — заявлено'
    assert 'заявлено в названии' in version.evidence
    assert not version.verified_uncensored
