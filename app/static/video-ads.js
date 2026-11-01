(() => {
  const $ = id => document.getElementById(id);
  if (!$('video-lead')) return;
  const state = {context: null, project: null, format: 'portrait', epoch: 0, timer: null};
  const labels = {preparing:'Captures HD en cours', ready:'Storyboard prêt', rendering:'Rendu vidéo en cours', completed:'Vidéo disponible', failed:'À reprendre'};
  let noticeTimer;
  function notice(message) { $('video-notice').textContent=message;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('video-notice').textContent='',7000); }
  async function api(url, data) {
    const response=await fetch(url, data===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    let value;try{value=await response.json();}catch{throw new Error('Le serveur n’a pas renvoyé de réponse valide.');}
    if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:value.error||'Le traitement a échoué.');
    return value;
  }
  const selectedAudio=()=>state.context?.audios.find(a=>a.id===$('video-audio').value);
  function updateAudio() {
    const audio=selectedAudio();
    $('source-audio').pause();$('source-audio').hidden=!audio;
    if(audio){$('source-audio').src=audio.url;$('audio-meta').textContent=`${audio.duration.toFixed(1)} s · ${audio.script.split(/\s+/).length} mots · audio conservé pour ce lead`;}
    else{$('source-audio').removeAttribute('src');$('audio-meta').textContent='Aucun audio sélectionné. Créez-le dans Ads ou importez un fichier existant.';}
    $('prepare-video').disabled=!(audio&&state.context?.has_site&&state.context.ready);
  }
  function drawHistory(projects) {
    $('video-history').replaceChildren();
    if(!projects.length){const p=document.createElement('p');p.className='history-empty';p.textContent='Vos prochains projets vidéo apparaîtront ici.';$('video-history').append(p);return;}
    projects.forEach(project=>{const button=document.createElement('button');button.type='button';button.className='history-item'+(state.project?.id===project.id?' chosen':'');const label=document.createElement('span');label.textContent=labels[project.status]||project.status;const date=document.createElement('small');date.textContent=new Date(project.created_at+'Z').toLocaleDateString('fr-FR')+' · '+({portrait:'9:16',landscape:'16:9',square:'1:1'}[project.format]);button.append(label,date);button.onclick=()=>loadProject(project.id);$('video-history').append(button);});
  }
  async function loadContext(audioId) {
    const epoch=++state.epoch;clearTimeout(state.timer);state.project=null;state.context=null;
    $('story-empty').hidden=false;$('storyboard').hidden=true;$('video-result').hidden=true;$('project-progress').hidden=true;$('project-error').hidden=true;$('project-badge').textContent='EN ATTENTE';$('lead-context').hidden=true;$('prepare-video').disabled=true;$('final-video').pause();
    const lead=$('video-lead').value;if(!lead){$('video-history').replaceChildren();return;}
    try{
      const context=await api('/api/video-ads/leads/'+lead);if(epoch!==state.epoch)return;
      state.context=context;$('lead-context').hidden=false;$('site-status').textContent=context.has_site?`◈ Site disponible · ${context.pages.length} page(s) à capturer en HD`:'Générez d’abord un site pour ce lead dans Sites IA.';$('site-status').classList.toggle('missing',!context.has_site);
      $('audio-studio-link').href='/ads?lead_id='+lead;
      $('video-audio').replaceChildren(new Option('Choisir un audio…',''));
      context.audios.forEach(audio=>$('video-audio').add(new Option(`${new Date(audio.created_at+'Z').toLocaleString('fr-FR')} · ${audio.duration.toFixed(1)} s`,audio.id)));
      $('video-audio').value=context.audios.some(a=>a.id===audioId)?audioId:(context.audios[0]?.id||'');updateAudio();drawHistory(context.projects);
      if(!context.ready)notice('Playwright, Chromium et FFmpeg sont requis pour produire les vidéos.');
    }catch(error){if(epoch===state.epoch)notice(error.message);}
  }
  function updateURL() {const query=new URLSearchParams({lead_id:$('video-lead').value});if(state.project)query.set('project_id',state.project.id);history.replaceState(null,'','/video-ads?'+query);}
  function timing() {const slides=state.project?.slides||[];const audio=state.context?.audios.find(a=>a.id===state.project?.audio_id);$('timing-summary').textContent=`${slides.length} slide(s) · audio ${audio?audio.duration.toFixed(1):'—'} s`;}
  function dirty() {$('video-result').hidden=true;$('project-badge').textContent='À GÉNÉRER';}
  function drawSlides() {
    const project=state.project;$('slides-list').replaceChildren();timing();
    project.slides.forEach((slide,index)=>{
      const card=document.createElement('article');card.className='slide-card';
      const thumb=document.createElement('div');thumb.className='slide-thumbnail';const img=document.createElement('img');img.src=project.pages[slide.page_index].url;img.alt='Capture HD de '+project.pages[slide.page_index].title;const counter=document.createElement('span');counter.className='slide-counter';counter.textContent=`SLIDE ${String(index+1).padStart(2,'0')}`;thumb.append(img,counter);
      const fields=document.createElement('div');fields.className='slide-fields';const label=document.createElement('label');label.textContent='Texte à l’écran';const caption=document.createElement('textarea');caption.rows=3;caption.maxLength=700;caption.value=slide.caption;caption.setAttribute('aria-label',`Texte de la slide ${index+1}`);caption.oninput=()=>{slide.caption=caption.value;dirty();};label.append(caption);
      const controls=document.createElement('div');controls.className='slide-controls';const pageLabel=document.createElement('label');pageLabel.textContent='Page du site';const select=document.createElement('select');project.pages.forEach((p,i)=>select.add(new Option(p.title,String(i))));select.value=slide.page_index;select.onchange=()=>{slide.page_index=Number(select.value);img.src=project.pages[slide.page_index].url;img.alt=project.pages[slide.page_index].title;dirty();};pageLabel.append(select);
      const durationLabel=document.createElement('label');durationLabel.textContent='Durée (s)';const duration=document.createElement('input');duration.type='number';duration.min='.5';duration.max='300';duration.step='.1';duration.value=slide.duration.toFixed(1);duration.setAttribute('aria-label',`Durée de la slide ${index+1}`);duration.oninput=()=>{slide.duration=Number(duration.value);dirty();};durationLabel.append(duration);
      const order=document.createElement('div');order.className='slide-order';for(const [text,title,offset] of [['↑','Monter',-1],['↓','Descendre',1],['×','Supprimer',0]]){const button=document.createElement('button');button.type='button';button.textContent=text;button.title=title;button.setAttribute('aria-label',`${title} la slide ${index+1}`);button.disabled=offset===-1?index===0:offset===1?index===project.slides.length-1:project.slides.length===1;if(!offset)button.className='delete-slide';button.onclick=()=>{if(offset){const target=index+offset;[project.slides[index],project.slides[target]]=[project.slides[target],project.slides[index]];}else project.slides.splice(index,1);dirty();drawSlides();};order.append(button);}
      controls.append(pageLabel,durationLabel,order);fields.append(label,controls);card.append(thumb,fields);$('slides-list').append(card);
    });$('add-slide').disabled=project.slides.length>=8;
  }
  async function refreshHistory() {try{const epoch=state.epoch;const context=await api('/api/video-ads/leads/'+$('video-lead').value);if(epoch===state.epoch)drawHistory(context.projects);}catch{}}
  function showProject(project) {
    state.project=project;updateURL();$('story-empty').hidden=true;$('project-badge').textContent=(labels[project.status]||project.status).toLocaleUpperCase('fr');
    const busy=['preparing','rendering'].includes(project.status);$('project-progress').hidden=!busy;$('progress-label').textContent=labels[project.status];$('progress-value').textContent=project.progress+' %';$('progress-bar').value=project.progress;
    $('project-error').hidden=!project.error;$('project-error').textContent=project.error||'';$('storyboard').hidden=busy||project.status==='failed'&&project.pages.length===0;
    $('video-result').hidden=project.status!=='completed';
    if(!busy){drawSlides();if(project.status==='completed'){$('final-video').src=project.video_url;$('download-video').href=project.video_url;$('download-video').download=`video-ads-${project.lead_id}.mp4`;$('result-format').textContent={portrait:'1080 × 1920',landscape:'1920 × 1080',square:'1080 × 1080'}[project.format];}}
    clearTimeout(state.timer);if(busy){const epoch=state.epoch;state.timer=setTimeout(()=>poll(project.id,epoch),1400);}else refreshHistory();
  }
  async function poll(id,epoch){try{const project=await api('/api/video-ads/'+id);if(epoch===state.epoch&&state.project?.id===id)showProject(project);}catch(error){if(epoch===state.epoch){notice(error.message+' · nouvelle tentative dans 5 secondes');state.timer=setTimeout(()=>poll(id,epoch),5000);}}}
  async function loadProject(id){try{const epoch=state.epoch;const project=await api('/api/video-ads/'+id);if(epoch!==state.epoch)return;if(project.lead_id!==Number($('video-lead').value))throw new Error('Ce projet appartient à un autre lead.');$('video-audio').value=project.audio_id;updateAudio();showProject(project);}catch(error){notice(error.message);}}
  $('video-lead').onchange=async()=>{history.replaceState(null,'','/video-ads'+($('video-lead').value?'?lead_id='+$('video-lead').value:''));await loadContext();};
  $('video-audio').onchange=()=>{updateAudio();if(state.project&&$('video-audio').value!==state.project.audio_id)notice('Pour utiliser ce nouvel audio, préparez un nouveau slideshow.');};
  document.querySelectorAll('[data-format]').forEach(button=>button.onclick=()=>{state.format=button.dataset.format;document.querySelectorAll('[data-format]').forEach(b=>{const selected=b===button;b.classList.toggle('chosen',selected);b.setAttribute('aria-pressed',String(selected));});});
  $('prepare-video').onclick=async()=>{const button=$('prepare-video'),epoch=state.epoch;button.disabled=true;try{const project=await api('/api/video-ads/prepare',{lead_id:Number($('video-lead').value),audio_id:$('video-audio').value,format:state.format});if(epoch===state.epoch){showProject(project);notice('Préparation des captures HD et du storyboard.');}}catch(error){notice(error.message);}finally{if(epoch===state.epoch)updateAudio();}};
  $('add-slide').onclick=()=>{if(state.project.slides.length>=8)return;state.project.slides.push({page_index:0,caption:'',duration:3});dirty();drawSlides();};
  $('render-video').onclick=async()=>{if(state.project.slides.some(s=>!s.caption.trim()||s.caption.length>700||!Number.isFinite(s.duration)||s.duration<.5||s.duration>300)){notice('Vérifiez les textes et les durées de vos slides.');return;}const button=$('render-video'),epoch=state.epoch;button.disabled=true;try{const project=await api('/api/video-ads/'+state.project.id+'/render',{slides:state.project.slides});if(epoch===state.epoch)showProject(project);}catch(error){notice(error.message);}finally{button.disabled=false;}};
  const toBase64=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Fichier illisible.'));reader.readAsDataURL(file);});
  $('save-existing').onclick=async()=>{const file=$('existing-audio').files[0],script=$('existing-script').value.trim(),lead=Number($('video-lead').value);if(!file||file.size>20*1024*1024||!script){notice('Choisissez un audio de 20 Mo maximum et renseignez son texte de voix off.');return;}const button=$('save-existing'),epoch=state.epoch;button.disabled=true;try{const audio=await api('/api/ads/audio',{lead_id:lead,script,audio:await toBase64(file)});if(epoch===state.epoch){await loadContext(audio.id);notice('Audio et texte associés à ce lead.');}}catch(error){notice(error.message);}finally{button.disabled=false;}};
  const params=new URLSearchParams(location.search);if(params.get('lead_id')&&Array.from($('video-lead').options).some(o=>o.value===params.get('lead_id'))){$('video-lead').value=params.get('lead_id');loadContext(params.get('audio_id')).then(()=>{if(params.get('project_id'))loadProject(params.get('project_id'));});}
})();
