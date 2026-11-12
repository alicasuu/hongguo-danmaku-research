"""Read only the existing screenshot; verify ROI mapping against full-frame OCR."""
import json
from collect import BASE, Vision


def intersection_over_union(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    area = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))
    return area / (aw * ah + bw * bh - area)


def main():
    references = [d for d in json.loads((BASE / 'static_ocr.json').read_text())['detections']
                  if d['region'] == 'danmaku_candidate']
    worker = Vision()
    try:
        result = worker.read(BASE.parents[1] / 'debug_capture.png')
    finally:
        worker.close()
    detections = result['detections']
    assert len(detections) == len(references) == 5
    for detection in detections:
        assert detection['region'] == 'danmaku_candidate'
        # OCR crop changes can expand or shift boxes; compare overlap, not exact pixels.
        assert max(intersection_over_union(detection['bbox'], r['bbox']) for r in references) > .45
    output = BASE / 'static_roi_ocr.json'
    if not output.exists():
        with output.open('x') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(dict(coordinate_overlap_check='passed', result=result), ensure_ascii=False))


if __name__ == '__main__':
    main()
