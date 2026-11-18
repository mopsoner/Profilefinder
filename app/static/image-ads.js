(() => {
  const $ = id => document.getElementById('image-' + id);
  const form = $('form');
  let epoch = 0;
  let projectId = '';
  let pending = false;
  const base = () => '/api/leads/' + Number($('lead').value) + '/image-ads';
  const report = message => { $('status').textContent = message; };
  const payload = () => ({...Object.fromEntries(new FormData(form)),
    media_ids: ProspectMedia.values($('references')), logo_id: ProspectMedia.values($('logo'))[0] || null});
  async function showProject(id) {
    const revision = ++epoch;
    projectId = id;
    pending = true;
    form.reset();
    $('preview').hidden = $('download').hidden = true;
    $('history').replaceChildren();
    $('render').disabled = true;
    $('render').textContent = 'Composer et enregistrer';
    report('');
    try {
      const project = id ? await ProspectMedia.request(base() + '/' + id) : null;
      if (revision !== epoch) return;
      for (const [key, value] of Object.entries(project?.options || {})) {
        if (['media_ids', 'logo_id', 'identity'].includes(key)) continue;
        const field = form.elements.namedItem(key);
        if (field instanceof HTMLElement) field.value = value;
      }
      await Promise.all([
        ProspectMedia.mount($('references'), $('lead').value, {types: ['image'], distinct: true, ids: project?.options.media_ids}),
        ProspectMedia.mount($('logo'), $('lead').value, {types: ['image'], logos: true, name: 'logo_id',
          ids: project?.options.logo_id ? [project.options.logo_id] : []})
      ]);
      if (revision !== epoch) return;
      if (project) await poll(project, revision);
    } catch (error) {
      if (revision === epoch) report(error.message);
    } finally {
      if (revision === epoch) {
        pending = false;
        $('render').disabled = false;
      }
    }
  }
  async function poll(project, revision) {
    while (revision === epoch) {
      const latest = project.jobs[0];
      $('render').textContent = latest?.status === 'failed' ? 'Relancer la composition' : 'Composer et enregistrer';
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
        const src = project.png + '?v=' + (latest?.id || '');
        if ($('preview').getAttribute('src') !== src) $('preview').src = src;
        $('preview').hidden = $('download').hidden = false;
        $('download').href = project.png + '?download=true';
      }
      if (!latest || !['queued', 'running'].includes(latest.status)) return;
      await new Promise(resolve => setTimeout(resolve, 900));
      if (revision !== epoch) return;
      project = await ProspectMedia.request(base() + '/' + project.id);
    }
  }
  async function selectLead(id = '') {
    const revision = ++epoch;
    $('context').hidden = !$('lead').value;
    $('project').replaceChildren(new Option('Nouvelle création', ''));
    if ($('context').hidden) return;
    $('render').disabled = true;
    try {
      const context = await ProspectMedia.request(base());
      if (revision !== epoch) return;
      const colors = Object.values(context.identity.palette || {}).join(', ');
      $('identity').textContent = [context.name, context.website, colors].filter(Boolean).join(' · ');
      for (const project of context.projects) {
        $('project').add(new Option(new Date(project.created_at + 'Z').toLocaleString('fr-FR'), project.id));
      }
      $('project').value = id;
      await showProject(id);
    } catch (error) {
      if (revision === epoch) report(error.message);
    }
  }
  $('lead').onchange = () => {
    history.replaceState(null, '', $('lead').value ? '?lead_id=' + $('lead').value : '/image-ads');
    selectLead();
  };
  $('project').onchange = () => {
    const id = $('project').value;
    history.replaceState(null, '', '?lead_id=' + $('lead').value + (id ? '&project_id=' + id : ''));
    showProject(id);
  };
  $('message').onclick = async () => {
    const revision = epoch;
    $('message').disabled = true;
    report('Rédaction du message…');
    try {
      const data = await ProspectMedia.request(base() + '/message', ProspectMedia.json({...payload(), message: 'Brouillon'}));
      if (revision === epoch) {
        form.elements.message.value = data.script.slice(0, 220);
        report('Message prêt à modifier.');
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
  selectLead($('context').dataset.project);
})();
