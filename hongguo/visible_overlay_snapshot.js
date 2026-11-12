// Read-only DOM sampler. Run through the connected browser's evaluate API.
// No fetch, browser storage, cookies, credentials, or application globals.
() => {
  const script = Array.from(document.scripts).find(s =>
    !s.src && s.textContent.trim().startsWith('_ROUTER_DATA ='));
  if (!script) throw new Error('Expected public page loader markup missing');
  const source = script.textContent;
  const start = source.indexOf('{');
  let depth = 0, quoted = false, escape = false, end = -1;
  for (let i = start; i < source.length; i++) {
    const c = source[i];
    if (quoted) {
      if (escape) escape = false;
      else if (c === '\\') escape = true;
      else if (c === '"') quoted = false;
    } else if (c === '"') quoted = true;
    else if (c === '{') depth++;
    else if (c === '}' && --depth === 0) { end = i + 1; break; }
  }
  if (end < 0) throw new Error('Unterminated public loader JSON');
  const loader = JSON.parse(source.slice(start, end)).loaderData;
  const entry = Object.entries(loader).find(([key, value]) =>
    key.startsWith('player_') && value?.seriesDetail);
  if (!entry) throw new Error('Player loader missing');
  const [route, data] = entry;
  const parts = location.pathname.split('/').filter(Boolean);
  const episodeId = parts[2] || data.seriesDetail.vid_list?.[0];
  if (typeof episodeId !== 'string' || !/^\d+$/.test(episodeId))
    throw new Error('Exact episode ID unavailable');
  const reviews = data.episodeSocialInfo?.reviews?.reviews || [];
  const video = document.querySelector('video');
  const layer = document.querySelector('xg-danmu[data-testid="xgplayer-danmu-layer"]');
  const textWithEmoji = node => node.nodeType === 3 ? node.textContent :
    node.nodeName === 'IMG' ? (node.getAttribute('alt') || '') :
      Array.from(node.childNodes).map(textWithEmoji).join('');
  const box = r => ({left:r.left, top:r.top, right:r.right, bottom:r.bottom});
  const clip = layer?.getBoundingClientRect();
  const messages = [];
  if (layer && clip) for (const el of layer.querySelectorAll('[data-danmaku-id]')) {
    const rect = el.getBoundingClientRect();
    let hidden = false;
    for (let p = el; p; p = p.parentElement) {
      const style = getComputedStyle(p);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) {
        hidden = true; break;
      }
    }
    const intersection = {
      left:Math.max(0, clip.left, rect.left), top:Math.max(0, clip.top, rect.top),
      right:Math.min(innerWidth, clip.right, rect.right), bottom:Math.min(innerHeight, clip.bottom, rect.bottom)
    };
    if (hidden || intersection.right <= intersection.left || intersection.bottom <= intersection.top) continue;
    const renderId = el.getAttribute('data-danmaku-id');
    const match = /^dm-init-(\d+)$/.exec(renderId || '');
    const text = textWithEmoji(el).trim();
    if (!text) continue;
    const review = match ? reviews[Number(match[1])] : null;
    const matched = !!review && typeof review.content === 'string' && review.content.trim() === text;
    messages.push({text, dom_render_id:renderId, visible:true,
      partially_clipped:intersection.left > rect.left || intersection.right < rect.right,
      element_bounds:box(rect), visible_bounds:intersection,
      source_review:matched ? {index:Number(match[1]), content:review.content,
        create_time:review.create_time ?? null, available_fields:Object.keys(review)} : null,
      source_match:matched ? 'renderer_index_and_exact_text' : 'unmatched',
      platform_message_id:null, platform_playback_time_ms:null});
  }
  return {observed_at:new Date().toISOString(), source_url:location.origin + location.pathname,
    page_title:document.title, drama_id:String(data.series_id), episode_id:episodeId,
    episode_mapping:parts[2] ? 'player_path_episode_id' : 'page_loader_first_vid',
    loader_route:route, source_path:'episodeSocialInfo.reviews.reviews',
    source_review_count:reviews.length,
    source_review_field_names:Array.from(new Set(reviews.flatMap(r=>Object.keys(r)))),
    coverage:'sampled_visible', timing_method:'observed_playback_position',
    video:video ? {current_time_seconds:Number.isFinite(video.currentTime)?video.currentTime:null,
      duration_seconds:Number.isFinite(video.duration)?video.duration:null,
      paused:video.paused, ended:video.ended} : null,
    layer_present:!!layer, viewport:{width:innerWidth,height:innerHeight}, messages};
}
