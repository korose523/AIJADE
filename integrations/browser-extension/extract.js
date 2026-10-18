// What is on screen, from a document: kept free of browser-extension APIs so it can be tested with plain DOM fixtures.
export function extractContext(doc, location) {
  const host = location.hostname;
  const video = doc.querySelector('video');
  const fmt = (t) => {
    if (!Number.isFinite(t)) return undefined;
    const s = Math.floor(t), m = Math.floor(s / 60);
    return `${Math.floor(m / 60) ? `${Math.floor(m / 60)}:` : ''}${String(m % 60).padStart(Math.floor(m / 60) ? 2 : 1, '0')}:${String(s % 60).padStart(2, '0')}`;
  };
  if (host.endsWith('youtube.com')) {
    const title = doc.querySelector('h1.ytd-watch-metadata, h1.title')?.textContent?.trim() || doc.title.replace(/ - YouTube$/, '');
    const subtitle = [...doc.querySelectorAll('.ytp-caption-segment')].map(e => e.textContent.trim()).filter(Boolean).join(' ');
    return { site: 'YouTube', kind: video ? 'video' : 'page', title, url: location.href, text: subtitle || undefined, position: video ? fmt(video.currentTime) : undefined };
  }
  if (host.endsWith('bilibili.com')) {
    const title = doc.querySelector('h1.video-title, .video-title')?.textContent?.trim() || doc.title.replace(/_哔哩哔哩_bilibili$/, '');
    const subtitle = [...doc.querySelectorAll('.bili-subtitle-x-subtitle-panel-text, .bpx-player-subtitle-panel-text')].map(e => e.textContent.trim()).filter(Boolean).join(' ');
    return { site: 'Bilibili', kind: video ? 'video' : 'page', title, url: location.href, text: subtitle || undefined, position: video ? fmt(video.currentTime) : undefined };
  }
  return { site: host, kind: 'page', title: doc.title, url: location.href };
}
