(() => {
  const root=document.querySelector('[data-activity-feed]');if(!root)return;
  let tasks=JSON.parse(root.querySelector('[data-task-initial]').textContent),pending=false;
  const kind=root.querySelector('[data-task-kind]'),status=root.querySelector('[data-task-status]'),search=root.querySelector('[data-task-search]'),body=root.querySelector('[data-task-body]'),feedback=root.querySelector('[data-task-feedback]');
  function cell(row,text){const td=document.createElement('td');td.textContent=text??'—';row.append(td);return td;}
  function link(td,url,text){const a=document.createElement('a');a.href=url;a.textContent=text;a.className='lead-link';td.replaceChildren(a);}
  function date(value){return value?new Date(value+'Z').toLocaleString('fr-FR'):'—';}
  function render(){
    const term=search.value.toLocaleLowerCase('fr').trim();
    const rows=tasks.filter(t=>(!kind.value||t.kind===kind.value)&&(!status.value||t.status===status.value)&&(!term||[t.city,t.id,t.kind_label,t.stage,t.error].join(' ').toLocaleLowerCase('fr').includes(term)));
    for(const group of ['running','completed','failed'])root.querySelector(`[data-task-count="${group}"]`).textContent=rows.filter(t=>group==='running'?['running','queued'].includes(t.status):group==='completed'?['ready','completed'].includes(t.status):t.status==='failed').length;
    const fragment=document.createDocumentFragment();
    rows.forEach(t=>{const tr=document.createElement('tr');link(cell(tr,''),t.url,'#'+t.id);cell(tr,t.kind_label);const lead=cell(tr,t.city);if(t.lead_url)link(lead,t.lead_url,t.city);const badge=document.createElement('span');badge.className='badge '+t.status;badge.textContent=t.status_label;cell(tr,'').append(badge);cell(tr,t.progress==null?'—':t.progress+'%');const info=cell(tr,t.error||t.stage||'—');if(t.error)info.className='error-text';cell(tr,t.kind==='search'?`${t.total_found} trouvés · ${t.total_filtered} retenus`:'—');cell(tr,date(t.created_at));cell(tr,t.started_at?Math.max(0,Math.round(((t.finished_at?new Date(t.finished_at+'Z'):new Date())-new Date(t.started_at+'Z'))/1000))+' s':'—');link(cell(tr,''),t.result_url||t.url,t.kind.startsWith('video_')?'Video Ads':t.kind.startsWith('audio_')?'Audio':t.kind==='site_ai'?'Site IA':'Détails');fragment.append(tr);});
    if(!rows.length){const tr=document.createElement('tr');cell(tr,'Aucune tâche ne correspond à ces filtres.').colSpan=10;fragment.append(tr);}
    body.replaceChildren(fragment);
  }
  for(const input of [kind,status,search])input.addEventListener('input',render);
  async function refresh(){if(pending||document.hidden)return;pending=true;try{const r=await fetch('/api/jobs');if(!r.ok)throw Error();const data=await r.json();if(!Array.isArray(data))throw Error();tasks=data;render();feedback.textContent='Actualisé à '+new Date().toLocaleTimeString('fr-FR')+' · '+tasks.length+' activités · actualisation toutes les 5 secondes.';}catch{feedback.textContent='Actualisation indisponible. Les dernières données restent affichées ; nouvel essai dans 5 secondes.';}finally{pending=false;}}
  render();setInterval(refresh,5000);
})();
