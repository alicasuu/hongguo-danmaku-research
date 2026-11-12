"""Evaluate a frozen offline output against separately recorded manual labels."""
import argparse
import hashlib
import json
from pathlib import Path
from reprocess import distance, norm, write_json


def evaluate(items, old, new):
    rows = []
    for item in items:
        i = item.get('original_record_index', item.get('record_index'))
        reference = item['manual_reference_text']
        matches = [r for r in new if i in r['original_record_indices']]
        if len(matches) != 1:
            raise ValueError(f'Ambiguous/missing mapping for original #{i}')
        record = matches[0]
        before, after = old[i-1]['text'], record['text']
        rows.append(dict(original_index=i, observation_group=record['observation_group'], reference=reference,
                         before=before, after=after, before_edits=distance(norm(reference), norm(before)),
                         after_edits=distance(norm(reference), norm(after)), reference_chars=len(norm(reference))))
    chars = sum(r['reference_chars'] for r in rows)
    result = dict(paired_original_records=len(rows), distinct_new_events=len({r['observation_group'] for r in rows}),
                  reference_characters=chars, rows=rows)
    for name in ['before', 'after']:
        edits = sum(r[f'{name}_edits'] for r in rows)
        result[name] = dict(edit_count=edits, character_accuracy_proxy=1-edits/chars,
                            exact_text_matches=sum(r[f'{name}_edits']==0 for r in rows))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    data = json.loads((output/'danmaku_reprocessed.json').read_text())
    run = Path(data['metadata']['source_run'])
    old = json.loads((run/'danmaku_live.json').read_text())['records']
    new = data['records']
    for name, expected in data['metadata']['input_sha256'].items():
        assert hashlib.sha256((run/name).read_bytes()).hexdigest() == expected, name
    code_hash = hashlib.sha256(Path(__file__).with_name('reprocess.py').read_bytes()).hexdigest()
    assert code_hash == data['metadata']['code_sha256']
    held = json.loads((output/'manual_holdout_labels.json').read_text())
    assert code_hash == held['algorithm_sha256']
    for record in new:
        assert record['text'] in record['raw_text_variants']
        assert all(o['text']==record['text'] for o in record['support'])
        for name in ['native_message_id','posting_time','platform_offset_time_ms','estimated_playback_offset_ms','episode_id']:
            assert record[name] is None
    dev = json.loads((run/'manual_audit_first10.json').read_text())
    metrics = dict(development=evaluate(dev['items'],old,new),
                   later_examples=evaluate(held['items'],old,new),
                   normalization='NFKC alphanumeric comparison; reference emoji/punctuation excluded; hallucinated letters count as errors',
                   limits='Small correlated samples in one episode, not cross-episode validation. Recall and true native IDs unavailable.',
                   source_hashes_unchanged=True, retained_tracks=len(new),
                   candidate_tracks=data['metadata']['withheld_candidates'])
    write_json(output/'evaluation.json',metrics)
    frame_hashes = {str(p.relative_to(run)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((run/'frames').glob('*.png'))}
    assert len(frame_hashes)==178
    write_json(output/'source_frame_sha256.json',frame_hashes)
    print(json.dumps({k:{x:y for x,y in v.items() if x!='rows'} if isinstance(v,dict) else v for k,v in metrics.items()},ensure_ascii=False))
    # Extend the new audit, leaving original pilot files untouched.
    page = (output/'audit.html').read_text()
    summary = '<p><b>38 retained events; 1 withheld candidate (group 31).</b> Groups 1 and 2 are boundary events with only one full-spelling supporting frame; review them. All local group numbers are processing identifiers, never native message IDs.</p>'
    summary += '<p><a href="development_comparison.png">First-10 side-by-side audit</a> · <a href="holdout_comparison.png">Later-10 side-by-side audit</a> · <a href="evaluation.json">Machine-readable evaluation</a></p>'
    for label,key in [('Original first 10','development'),('Frozen later 10','later_examples')]:
        m=metrics[key]
        summary+=f'<p>{label}: character accuracy {m["before"]["character_accuracy_proxy"]:.1%} → {m["after"]["character_accuracy_proxy"]:.1%}; exact normalized text {m["before"]["exact_text_matches"]}/10 → {m["after"]["exact_text_matches"]}/10. {m["distinct_new_events"]} distinct retained events.</p>'
    summary += '<p>These checks exclude emoji and punctuation and do not measure missed messages. Later examples are from the same capture and share vocabulary; perfect sample matches do not imply 100% general accuracy.</p>'
    summary += '<h2>Playback-clock synchronization proposal</h2><p>Before a future approved capture, expose the player elapsed-time display and capture it in the SAME mirrored frame as the video. Record multiple clock anchors, capture start/end monotonic times, and display resolution/rounding uncertainty. Re-anchor periodically and after pause, buffering, seeking, speed changes or episode changes; interpolate only within verified continuous segments. Unknown gaps stay null. The phone status-bar clock is not a playback clock. If the app cannot display an elapsed clock, a user-confirmed reset can give only an approximate relative zero; exact offsets remain unavailable. No current offsets have been backfilled.</p>'
    page = page.replace('<table><thead>',summary+'<table><thead>',1)
    page = page.replace('<td>31<br>','<td><strong>WITHHELD CANDIDATE</strong><br>31<br>')
    (output/'audit.html').write_text(page,encoding='utf-8')


if __name__=='__main__':main()
