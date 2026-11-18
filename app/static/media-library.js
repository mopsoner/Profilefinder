for (const root of document.querySelectorAll('[data-media-library]')) {
  const endpoint = '/api/leads/' + Number(root.dataset.mediaLibrary) + '/media';
  const categories = JSON.parse(root.dataset.categories);
  const form = root.querySelector('form');
  const list = root.querySelector('[data-media-list]');
  const status = root.querySelector('[data-media-status]');
  async function refresh() {
    const {media, google} = await ProspectMedia.request(endpoint);
    list.replaceChildren();
    for (const row of media) {
      const card = document.createElement('article');
      const name = document.createElement('strong');
      name.textContent = row.name + (row.attribution ? ' · ' + row.attribution : '');
      const category = document.createElement('select');
      category.setAttribute('aria-label', 'Catégorie de ' + row.name);
      for (const [value, title] of Object.entries(categories)) {
        if (value !== 'logo' || row.mime.startsWith('image/')) category.add(new Option(title, value));
      }
      category.value = row.category;
      category.onchange = async () => {
        const body = new FormData();
        body.set('category', category.value);
        category.disabled = true;
        try {
          const updated = await ProspectMedia.request(row.url, {method: 'PATCH', body});
          row.category = updated.category;
          status.textContent = 'Catégorie enregistrée.';
        } catch (error) {
          category.value = row.category;
          status.textContent = error.message;
        } finally {
          category.disabled = false;
        }
      };
      card.append(name, ProspectMedia.previews(row), category);
      list.append(card);
    }
    for (const photo of google) {
      const card = document.createElement('article');
      const name = 'Photo Google ' + (photo.index + 1);
      const button = document.createElement('button');
      button.textContent = 'Ajouter à la bibliothèque';
      button.onclick = async () => {
        button.disabled = true;
        try {
          await ProspectMedia.request(endpoint + '/google/' + photo.index, {method: 'POST'});
          await refresh();
          status.textContent = 'Photo ajoutée.';
        } catch (error) {
          button.disabled = false;
          status.textContent = error.message;
        }
      };
      card.append(ProspectMedia.previews({...photo, name, mime: 'image/jpeg'}),
        [name, ...photo.authors.filter(Boolean)].join(' · '), button);
      list.append(card);
    }
    if (!list.children.length) list.textContent = 'Aucun média pour ce prospect.';
  }
  form.onsubmit = async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    status.textContent = 'Validation du fichier…';
    try {
      await ProspectMedia.request(endpoint, {method: 'POST', body: new FormData(form)});
      form.reset();
      await refresh();
      status.textContent = 'Média ajouté.';
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  refresh().catch(error => { status.textContent = error.message; });
}
