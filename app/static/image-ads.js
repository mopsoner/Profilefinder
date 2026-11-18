(() => {
  const $ = id => document.getElementById('image-' + id);
  const form = $('form');
  let epoch = 0;
  let projectId = '';
  let pending = false;
  let prospectFields = {};
  const activeJobs = ['queued', 'running'];
  const renderLabel = () => projectId ? 'Enregistrer les modifications' : 'Composer et enregistrer';
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
    media_ids: ProspectMedia.values($('references')), logo_id: ProspectMedia.values($('logo'))[0] || null});
  function syncImageStyle() {
    const realPhoto = $('mode').value !== 'ai';
    $('style-field').hidden = realPhoto;
    $('style').disabled = realPhoto;
  }
  $('mode').addEventListener('change', syncImageStyle);
  function syncHeadlinePlacement() {
    $('headline-placement').hidden = !form.elements.message.value.trim();
  }
  $('headline').addEventListener('input', syncHeadlinePlacement);
  async function showProject(id) {
    const revision = ++epoch;
    projectId = id;
    pending = true;
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
    $('render').disabled = true;
    $('render').textContent = renderLabel();
    report('');
    let loaded = false;
    try {
      const project = id ? await ProspectMedia.request(base() + '/' + id) : null;
      if (revision !== epoch) return;
      const options = project?.options || {};
      const fields = {...prospectFields, ...options, ...options.business};
      for (const [key, value] of Object.entries(fields)) {
        if (['media_ids', 'logo_id', 'identity', 'business'].includes(key)) continue;
        const field = form.elements.namedItem(key);
        if (field instanceof HTMLElement) field.value = value;
      }
      syncImageStyle();
      syncHeadlinePlacement();
      await Promise.all([
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
        pending = false;
        $('render').disabled = !loaded;
      }
    }
  }
  async function poll(project, revision) {
    while (revision === epoch) {
      const latest = project.jobs[0];
      $('render').textContent = latest?.status === 'failed' ? 'Relancer la composition' : renderLabel();
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
    $('render').disabled = true;
    report('Enregistrement de la composition…');
    try {
      const data = await ProspectMedia.request(base() + (projectId ? '/' + projectId : ''), ProspectMedia.json(payload()));
      if (revision !== epoch) return;
      history.replaceState(null, '', '?lead_id=' + $('lead').value + '&project_id=' + data.id);
      await selectLead(data.id);
    } catch (error) {
      if (revision === epoch) report(error.message);
    } finally {
      if (revision === epoch) {
        pending = false;
        $('render').disabled = false;
      }
    }
  };
  selectLead($('context').dataset.project, new URLSearchParams(location.search).get('new') === '1');
})();
