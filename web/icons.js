// Button icons as inline SVG. Symbol characters such as ⏮ or ▶ turn into
// colour emoji on some phones, so the buttons draw their own shapes in the
// text colour instead. Buttons name their icon with `data-icon`.

const svg = (body) =>
  `<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">${body}</svg>`;

export const ICONS = {
  start: svg('<rect x="5" y="5" width="2.5" height="14" rx="1"/><path d="M19 5v14L8.5 12z"/>'),
  prevMeasure: svg('<path d="M12 5v14l-8-7z"/><path d="M20 5v14l-8-7z"/>'),
  play: svg('<path d="M7 4.5v15l12.5-7.5z"/>'),
  pause: svg('<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>'),
  nextMeasure: svg('<path d="M4 5v14l8-7z"/><path d="M12 5v14l8-7z"/>'),
  stop: svg('<rect x="6" y="6" width="12" height="12" rx="1.5"/>'),
  repeat: svg(
    '<path d="M17 4l3 3-3 3V8H7a2 2 0 0 0-2 2v2H3v-2a4 4 0 0 1 4-4h10z"/>' +
      '<path d="M7 20l-3-3 3-3v2h10a2 2 0 0 0 2-2v-2h2v2a4 4 0 0 1-4 4H7z"/>',
  ),
  render: svg('<path d="M11 3h2v10.2l3.6-3.6 1.4 1.4-6 6-6-6 1.4-1.4 3.6 3.6z"/><rect x="4" y="19" width="16" height="2" rx="1"/>'),
};

export function setIcon(el, name) {
  el.dataset.icon = name;
  el.innerHTML = ICONS[name];
}

export function drawIcons(root = document) {
  for (const el of root.querySelectorAll("[data-icon]")) setIcon(el, el.dataset.icon);
}
