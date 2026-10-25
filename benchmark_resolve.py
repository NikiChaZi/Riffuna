r"""Opt-in resolve benchmark. Prints timings and byte-range proofs, never stream URLs.

Run: .venv\Scripts\python.exe benchmark_resolve.py --modes default visionos android_vr
Use --modes application after changing YouTubeSource.resolve.
"""
from __future__ import annotations

import argparse
import json
import re
from time import perf_counter

import requests
from yt_dlp import YoutubeDL

from musicdesk.models import Track
from musicdesk.youtube import YouTubeSource

TRACKS = [
    Track('1ySTQ_e0SmU', 'Дора — ЁК'),
    Track('lCKU-tI-upI', 'worry (ultra slowed)'),
    Track('1lv1h3LWbNk', 'Paparazzi (Dubstep) (Slowed)'),
    Track('N3472Q6kvg0', 'Rules of Nature Extended — Crimson'),
]


def range_probe(url, headers, start=0):
    started = perf_counter()
    probe_headers = {**headers, 'Range': f'bytes={start}-{start + 1023}', 'Accept-Encoding': 'identity'}
    with requests.get(url, headers=probe_headers, stream=True, timeout=(6, 12), allow_redirects=True) as response:
        content = response.raw.read(1024)
        content_range = response.headers.get('Content-Range', '')
        return {'status': response.status_code, 'bytes': len(content),
                'content_range': content_range, 'content_type': response.headers.get('Content-Type', ''),
                'ok': response.status_code == 206 and len(content) == 1024
                      and content_range.startswith(f'bytes {start}-{start + 1023}/'),
                'seconds': round(perf_counter() - started, 3)}


def measure(track, mode):
    started = perf_counter()
    record = {'id': track.video_id, 'mode': mode}
    try:
        if mode == 'application':
            stream = YouTubeSource().resolve(track)
            url, headers = stream.url, stream.headers
        else:
            options = YouTubeSource._options(format='bestaudio[ext=m4a]/bestaudio/best')
            if mode != 'default':
                options['extractor_args'] = {'youtube': {
                    'player_client': [mode.removesuffix('_manifests').removesuffix('_webpage')],
                    'player_skip': ['configs', 'initial_data'] if '_webpage' in mode else ['webpage', 'configs', 'initial_data'],
                    **({} if mode.endswith('_manifests') else {'skip': ['hls', 'dash']}),
                }}
            with YoutubeDL(options) as extractor:
                result = extractor.extract_info(track.url, download=False)
            url = result['url']
            headers = {k: v for k, v in (result.get('http_headers') or {}).items()
                       if k.lower() in {'user-agent', 'accept', 'accept-language', 'referer', 'origin'}}
            record.update({'format': result.get('format_id'), 'ext': result.get('ext'),
                           'protocol': result.get('protocol'), 'audio_codec': result.get('acodec')})
        record['resolve_seconds'] = round(perf_counter() - started, 3)
        record['range_start'] = range_probe(url, headers)
        record['range_seek'] = range_probe(url, headers, start=4096)
    except Exception as exc:
        # Exceptions from extractors/requests can contain signed URLs.
        record.update({'error_type': type(exc).__name__, 'elapsed_seconds': round(perf_counter() - started, 3), 'reason': re.sub(r'https?://[^\s]+', '<url>', str(exc))[:250]})
    print(json.dumps(record), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modes', nargs='+', choices=['default', 'visionos', 'visionos_manifests', 'android_vr', 'tv_samsung', 'tv_samsung_manifests', 'visionos_webpage', 'visionos_webpage_manifests', 'tv_samsung_webpage', 'application'],
                        default=['default', 'visionos', 'android_vr'])
    parser.add_argument('--video-id', choices=[track.video_id for track in TRACKS])
    parser.add_argument('--rounds', type=int, default=1)
    args = parser.parse_args()
    for _ in range(args.rounds):
        for track in TRACKS:
            if args.video_id and track.video_id != args.video_id:
                continue
            for mode in args.modes:
                measure(track, mode)


if __name__ == '__main__':
    main()
