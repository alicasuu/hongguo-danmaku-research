"""Screen-visible OCR observations only; no native IDs or platform timestamps.

Run from the project root with .venv/bin/python experiments/quicktime_ocr/collect.py.
Requires the compiled sibling vision_ocr worker and macOS screen capture permission.
"""
import argparse
import csv
import ctypes as C
import datetime as dt
import difflib
import json
import plistlib
import resource
import select
import subprocess
import time
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROI = [0, 0.115, 1, 0.24]


def quicktime_window():
    cg = C.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg.CGPreflightScreenCaptureAccess.restype = C.c_bool
    if not cg.CGPreflightScreenCaptureAccess():
        raise RuntimeError('Screen Recording permission unavailable for this process')
    cg.CGWindowListCopyWindowInfo.argtypes = [C.c_uint32, C.c_uint32]
    cg.CGWindowListCopyWindowInfo.restype = C.c_void_p
    cf.CFPropertyListCreateData.argtypes = [C.c_void_p, C.c_void_p, C.c_long, C.c_ulong, C.c_void_p]
    cf.CFPropertyListCreateData.restype = C.c_void_p
    cf.CFDataGetLength.argtypes = [C.c_void_p]
    cf.CFDataGetLength.restype = C.c_long
    cf.CFDataGetBytePtr.argtypes = [C.c_void_p]
    cf.CFDataGetBytePtr.restype = C.c_void_p
    cf.CFRelease.argtypes = [C.c_void_p]
    windows = cg.CGWindowListCopyWindowInfo(17, 0)
    if not windows:
        raise RuntimeError('WindowServer unavailable')
    data = None
    try:
        data = cf.CFPropertyListCreateData(None, windows, 200, 0, None)
        if not data:
            raise RuntimeError('Cannot read window metadata')
        rows = plistlib.loads(C.string_at(cf.CFDataGetBytePtr(data), cf.CFDataGetLength(data)))
    finally:
        if data:
            cf.CFRelease(data)
        cf.CFRelease(windows)
    matches = [r for r in rows if r.get('kCGWindowOwnerName') == 'QuickTime Player'
               and r.get('kCGWindowLayer') == 0
               and r.get('kCGWindowName') in ('Movie Recording', '影片录制', '影片錄製')]
    if len(matches) != 1:
        raise RuntimeError(f'Expected one QuickTime Movie Recording window; found {len(matches)}')
    return matches[0]


class Vision:
    def __init__(self):
        self.process = subprocess.Popen([str(BASE / 'vision_ocr')], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True, bufsize=1)

    def read(self, image, annotated=None, roi=ROI):
        payload = dict(image=str(image), roi=roi, restrictROI=True)
        if annotated:
            payload['annotated'] = str(annotated)
        self.process.stdin.write(json.dumps(payload) + '\n')
        self.process.stdin.flush()
        if not select.select([self.process.stdout], [], [], 30)[0]:
            raise RuntimeError('Apple Vision timed out')
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('Apple Vision worker exited')
        result = json.loads(line)
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum())


def similar(a, b):
    a, b = normalized(a), normalized(b)
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))
                              or difflib.SequenceMatcher(None, a, b).ratio() >= .78)


class Tracker:
    def __init__(self):
        self.tracks = []

    def update(self, detections, elapsed_ms, capture_time, frame, width):
        used = set()
        for d in detections:
            if d['region'] != 'danmaku_candidate' or not any('\u3400' <= c <= '\u9fff' for c in d['text']):
                continue
            x, y, w, h = d['bbox']
            choices = []
            for index, track in enumerate(self.tracks):
                if index in used:
                    continue
                last = track['observations'][-1]
                gap = (elapsed_ms - last['elapsed_ms']) / 1000
                lx, ly, lw, lh = last['bbox']
                if (0 < gap <= 1.5 and abs(y + h / 2 - ly - lh / 2) <= max(5, h * .55)
                        and -width * .9 * gap - 10 <= x - lx <= 8
                        and similar(d['text'], last['text'])):
                    choices.append((abs(x - lx), index))
            if choices:
                _, index = min(choices)
                track = self.tracks[index]
            else:
                index = len(self.tracks)
                track = {'observations': [], 'motion_steps': 0, 'leftward_px': 0.0}
                self.tracks.append(track)
            used.add(index)
            if track['observations']:
                dx = track['observations'][-1]['bbox'][0] - x
                if dx >= 2:
                    track['motion_steps'] += 1
                    track['leftward_px'] += dx
            track['observations'].append(dict(d, elapsed_ms=elapsed_ms, capture_timestamp=capture_time,
                                             screenshot=frame, edge_clipped=x <= 2 or x + w >= width - 2))

    def records(self, episode_id, anchor):
        results = []
        for track in self.tracks:
            obs = track['observations']
            if len(obs) < 3 or track['motion_steps'] < 2 or track['leftward_px'] < 8:
                continue
            first = obs[0]
            best = max(obs, key=lambda o: (not o['edge_clipped'], len(normalized(o['text'])), o['confidence']))
            results.append(dict(text=best['text'], episode_id=episode_id, native_message_id=None,
                                platform_offset_time_ms=None, posting_time=None,
                                capture_timestamp=first['capture_timestamp'],
                                last_capture_timestamp=obs[-1]['capture_timestamp'],
                                capture_elapsed_ms=first['elapsed_ms'],
                                estimated_playback_offset_ms=None if anchor is None else round(anchor + first['elapsed_ms']),
                                timing_basis='unsynchronized_capture_elapsed' if anchor is None else 'user_anchor_assuming_continuous_1x_playback',
                                confidence=best['confidence'], bbox=best['bbox'],
                                bbox_screenshot=best['screenshot'], bbox_capture_timestamp=best['capture_timestamp'],
                                observations=len(obs), text_variants=list(dict.fromkeys(o['text'] for o in obs)),
                                edge_clipped=best['edge_clipped'], source='quicktime_screen_ocr',
                                coverage='partial_screen_visible_motion_confirmed'))
        return results


def export(folder, tracker, args, stats):
    records = tracker.records(args.episode_id, args.playback_start_ms)
    data = dict(metadata=stats, records=records)
    # Only this newly created run directory is updated. No production files or SQLite.
    for name, payload in [('danmaku_live.json', data), ('tracks.json', tracker.tracks)]:
        target = folder / name
        temp = folder / (name + '.tmp')
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(target)
    fields = list(records[0]) if records else ['text', 'episode_id', 'capture_timestamp',
             'capture_elapsed_ms', 'estimated_playback_offset_ms', 'confidence', 'bbox']
    with (folder / 'danmaku_live.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--fps', type=float, default=3)
    parser.add_argument('--episode-id', help='User-confirmed episode ID; never inferred from the screen')
    parser.add_argument('--playback-start-ms', type=float, help='User-confirmed clock at first capture; omit if unknown')
    parser.add_argument('--roi', type=float, nargs=4, default=ROI, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'))
    args = parser.parse_args()
    if not 0 < args.seconds <= 60 or not 0 < args.fps <= 5:
        parser.error('Prototype is limited to 60 seconds and at most 5 FPS')
    l, t, r, b = args.roi
    if not 0 <= l < r <= 1 or not 0 <= t < b <= 1:
        parser.error('ROI must be normalized left/top/right/bottom coordinates')
    if args.playback_start_ms is not None and args.playback_start_ms < 0:
        parser.error('Playback anchor must be nonnegative')
    window = quicktime_window()
    folder = BASE / 'runs' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    (folder / 'frames').mkdir(parents=True, exist_ok=False)
    worker = Vision()
    tracker = Tracker()
    stats = dict(source='screen_ocr_not_native_api', coverage='partial', roi=args.roi,
                 target_fps=args.fps, window_id=window['kCGWindowNumber'], frames=0,
                 ocr_ms=[], capture_ms=[], status='running', performance_includes_ocr=True)
    start = time.monotonic()
    first_capture = None
    dimensions = None
    print('Capturing QuickTime; keep window size, episode and playback speed unchanged. Ctrl-C stops.', flush=True)
    try:
        with (folder / 'frame_ocr.jsonl').open('x', encoding='utf-8') as raw:
            while time.monotonic() - start < args.seconds:
                frame_start = time.monotonic()
                if first_capture is None:
                    first_capture = frame_start
                capture_time = dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds')
                elapsed = round((frame_start - first_capture) * 1000)
                image = folder / 'frames' / f'{stats["frames"]:06d}.png'
                subprocess.run(['/usr/sbin/screencapture', '-x', '-o', '-l', str(window['kCGWindowNumber']), str(image)],
                               check=True, timeout=10, capture_output=True)
                stats['capture_ms'].append(round((time.monotonic() - frame_start) * 1000, 1))
                annotation = folder / 'debug_annotated.png' if stats['frames'] == 0 else None
                result = worker.read(image, annotation, args.roi)
                size = (result['width'], result['height'])
                if dimensions is not None and size != dimensions:
                    raise RuntimeError('Window resized: stopped to avoid invalid tracking')
                dimensions = size
                stats['ocr_ms'].append(result['processing_ms'])
                evidence = dict(capture_timestamp=capture_time, capture_elapsed_ms=elapsed,
                                screenshot=str(image.relative_to(folder)), **result)
                raw.write(json.dumps(evidence, ensure_ascii=False) + '\n'); raw.flush()
                tracker.update(result['detections'], elapsed, capture_time, str(image.relative_to(folder)), size[0])
                stats['frames'] += 1
                export(folder, tracker, args, stats)
                time.sleep(max(0, 1 / args.fps - (time.monotonic() - frame_start)))
        stats['status'] = 'finished'
    except KeyboardInterrupt:
        stats['status'] = 'user_stopped'
    except Exception as error:
        stats['status'] = 'failed'
        stats['error'] = str(error)
    finally:
        worker.close()
        wall = time.monotonic() - start
        stats['wall_seconds'] = wall
        stats['actual_fps'] = stats['frames'] / wall
        usage = [resource.getrusage(k) for k in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)]
        stats['process_cpu_seconds'] = sum(x.ru_utime + x.ru_stime for x in usage)
        stats['cpu_percent_one_core'] = 100 * stats['process_cpu_seconds'] / wall
        stats['cpu_scope'] = 'Python and child processes; excludes macOS service processes'
        export(folder, tracker, args, stats)
    print(json.dumps(dict(output=str(folder), unique_tracks=len(tracker.records(args.episode_id, args.playback_start_ms)), **stats), ensure_ascii=False))
    return 1 if stats['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
