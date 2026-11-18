(() => {
  const $ = id => document.getElementById('image-' + id);
  const form = $('form');
  let epoch = 0;
  let projectId = '';
  let pending = false;
  let prospectFields = {};
  const activeJobs = ['queued', 'running'];
  let currentProject = null;
  let previewTimer;
  let previewRequest;
  let previewUrl;
  function cancelPreview() {
    clearTimeout(previewTimer);
    previewRequest?.abort();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
  function syncActions() {
    const ai = $('mode').value === 'ai';
    const hasPhoto = ProspectMedia.values($('references')).length === 1;
    $('render').disabled = pending || (ai ? !currentProject?.has_background : !hasPhoto);
    $('render').textContent = projectId ? 'Retoucher le flyer' : 'Composer et enregistrer';
    $('full-render').hidden = $('ai-render').hidden = $('full-help').hidden = !ai;
    $('full-render').disabled = $('ai-render').disabled = pending;
    $('ai-render').textContent = currentProject?.has_background ? 'Modifier le fond avec l’IA' : 'Générer le fond avec l’IA';
    $('variant').hidden = !currentProject?.png;
    $('variant').disabled = pending || (!ai && !hasPhoto);
    $('reference-option').hidden = !ai || !currentProject?.png;
    $('restore').disabled = pending || !$('version').value;
  }
  function showVersions(project) {
    const selected = $('version').value;
    $('version').replaceChildren(new Option('Choisir une version', ''));
    for (const version of project?.versions || []) {
      $('version').add(new Option('Version ' + version.id + ' · ' +
        new Date(version.created_at + 'Z').toLocaleString('fr-FR'), version.id));
    }
    $('version').value = [...$('version').options].some(option => option.value === selected) ? selected : '';
    $('versions').hidden = !project?.versions.length;
    showComparison();
  }
  function showComparison() {
    const version = currentProject?.versions.find(item => String(item.id) === $('version').value);
    $('comparison').hidden = $('version-download').hidden = !version;
    $('restore').disabled = pending || !version;
    if (version) {
      $('current-version').src = currentProject.versions[0].png;
      $('old-version').src = version.png;
      $('version-download').href = version.png + '?download=true';
    }
  }
  $('version').onchange = showComparison;
  $('restore').onclick = async () => {
    const revision = epoch;
    pending = true;
    cancelPreview();
    syncActions();
    try {
      await ProspectMedia.request(base() + '/' + projectId + '/versions/' + $('version').value + '/restore', {method: 'POST'});
      if (revision === epoch) await selectLead(projectId);
    } catch (error) {
      if (revision === epoch) report(error.message);
    } finally {
      if (revision === epoch) {
        pending = false;
        syncActions();
      }
    }
  };
  function openProject(id) {
    const query = new URLSearchParams({lead_id: $('lead').value});
    if (id) query.set('project_id', id);
    history.replaceState(null, '', '?' + query);
    return showProject(id);
  }
  function updateThumbnail(project, src) {
    const card = [...$('projects').children].find(button => button.dataset.project === project.id);
    const image = card?.querySelector('img');
    if (image && image.getAttribute('src') !== src) {
      image.src = src;
      image.hidden = false;
    }
  }
  const base = () => '/api/leads/' + Number($('lead').value) + '/image-ads';
  const report = message => { $('status').textContent = message; };
  const payload = () => ({...Object.fromEntries(new FormData(form)),
    contact_icons: $('contact-icons').checked,
    design_reference_ids: $('mode').value === 'ai' ? ProspectMedia.values($('design-saved')) : [],
    media_ids: ProspectMedia.values($('references')), logo_id: ProspectMedia.values($('logo'))[0] || null});
  function syncImageStyle() {
    const realPhoto = $('mode').value !== 'ai';
    $('style-field').hidden = $('design-library').hidden = realPhoto;
    $('style').disabled = realPhoto;
  }
  const designApi = '/api/design-references';
  const designNotice = text => { $('design-status').textContent = text; };

  function referenceCard(item, url) {
    const card = document.createElement('article');
    const thumbnail = document.createElement('img');
    thumbnail.alt = item.title;
    thumbnail.referrerPolicy = 'no-referrer';
    thumbnail.loading = 'lazy';
    if (url) thumbnail.src = url;
    const source = document.createElement('a');
    source.href = item.source_url;
    source.target = '_blank';
    source.rel = 'noopener noreferrer';
    source.textContent = item.title + ' ↗';
    if (url) card.append(thumbnail);
    card.append(source);
    return card;
  }

  async function showDesignLibrary(ids = []) {
    const revision = epoch;
    const {references, search_available: canSearch} = await ProspectMedia.request(designApi);
    if (revision !== epoch) return;
    $('design-search').disabled = $('design-query').disabled = !canSearch;
    if (!canSearch) designNotice('Recherche indisponible. Définissez SERPAPI_API_KEY sur le serveur.');
    $('design-saved').replaceChildren();
    for (const item of references) {
      const card = referenceCard(item, item.url);
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = item.id;
      input.setAttribute('aria-label', 'Utiliser « ' + item.title + ' » comme référence');
      input.checked = ids.includes(item.id);
      label.append(input, ' Utiliser comme référence');
      card.append(label);
      $('design-saved').append(card);
    }
    if (!references.length) $('design-saved').textContent = 'Aucune référence enregistrée.';
  }

  async function searchDesigns() {
    const query = $('design-query').value.trim();
    if (query.length < 2) {
      designNotice('Saisissez au moins deux caractères.');
      return;
    }
    const revision = epoch;
    $('design-search').disabled = true;
    designNotice('Recherche en cours…');
    $('design-results').replaceChildren();
    try {
      const {results} = await ProspectMedia.request(designApi + '/search?' + new URLSearchParams({q: query}));
      if (revision !== epoch) return;
      for (const item of results) {
        const card = referenceCard(item, item.thumbnail);
        const save = document.createElement('button');
        save.type = 'button';
        save.className = 'secondary';
        save.textContent = 'Enregistrer comme référence';
        save.onclick = async () => {
          save.disabled = true;
          try {
            const reference = await ProspectMedia.request(designApi, ProspectMedia.json({token: item.token}));
            if (revision !== epoch) return;
            const selected = ProspectMedia.values($('design-saved'));
            const room = ProspectMedia.values($('references')).length + selected.length < 4;
            if (room && !selected.includes(reference.id)) selected.push(reference.id);
            await showDesignLibrary(selected);
            if (revision !== epoch) return;
            save.textContent = 'Référence enregistrée';
            designNotice(room ? 'Référence enregistrée dans la bibliothèque.' :
              'Référence enregistrée. Libérez une place pour l’utiliser dans ce projet.');
          } catch (error) {
            if (revision === epoch) {
              designNotice(error.message);
              save.disabled = false;
            }
          }
        };
        card.append(save);
        $('design-results').append(card);
      }
      designNotice(results.length ? results.length + ' références trouvées.' : 'Aucune image trouvée.');
    } catch (error) {
      if (revision === epoch) designNotice(error.message);
    } finally {
      if (revision === epoch) $('design-search').disabled = false;
    }
  }
  $('design-search').onclick = searchDesigns;
  $('design-query').onkeydown = event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (!$('design-search').disabled) searchDesigns();
    }
  };
  function schedulePreview() {
    syncActions();
    clearTimeout(previewTimer);
    previewRequest?.abort();
    if (pending) return;
    const options = payload();
    const hasBackground = options.mode === 'photo' ? options.media_ids.length === 1 : currentProject?.has_background;
    if (!hasBackground) {
      if (options.mode === 'ai' && currentProject?.options.render_kind === 'full' && currentProject.png) {
        $('preview').src = currentProject.png;
        $('preview').hidden = false;
        $('preview-status').textContent = 'Dernier flyer enregistré. Régénérez le flyer complet pour appliquer les nouvelles consignes.';
      } else {
        $('preview-status').textContent = 'Sélectionnez une photo ou générez un visuel pour afficher l’aperçu.';
        $('preview').hidden = true;
      }
      return;
    }
    const revision = epoch;
    previewTimer = setTimeout(async () => {
      const request = new AbortController();
      previewRequest = request;
      try {
        const url = base() + (projectId ? '/' + projectId : '') + '/preview';
        const response = await fetch(url, {...ProspectMedia.json(options), signal: request.signal});
        if (!response.ok) throw new Error('Aperçu indisponible pour ces réglages.');
        const blob = await response.blob();
        if (revision !== epoch || request.signal.aborted) return;
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = URL.createObjectURL(blob);
        $('preview').src = previewUrl;
        $('preview').hidden = false;
        $('preview-status').textContent = 'Aperçu des retouches sur le visuel actuel';
      } catch (error) {
        if (revision === epoch && !request.signal.aborted) $('preview-status').textContent = error.message;
      }
    }, 350);
  }
  $('mode').addEventListener('change', syncImageStyle);
  form.addEventListener('input', schedulePreview);
  function syncHeadlinePlacement() {
    $('headline-placement').hidden = !form.elements.message.value.trim();
  }
  $('headline').addEventListener('input', syncHeadlinePlacement);
  async function showProject(id) {
    const revision = ++epoch;
    projectId = id;
    pending = true;
    cancelPreview();
    currentProject = null;
    showVersions(null);
    $('preview-status').textContent = '';
    $('design-results').replaceChildren();
    $('design-saved').replaceChildren();
    designNotice('');
    form.reset();
    syncImageStyle();
    syncHeadlinePlacement();

    $('preview').hidden = $('download').hidden = true;
    $('preview').removeAttribute('src');
    $('download').removeAttribute('href');
    for (const card of $('projects').children) {
      card.setAttribute('aria-pressed', String(card.dataset.project === id));
    }
    $('history').replaceChildren();
    syncActions();
    report('');
    let loaded = false;
    try {
      const project = id ? await ProspectMedia.request(base() + '/' + id) : null;
      if (revision !== epoch) return;
      const options = project?.options || {};
      const fields = {...prospectFields, contact_icons: !project, ...options, ...options.business};
      for (const [key, value] of Object.entries(fields)) {
        if (['media_ids', 'design_reference_ids', 'logo_id', 'identity', 'business'].includes(key)) continue;
        const field = form.elements.namedItem(key);
        if (field === $('contact-icons')) field.checked = value === true;
        else if (field instanceof HTMLElement) field.value = value;
      }
      syncImageStyle();
      syncHeadlinePlacement();
      await Promise.all([
        showDesignLibrary(options.design_reference_ids).catch(error => {
          if (revision === epoch) designNotice(error.message);
        }),
        ProspectMedia.mount($('references'), $('lead').value, {types: ['image'], distinct: true, ids: project?.options.media_ids}),
        ProspectMedia.mount($('logo'), $('lead').value, {types: ['image'], logos: true, name: 'logo_id',
          ids: project?.options.logo_id ? [project.options.logo_id] : []})
      ]);
      if (revision !== epoch) return;
      loaded = true;
      if (project) await poll(project, revision);
    } catch (error) {
      if (revision === epoch) report(error.message);
    } finally {
      if (revision === epoch) {
        pending = !loaded;
        syncActions();
      }
    }
  }
  async function poll(project, revision) {
    while (revision === epoch) {
      const latest = project.jobs[0];
      currentProject = project;
      showVersions(project);
      $('history').replaceChildren(...project.jobs.map(job => {
        const item = document.createElement('li');
        const link = document.createElement('a');
        link.href = job.url;
        link.textContent = new Date(job.created_at + 'Z').toLocaleString('fr-FR') + ' · ' + job.status_label;
        item.append(link, job.error ? ' · ' + job.error : '');
        return item;
      }));
      report(latest ? [latest.status_label, latest.stage, latest.progress == null ? '' : latest.progress + ' %', latest.error].filter(Boolean).join(' · ') : '');
      if (project.png) {
        const src = project.png + '?v=' + (latest ? latest.id + '-' + latest.status : '');
        updateThumbnail(project, src);
        if ($('preview').getAttribute('src') !== src) $('preview').src = src;
        $('preview').hidden = $('download').hidden = false;
        $('download').href = project.png + '?download=true';
      }
      if (!latest || !activeJobs.includes(latest.status)) return;
      await new Promise(resolve => setTimeout(resolve, 900));
      if (revision !== epoch) return;
      project = await ProspectMedia.request(base() + '/' + project.id);
    }
  }
  async function selectLead(id = '', startNew = false) {
    const revision = ++epoch;
    pending = true;
    cancelPreview();
    syncActions();
    $('context').hidden = !$('lead').value;
    $('projects').replaceChildren();
    $('preview').hidden = $('download').hidden = true;
    $('identity').textContent = '';
    report('');
    if ($('context').hidden) return;
    $('render').disabled = $('new').disabled = true;
    try {
      const context = await ProspectMedia.request(base());
      if (revision !== epoch) return;
      prospectFields = {display_name: context.name, ...context.business};
      const colors = Object.values(context.identity.palette || {}).join(', ');
      $('identity').textContent = [context.name, context.website, colors].filter(Boolean).join(' · ');
      for (const project of context.projects) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'secondary';
        button.dataset.project = project.id;
        const image = document.createElement('img');
        image.alt = '';
        image.loading = 'lazy';
        image.hidden = !project.png;
        if (project.png) image.src = project.png;
        const title = document.createElement('span');
        title.textContent = new Date(project.created_at + 'Z').toLocaleString('fr-FR');
        button.append(image, title);
        button.onclick = () => openProject(project.id);
        $('projects').append(button);
      }
      $('new').disabled = false;
      await openProject(startNew ? '' : id || context.projects[0]?.id || '');
    } catch (error) {
      if (revision === epoch) report(error.message);
    }
  }
  $('lead').onchange = () => {
    history.replaceState(null, '', $('lead').value ? '?lead_id=' + $('lead').value : '/image-ads');
    selectLead();
  };
  $('new').onclick = () => openProject('');
  $('message').onclick = async () => {
    const revision = epoch;
    $('message').disabled = true;
    report('Rédaction du message…');
    try {
      const data = await ProspectMedia.request(base() + '/message', ProspectMedia.json(payload()));
      if (revision === epoch) {
        form.elements.message.value = data.script.slice(0, 220);
        syncHeadlinePlacement();
        schedulePreview();
        report('Accroche prête à modifier.');
      }
    } catch (error) {
      if (revision === epoch) report(error.message);
    } finally {
      $('message').disabled = false;
    }
  };
  form.onsubmit = async event => {
    event.preventDefault();
    if (pending) return;
    const revision = epoch;
    pending = true;
    cancelPreview();
    syncActions();
    $('preview').hidden = true;
    $('preview-status').textContent = '';
    const selectedAction = event.submitter?.value || ($('mode').value === 'ai' ? 'full' : 'local');
    const action = selectedAction === 'variant' && $('mode').value === 'ai' &&
      currentProject?.options.render_kind === 'full' ? 'full_variant' : selectedAction;
    report('Enregistrement de la composition…');
    try {
      const data = await ProspectMedia.request(base() + (projectId ? '/' + projectId : ''), ProspectMedia.json({...payload(),
        action,
        use_previous_flyer: $('use-flyer').checked}));
      if (revision !== epoch) return;
      history.replaceState(null, '', '?lead_id=' + $('lead').value + '&project_id=' + data.id);
      await selectLead(data.id);
    } catch (error) {
      if (revision === epoch) report(error.message);
    } finally {
      if (revision === epoch) {
        pending = false;
        schedulePreview();
      }
    }
  };
  selectLead($('context').dataset.project, new URLSearchParams(location.search).get('new') === '1');
})();
