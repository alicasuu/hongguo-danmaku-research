"""Offline-only reprocessing of saved OCR observations. No capture/API/database code.

Text is always selected verbatim from an observed OCR string; never synthesized.
Run: python reprocess.py RUN_DIRECTORY --output NEW_DIRECTORY
"""
import argparse
import collections
import csv
import difflib
import hashlib
import html
import json
import math
import os
import statistics
import unicodedata
from pathlib import Path

HOLDOUT = [12, 16, 20, 24, 28, 32, 36, 40, 44, 45]


def norm(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum())


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        new = [i]
        for j, cb in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (ca != cb)))
        row = new
    return row[-1]


def key(o):
    return (o['screenshot'], o['text'], tuple(round(x, 3) for x in o['bbox']))


def chinese(text):
    return any('\u3400' <= c <= '\u9fff' for c in text)


def median(values, default):
    return statistics.median(values) if values else default


def select_text(observations, width, font_height):
    """Weighted observed medoid, using interior/full-size evidence when possible.

    No emoji/Chinese blacklist. Unstable tails lose to recurring observed forms.
    Punctuation is preserved from an actual observation of the selected form.
    """
    interior = [o for o in observations if font_height / 2 < o['bbox'][0]
                and o['bbox'][0] + o['bbox'][2] < width - font_height / 2]
    clean_shape = [o for o in interior if .65 * font_height <= o['bbox'][3] <= 1.35 * font_height]
    eligible = clean_shape or interior or observations
    weights = collections.Counter()
    variants = collections.defaultdict(list)
    for o in eligible:
        n = norm(o['text'])
        if n:
            weights[n] += max(.25, o['confidence'])
            variants[n].append(o)
    # Require position-specific agreement, rather than a blacklist of emoji-like Han characters.
    # Only choose among strings actually observed, so trimming never fabricates a new phrase.
    supports = {}
    for candidate in weights:
        votes = [0] * len(candidate)
        for o in eligible:
            for block in difflib.SequenceMatcher(None, candidate, norm(o['text'])).get_matching_blocks():
                for j in range(block.a, block.a + block.size):
                    votes[j] += 1
        supports[candidate] = [v / len(eligible) for v in votes]
    winner = min(weights, key=lambda s: (sum(weight * distance(s, t) for t, weight in weights.items()), len(s)))
    # Remove an unstable boundary only if the shorter complete form was itself observed.
    # Internal/initial rare Han characters are not globally deleted for failing a vote threshold.
    while len(winner) > 1:
        alternatives = [s for s in weights if len(s) == len(winner) - 1 and
                        ((winner.startswith(s) and supports[winner][-1] < .6) or
                         (winner.endswith(s) and supports[winner][0] < .6))]
        if not alternatives:
            break
        winner = max(alternatives, key=lambda s: weights[s])
    raw = collections.Counter()
    for o in variants[winner]:
        raw[o['text']] += max(.25, o['confidence'])
    text = max(raw, key=lambda s: (raw[s], -len(s)))
    exact = [o for o in variants[winner] if o['text'] == text]
    best = max(exact, key=lambda o: o['confidence'])
    agreement = sum(norm(o['text']) == winner for o in eligible) / len(eligible)
    # Include different frames supporting the same spelling, not just the best one.
    support = list({o['screenshot']: o for o in exact}.values())
    chosen = [support[i] for i in sorted({0, len(support) // 2, len(support) - 1})]
    return dict(text=text, confidence=median([o['confidence'] for o in exact], 0),
                consensus_agreement=agreement, eligible_observations=len(eligible),
                exact_support_frames=len(support), bbox=best['bbox'],
                bbox_screenshot=best['screenshot'], bbox_capture_timestamp=best['capture_timestamp'],
                support=chosen, selection_basis='observed_weighted_edit_medoid',
                low_support=len(support) < 3)


class OfflineTracker:
    def __init__(self, width, font_height):
        self.width = width
        self.height = font_height
        self.tracks = []
        self.rejected = []

    def cost(self, track, o):
        last = track['observations'][-1]
        gap = (o['elapsed_ms'] - last['elapsed_ms']) / 1000
        if not 0 < gap <= 3:
            return None
        x, y, w, h = o['bbox']
        lx, ly, lw, lh = last['bbox']
        lane = median([a['bbox'][1] + a['bbox'][3] / 2 for a in track['observations']], ly + lh / 2)
        if abs(y + h / 2 - lane) > self.height * .65:
            return None
        a, b = norm(last['text']), norm(o['text'])
        if not a or not b:
            return None
        match = difflib.SequenceMatcher(None, a, b).find_longest_match()
        if match.size < min(2, len(a), len(b)) or match.size / min(len(a), len(b)) < .45:
            return None
        # Match common characters, compensating when clipping changes the box's left edge.
        glyph = self.height * .82
        shift = (match.a - match.b) * glyph
        velocity = median(track['velocities'][-8:], -self.width * .12)
        predicted = lx + velocity * gap + shift
        residual = abs(x - predicted)
        tolerance = 18 + 12 * gap
        if residual > tolerance:
            return None
        score = residual / tolerance + .2 * abs(y + h / 2 - lane) / self.height
        score += .15 * (1 - difflib.SequenceMatcher(None, a, b).ratio())
        return score, shift

    def update(self, frame):
        observations = []
        for d in frame['detections']:
            if d['region'] != 'danmaku_candidate' or not chinese(d['text']):
                continue
            o = dict(d, elapsed_ms=frame['capture_elapsed_ms'], capture_timestamp=frame['capture_timestamp'],
                     screenshot=frame['screenshot'])
            # Reject unusually tall text boxes (scene titles leaking into the danmaku lane).
            if not .6 * self.height <= d['bbox'][3] <= 2 * self.height:
                self.rejected.append(dict(o, reason='outside_dominant_font_height'))
                continue
            observations.append(o)
        candidates = []
        for oi, o in enumerate(observations):
            for ti, track in enumerate(self.tracks):
                result = self.cost(track, o)
                if result:
                    candidates.append((*result, ti, oi))
        used_tracks, used_obs = set(), set()
        for score, shift, ti, oi in sorted(candidates):
            if ti in used_tracks or oi in used_obs:
                continue
            used_tracks.add(ti); used_obs.add(oi)
            track, o = self.tracks[ti], observations[oi]
            last = track['observations'][-1]
            gap = (o['elapsed_ms'] - last['elapsed_ms']) / 1000
            dx = o['bbox'][0] - last['bbox'][0] - shift
            if dx < -2:
                track['motion_steps'] += 1
                track['leftward_px'] -= dx
            velocity = dx / gap
            if -self.width * .35 < velocity < -self.width * .04:
                track['velocities'].append(velocity)
            track['observations'].append(o)
        for oi, o in enumerate(observations):
            if oi not in used_obs:
                self.tracks.append(dict(observations=[o], velocities=[], motion_steps=0, leftward_px=0))

    def accepted(self):
        return [t for t in self.tracks if len(t['observations']) >= 3 and t['motion_steps'] >= 2
                and t['leftward_px'] >= 8]

    def stitch(self):
        """Merge only spatially compatible fragments, never deduplicate globally by text."""
        changed = True
        while changed:
            changed = False
            for i, a in enumerate(self.tracks):
                if len(a['observations']) < 2:
                    continue
                for j in range(i + 1, len(self.tracks)):
                    b = self.tracks[j]
                    if len(b['observations']) < 2:
                        continue
                    if self.mergeable(a, b):
                        a['observations'] = sorted(a['observations'] + b['observations'], key=lambda o: o['elapsed_ms'])
                        a['velocities'] += b['velocities']
                        a['motion_steps'] += b['motion_steps']
                        a['leftward_px'] += b['leftward_px']
                        a['merged_fragments'] = a.get('merged_fragments', 1) + b.get('merged_fragments', 1)
                        self.tracks.pop(j)
                        changed = True
                        break
                if changed:
                    break

    def mergeable(self, a, b):
        ao, bo = a['observations'], b['observations']
        if max(ao[0]['elapsed_ms'], bo[0]['elapsed_ms']) - min(ao[-1]['elapsed_ms'], bo[-1]['elapsed_ms']) > 3000:
            return False
        lane = lambda obs: statistics.median(o['bbox'][1] + o['bbox'][3] / 2 for o in obs)
        if abs(lane(ao) - lane(bo)) > self.height * .6:
            return False
        at = norm(select_text(ao, self.width, self.height)['text'])
        bt = norm(select_text(bo, self.width, self.height)['text'])
        common = difflib.SequenceMatcher(None, at, bt).find_longest_match()
        if common.size < min(2, len(at), len(bt)) or (common.size / min(len(at), len(bt)) < .65
                and difflib.SequenceMatcher(None, at, bt).ratio() < .6):
            return False
        anchor = at[common.a:common.a + common.size]
        def points(obs):
            result = []
            for o in obs:
                text = norm(o['text'])
                index = text.find(anchor)
                if index >= 0 and 2 < o['bbox'][0] < self.width - self.height:
                    result.append((o['elapsed_ms'] / 1000, o['bbox'][0] + index * self.height * .82))
            return result
        ap, bp = points(ao), points(bo)
        if not ap or not bp or max(len(ap), len(bp)) < 2:
            return False
        velocity = median(a['velocities'] + b['velocities'], -self.width * .12)
        ai = median([x - velocity * t for t, x in ap], 0)
        bi = median([x - velocity * t for t, x in bp], 0)
        if abs(ai - bi) > self.height * 1.25:
            return False
        # Simultaneous, disjoint same-text boxes are distinct events, even when nearby.
        times = {o['elapsed_ms']: o for o in ao}
        for o in bo:
            if o['elapsed_ms'] in times:
                other = times[o['elapsed_ms']]
                x, _, w, _ = o['bbox']; ox, _, ow, _ = other['bbox']
                # Complementary OCR fragments can be disjoint parts of ONE phrase.
                # Two simultaneous copies of the same text cannot be the same event.
                if norm(o['text']) == norm(other['text']) and min(x + w, ox + ow) < max(x, ox):
                    return False
        return True


def original_mapping(run):
    lookup = collections.defaultdict(set)
    old = json.loads((run / 'tracks.json').read_text())
    accepted = [t for t in old if len(t['observations']) >= 3 and t['motion_steps'] >= 2 and t['leftward_px'] >= 8]
    for i, track in enumerate(accepted, 1):
        for o in track['observations']:
            lookup[key(o)].add(i)
    return lookup


def write_json(path, obj):
    with path.open('x', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def audit_html(run, output, records, originals):
    rows = []
    def esc(x):
        return html.escape(str(x))
    for record in records:
        original = '<br>'.join(f'#{i}: {esc(originals[i-1]["text"])} '
                              f'(Vision {originals[i-1]["confidence"]:.2f})' for i in record['original_record_indices']) or 'Recovered track — absent from original export'
        pictures = []
        for o in record['support']:
            image = os.path.relpath(run / o['screenshot'], output)
            x, y, w, h = o['bbox']
            left, top = max(0, x - 8), max(0, y - 6)
            pictures.append(f'<a href="{esc(image)}"><div class="crop" style="width:{min(w+24,486-left):.1f}px;height:{h+12:.1f}px"><img src="{esc(image)}" style="left:{-left:.1f}px;top:{-top:.1f}px"></div></a><small>{esc(o["screenshot"])} · {o["elapsed_ms"]} ms since capture start</small>')
        rows.append(f'<tr><td>{record["observation_group"]}<br>{record["capture_elapsed_ms"]}–{record["last_capture_elapsed_ms"]} ms</td><td>{original}</td><td><b>{esc(record["text"])}</b><br>Vision median: {record["confidence"]:.2f}<br>Spelling agreement: {record["consensus_agreement"]:.0%}<br>Exact supporting frames: {record["exact_support_frames"]}<br>{"LOW SUPPORT" if record["low_support"] else ""}</td><td>{"".join(pictures)}</td></tr>')
    page = '''<!doctype html><meta charset="utf-8"><title>Saved-frame Hongguo OCR audit</title>
<style>body{font:15px system-ui;margin:24px;color:#18212b}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #ccd2d8;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#f1f3f5}small{display:block;margin:4px 0 12px}.crop{position:relative;overflow:hidden;background:#222}.crop img{position:absolute;width:486px;height:1055px}h1{font-size:24px}</style>
<h1>Hongguo saved-frame OCR: original vs consensus</h1><p>Only 178 saved frames. Local observation groups are not native message IDs. Timing is capture elapsed time, not playback offsets. Text is selected verbatim from supporting OCR observations; Vision confidence and spelling agreement are not calibrated accuracy. Click a crop for its full frame. Repeated text in separate trajectories stays separate.</p>
<table><thead><tr><th>Local group / capture interval</th><th>Original OCR</th><th>Consensus OCR / confidence</th><th>Supporting frames</th></tr></thead><tbody>'''
    (output / 'audit.html').write_text(page + ''.join(rows) + '</tbody></table>', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run, output = args.run.resolve(), args.output.resolve()
    if output.exists():
        parser.error('Output already exists; choose a new directory to preserve all prior results')
    frames = [json.loads(s) for s in (run / 'frame_ocr.jsonl').read_text().splitlines()]
    if len(frames) != 178:
        parser.error('This evaluation expects the existing 178-frame pilot')
    for f in frames:
        if not (run / f['screenshot']).is_file():
            parser.error('Missing saved screenshot')
    height = statistics.median(d['bbox'][3] for f in frames for d in f['detections'] if chinese(d['text']))
    tracker = OfflineTracker(frames[0]['width'], height)
    for f in frames:
        tracker.update(f)
    tracker.stitch()
    old = json.loads((run / 'danmaku_live.json').read_text())['records']
    lookup = original_mapping(run)
    records = []
    for index, t in enumerate(tracker.accepted(), 1):
        obs = t['observations']
        selected = select_text(obs, tracker.width, height)
        original_ids = sorted(set().union(*(lookup[key(o)] for o in obs)))
        boundary = obs[0]['elapsed_ms'] == 0 or obs[-1]['elapsed_ms'] == frames[-1]['capture_elapsed_ms']
        status = 'candidate_only' if selected['low_support'] and not original_ids and not boundary else 'retained'
        record = dict(observation_group=index, **selected, original_record_indices=original_ids,
                      capture_timestamp=obs[0]['capture_timestamp'], last_capture_timestamp=obs[-1]['capture_timestamp'],
                      capture_elapsed_ms=obs[0]['elapsed_ms'], last_capture_elapsed_ms=obs[-1]['elapsed_ms'],
                      observations=len(obs), median_velocity_px_s=median(t['velocities'], None),
                      merged_fragments=t.get('merged_fragments', 1),
                      raw_text_variants=list(dict.fromkeys(o['text'] for o in obs)),
                      episode_id=None, native_message_id=None, posting_time=None, platform_offset_time_ms=None,
                      estimated_playback_offset_ms=None, source='quicktime_saved_frame_ocr',
                      timing_basis='unsynchronized_capture_elapsed', coverage='partial_screen_visible',
                      boundary_event=boundary, export_status=status,
                      review_required=selected['low_support'] or selected['consensus_agreement'] < .6 or boundary)
        records.append(record)
    hashes = {name: hashlib.sha256((run / name).read_bytes()).hexdigest() for name in
              ['frame_ocr.jsonl', 'tracks.json', 'danmaku_live.json', 'danmaku_live.csv', 'manual_audit_first10.json']}
    retained = [r for r in records if r['export_status'] == 'retained']
    candidates = [r for r in records if r['export_status'] != 'retained']
    meta = dict(source_run=str(run), input_sha256=hashes, source_frames=len(frames),
                original_tracks=len(old), new_tracks=len(records), retained_tracks=len(retained),
                withheld_candidates=len(candidates), distinct_texts=len({r['text'] for r in retained}),
                median_font_height=height, frozen_holdout_original_indices=HOLDOUT,
                method='geometry prediction + one-to-one assignment + observed text medoid',
                ground_truth_used_for_selection=False, exact_native_message_count_unknown=True,
                code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'danmaku_reprocessed.json', dict(metadata=meta, records=retained))
    write_json(output / 'review_candidates.json', candidates)
    write_json(output / 'tracking_evidence.json', dict(tracks=tracker.tracks, rejected=tracker.rejected))
    with (output / 'danmaku_reprocessed.csv').open('x', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(retained[0]) if retained else ['text'])
        writer.writeheader()
        for record in retained:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in record.items()})
    audit_html(run, output, records, old)
    print(json.dumps(meta, ensure_ascii=False))
    for r in records:
        print(r['observation_group'], r['original_record_indices'], r['capture_elapsed_ms'], r['last_capture_elapsed_ms'],
              r['text'], r['exact_support_frames'], round(r['consensus_agreement'], 2))


if __name__ == '__main__':
    main()
