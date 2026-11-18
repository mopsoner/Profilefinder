/* Shared prospect media selection, with native controls and keyboard navigation. */
window.ProspectMedia = {
  async request(url, init) {
    const response = await fetch(url, init);
    if (response.ok) return response.json();
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'La demande a échoué.');
  },
  json(data) {
    return {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)};
  },
  previews(row) {
    const kind = row.mime.split('/')[0];
    const element = document.createElement(kind === 'image' ? 'img' : kind);
    element.src = row.url;
    if (kind === 'image') {
      element.alt = row.name;
      element.loading = 'lazy';
    } else {
      element.controls = true;
      element.preload = 'metadata';
      if (kind === 'video') element.playsInline = true;
    }
    return element;
  },
  values(root) {
    return [...root.querySelectorAll('input:checked')].map(input => input.value);
  },
  async mount(root, leadId, {types = ['image', 'video', 'audio'], ids = [], logos = false, distinct = false, name = 'media_ids'} = {}) {
    const token = Symbol();
    root.mediaToken = token;
    root.mediaRows = [];
    root.replaceChildren();
    if (!leadId) return;
    try {
      const data = await this.request('/api/leads/' + Number(leadId) + '/media');
      if (root.mediaToken !== token) return;
      root.mediaRows = data.media.filter(row => types.includes(row.mime.split('/')[0]) &&
        (logos ? row.category === 'logo' || ids.includes(row.id) : !distinct || row.category !== 'logo' || ids.includes(row.id)));
      for (const row of root.mediaRows) {
        const label = document.createElement('label');
        const input = document.createElement('input');
        input.type = logos ? 'radio' : 'checkbox';
        input.name = name;
        input.value = row.id;
        input.checked = ids.includes(row.id);
        label.append(input, ' ' + row.name + (row.attribution ? ' · ' + row.attribution : ''));
        const item = document.createElement('div');
        item.className = 'prospect-media-option';
        item.append(label, this.previews(row));
        root.append(item);
      }
      if (logos && root.mediaRows.length) {
        const empty = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'radio';
        input.name = name;
        empty.append(input, ' Sans logo');
        input.value = '';
        input.checked = !ids.length;
        root.prepend(empty);
      }
      const link = document.createElement('a');
      link.href = '/media?lead_id=' + Number(leadId);
      link.textContent = 'Ouvrir la bibliothèque du prospect';
      root.append(link);
    } catch (error) {
      if (root.mediaToken === token) root.textContent = error.message;
    }
  }
};
for (const root of document.querySelectorAll('[data-site-media]')) {
  ProspectMedia.mount(root, root.dataset.siteMedia, {types: ['image', 'video'],
    ids: JSON.parse(root.dataset.selected || '[]')});
}
