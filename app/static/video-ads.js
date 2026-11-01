(() => {
  const $ = id => document.getElementById(id);
  if (!$('video-lead')) return;
  const state = {context: null, project: null, format: 'portrait', epoch: 0, timer: null, submitting: false, loadingContext: false};
  const labels = {preparing:'Création des scènes en cours', ready:'Storyboard prêt', rendering:'Rendu vidéo en cours', completed:'Vidéo disponible', failed:'À reprendre'};
  let noticeTimer;
  function notice(message) { $('video-notice').textContent=message;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('video-notice').textContent='',7000); }
  async function api(url, data, timeout=90000) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const response=await fetch(url, {...(data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),signal:controller.signal});
      let value;try{value=await response.json();}catch{throw new Error('Le serveur n’a pas renvoyé de réponse valide. Rechargez la page ou réessayez.');}
      if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:value.error||'Le traitement a échoué.');
      return value;
    }catch(error){if(error.name==='AbortError')throw new Error('Le serveur met trop de temps à répondre. Rechargez les créations pour vérifier si le projet a démarré avant de réessayer.');throw error;}
    finally{clearTimeout(timer);}
  }
  function preparationMessage(message,error=false){$('prepare-status').textContent=message;$('prepare-status').classList.toggle('error',error);}
  function prerequisite(){
    if(!$('video-lead').value)return 'Sélectionnez d’abord un prospect dans « Le point de départ ».';
    if(state.loadingContext)return 'Chargement des médias du prospect… Patientez un instant.';
    if(!state.context)return 'Les médias du prospect ne sont pas chargés. Sélectionnez à nouveau le prospect pour réessayer.';
    if(!selectedAudio())return 'Il manque un audio sauvegardé pour ce prospect. Choisissez un audio, importez votre MP3 ou créez sa voix off dans Ads puis enregistrez le mix.';
    if(!state.context.has_site)return 'Il manque le site de ce prospect. Générez-le dans Sites IA avant de préparer le slideshow.';
    if(!state.context.ready)return 'Outils manquants sur le serveur : '+(state.context.missing_tools?.join(', ')||'Playwright, Chromium ou FFmpeg')+'. Exécutez scripts/install.sh puis redémarrez ProfileFinder.';
    if($('video-visual-mode').value==='cinematic'&&!state.context.ai_visuals_available)return 'Les plans vidéo IA nécessitent la clé OpenAI du serveur. Sélectionnez Compositions graphiques pour continuer sans nouveaux visuels IA.';
    return '';
  }
  function updatePreparation(){
    if(state.context)$('video-visual-help').textContent=`Visuels IA illustratifs : jusqu’à ${state.context.max_ai_images||4} images originales par projet, réutilisées entre les plans. La création de nouveaux visuels consomme des crédits OpenAI.`;
    const busy=state.submitting||['preparing','rendering'].includes(state.project?.status);
    $('prepare-video').disabled=busy;
    $('prepare-video').textContent=busy?'Préparation ou rendu en cours…':'✦ Préparer mon slideshow ↗';
    preparationMessage(busy?'Le traitement est en cours. Son avancement apparaît dans le storyboard.':prerequisite()||'Tout est prêt : votre audio et les pages du site seront réunis dans le storyboard.');
  }
  const scopedStudio=/^\/leads\/\d+\/video-ads$/.test(location.pathname);
  const studioPath=scopedStudio?location.pathname:'/video-ads';
  const selectedAudio=()=>state.context?.audios.find(a=>a.id===$('video-audio').value);
  function updateAudio() {
    const audio=selectedAudio();
    $('source-audio').pause();$('source-audio').hidden=!audio;
    if(audio){$('source-audio').src=audio.url;$('audio-meta').textContent=`${audio.duration.toFixed(1)} s · ${audio.script.split(/\s+/).length} mots · audio conservé pour ce lead`;}
    else{$('source-audio').removeAttribute('src');$('audio-meta').textContent='Aucun audio sélectionné. Créez-le dans Ads ou importez un fichier existant.';}
    loadAudioMessage(audio);updatePreparation();
  }
  function loadAudioMessage(audio=selectedAudio()){
    $('video-copy-text').value=audio?.script||'';
    $('video-copy-meta').textContent=audio?'Message conservé avec cet audio · utilisé pour préparer les slides.':'Sélectionnez un audio pour retrouver son message.';
    $('use-video-message').disabled=!audio?.script?.trim();
    $('restore-audio-message').hidden=!audio;
  }
  function drawHistory(projects) {
    $('video-history').replaceChildren();
    if(!projects.length){const p=document.createElement('p');p.className='history-empty';p.textContent='Vos prochains projets vidéo apparaîtront ici.';$('video-history').append(p);return;}
    projects.forEach(project=>{const button=document.createElement('button');button.type='button';button.className='history-item'+(state.project?.id===project.id?' chosen':'');const label=document.createElement('span');label.textContent=labels[project.status]||project.status;const date=document.createElement('small');date.textContent=new Date(project.created_at+'Z').toLocaleDateString('fr-FR')+' · '+({portrait:'9:16',landscape:'16:9',square:'1:1'}[project.format]);button.append(label,date);button.onclick=()=>loadProject(project.id);$('video-history').append(button);});
  }
  async function loadContext(audioId) {
    const epoch=++state.epoch;clearTimeout(state.timer);state.project=null;state.context=null;state.submitting=false;state.loadingContext=true;$('video-client-instructions').value='';$('video-client-note').hidden=true;$('restore-audio-message').hidden=true;$('video-copy-text').value='';$('video-copy-meta').textContent='';$('use-video-message').disabled=true;
    $('story-empty').hidden=false;$('storyboard').hidden=true;$('video-result').hidden=true;$('project-progress').hidden=true;$('project-error').hidden=true;$('project-badge').textContent='EN ATTENTE';$('lead-context').hidden=true;$('final-video').pause();updatePreparation();
    const lead=$('video-lead').value;if(!lead){state.loadingContext=false;$('video-history').replaceChildren();updatePreparation();return;}
    try{
      const context=await api('/api/video-ads/leads/'+lead);if(epoch!==state.epoch)return;
      state.context=context;state.loadingContext=false;$('lead-context').hidden=false;$('site-status').textContent=context.has_site?`◈ Site disponible · ${context.pages.length} page(s) à capturer en HD`:'Générez d’abord un site pour ce lead dans Sites IA.';$('site-status').classList.toggle('missing',!context.has_site);
      $('audio-studio-link').href='/ads?lead_id='+lead;
      $('video-audio').replaceChildren(new Option('Choisir un audio…',''));
      context.audios.forEach(audio=>$('video-audio').add(new Option(`${new Date(audio.created_at+'Z').toLocaleString('fr-FR')} · ${audio.duration.toFixed(1)} s`,audio.id)));
      $('video-audio').value=context.audios.some(a=>a.id===audioId)?audioId:(context.audios[0]?.id||'');updateAudio();drawHistory(context.projects);
      if(!context.ready)notice(prerequisite());
    }catch(error){if(epoch===state.epoch){state.loadingContext=false;updatePreparation();preparationMessage(error.message,true);notice(error.message);}}
  }
  function updateURL() {const query=new URLSearchParams({lead_id:$('video-lead').value});if(state.project)query.set('project_id',state.project.id);history.replaceState(null,'',studioPath+'?'+query);}
  function timing() {const slides=state.project?.slides||[];const audio=state.context?.audios.find(a=>a.id===state.project?.audio_id);$('timing-summary').textContent=`${slides.length} slide(s) · audio ${audio?audio.duration.toFixed(1):'—'} s`;}
  function dirty() {$('video-result').hidden=true;$('project-badge').textContent='À GÉNÉRER';}
  function drawSlides() {
    const project=state.project,cinematic=$('video-visual-mode').value==='cinematic';$('slides-list').replaceChildren();timing();
    project.slides.forEach((slide,index)=>{
      const card=document.createElement('article');card.className='slide-card';
      const thumb=document.createElement('div');thumb.className='slide-thumbnail';const img=document.createElement('img');img.src=slide.preview_url||project.pages[slide.page_index].url;img.alt=slide.preview_url?'Scène publicitaire composée':'Page d’inspiration '+project.pages[slide.page_index].title;const counter=document.createElement('span');counter.className='slide-counter';counter.textContent=`${cinematic?'PLAN':'SCÈNE'} ${String(index+1).padStart(2,'0')}`;thumb.append(img,counter);
      const fields=document.createElement('div');fields.className='slide-fields';const label=document.createElement('label');label.textContent='Texte à l’écran';const caption=document.createElement('textarea');caption.rows=3;caption.maxLength=cinematic?100:700;caption.value=cinematic?(slide.on_screen_text||''):slide.caption;caption.setAttribute('aria-label',`Texte de la slide ${index+1}`);caption.oninput=()=>{if(cinematic)slide.on_screen_text=caption.value;else slide.caption=caption.value;dirty();};label.append(caption);if(cinematic){const narration=document.createElement('details');narration.className='shot-narration';const summary=document.createElement('summary');summary.textContent='Passage de voix off associé';const text=document.createElement('p');text.textContent=slide.caption;narration.append(summary,text);fields.append(narration);}
      const controls=document.createElement('div');controls.className='slide-controls';const pageLabel=document.createElement('label');pageLabel.textContent='Page d’inspiration';const select=document.createElement('select');project.pages.forEach((p,i)=>select.add(new Option(p.title,String(i))));select.value=slide.page_index;select.onchange=()=>{slide.page_index=Number(select.value);img.alt='Page d’inspiration modifiée. Actualisez la scène pour voir le résultat.';dirty();};pageLabel.append(select);
      const durationLabel=document.createElement('label');durationLabel.textContent='Durée (s)';const duration=document.createElement('input');duration.type='number';duration.min='.5';duration.max='300';duration.step='.1';duration.value=slide.duration.toFixed(1);duration.setAttribute('aria-label',`Durée de la slide ${index+1}`);duration.oninput=()=>{slide.duration=Number(duration.value);dirty();};durationLabel.append(duration);
      const order=document.createElement('div');order.className='slide-order';for(const [text,title,offset] of [['↑','Monter',-1],['↓','Descendre',1],['×','Supprimer',0]]){const button=document.createElement('button');button.type='button';button.textContent=text;button.title=title;button.setAttribute('aria-label',`${title} la slide ${index+1}`);button.disabled=offset===-1?index===0:offset===1?index===project.slides.length-1:project.slides.length===1;if(!offset)button.className='delete-slide';button.onclick=()=>{if(offset){const target=index+offset;[project.slides[index],project.slides[target]]=[project.slides[target],project.slides[index]];}else project.slides.splice(index,1);dirty();drawSlides();};order.append(button);}
      const layoutLabel=document.createElement('label');layoutLabel.textContent=cinematic?'Placement du texte':'Composition';const layoutSelect=document.createElement('select');const layouts=cinematic?{left:'Texte à gauche',center:'Texte centré',right:'Texte à droite',none:'Image seule'}:project.layouts||{intro:'Accroche',spotlight:'Bénéfice',editorial:'Éditorial',statement:'Message fort',cta:'Appel à l’action',website:'Site en situation'};Object.entries(layouts).forEach(([value,name])=>layoutSelect.add(new Option(name,value)));layoutSelect.value=cinematic?(slide.text_position||'left'):(slide.layout||'intro');layoutSelect.setAttribute('aria-label',`Composition de la scène ${index+1}`);layoutSelect.onchange=()=>{if(cinematic)slide.text_position=layoutSelect.value;else slide.layout=layoutSelect.value;dirty();};layoutLabel.append(layoutSelect);controls.append(pageLabel,durationLabel,layoutLabel,order);fields.append(label,controls);card.append(thumb,fields);$('slides-list').append(card);
    });$('add-slide').disabled=project.slides.length>=8;
  }
  async function refreshHistory() {try{const epoch=state.epoch;const context=await api('/api/video-ads/leads/'+$('video-lead').value);if(epoch===state.epoch)drawHistory(context.projects);}catch{}}
  function showProject(project) {
    state.project=project;$('video-client-note').textContent=project.creative_direction?.note||'';$('video-client-note').hidden=!project.creative_direction?.note;updatePreparation();updateURL();$('story-empty').hidden=true;$('project-badge').textContent=(labels[project.status]||project.status).toLocaleUpperCase('fr');
    const busy=['preparing','rendering'].includes(project.status);$('project-progress').hidden=!busy;$('progress-label').textContent=labels[project.status];$('progress-value').textContent=project.progress+' %';$('progress-bar').value=project.progress;
    $('project-error').hidden=!project.error;$('project-error').textContent=project.error||'';$('storyboard').hidden=busy||project.status==='failed'&&project.pages.length===0;
    $('video-result').hidden=project.status!=='completed';
    if(!busy){drawSlides();if(project.status==='completed'){$('final-video').src=project.video_url;$('download-video').href=project.video_url;$('download-video').download=`video-ads-${project.lead_id}.mp4`;$('result-format').textContent={portrait:'1080 × 1920',landscape:'1920 × 1080',square:'1080 × 1080'}[project.format];}}
    clearTimeout(state.timer);if(busy){const epoch=state.epoch;state.timer=setTimeout(()=>poll(project.id,epoch),1400);}else refreshHistory();
  }
  async function poll(id,epoch){try{const project=await api('/api/video-ads/'+id);if(epoch===state.epoch&&state.project?.id===id)showProject(project);}catch(error){if(epoch===state.epoch){notice(error.message+' · nouvelle tentative dans 5 secondes');state.timer=setTimeout(()=>poll(id,epoch),5000);}}}
  async function loadProject(id){try{const epoch=state.epoch;const project=await api('/api/video-ads/'+id);if(epoch!==state.epoch)return;if(project.lead_id!==Number($('video-lead').value))throw new Error('Ce projet appartient à un autre lead.');$('video-audio').value=project.audio_id;$('video-visual-mode').value=project.visual_mode||'graphic';$('video-client-instructions').value=project.client_instructions||'';updateAudio();showProject(project);}catch(error){notice(error.message);}}
  $('video-lead').onchange=async()=>{if(scopedStudio){location.href=$('video-lead').value?'/leads/'+$('video-lead').value+'/video-ads':'/video-ads';return;}history.replaceState(null,'','/video-ads'+($('video-lead').value?'?lead_id='+$('video-lead').value:''));await loadContext();};
  $('video-audio').onchange=()=>{updateAudio();if(state.project&&$('video-audio').value!==state.project.audio_id)notice('Pour utiliser ce nouvel audio, préparez un nouveau slideshow.');};
  document.querySelectorAll('[data-format]').forEach(button=>button.onclick=()=>{state.format=button.dataset.format;document.querySelectorAll('[data-format]').forEach(b=>{const selected=b===button;b.classList.toggle('chosen',selected);b.setAttribute('aria-pressed',String(selected));});});
  $('prepare-video').onclick=async()=>{
    const missing=prerequisite();if(missing){preparationMessage(missing,true);notice(missing);if(!$('video-lead').value)$('video-lead').focus();else if(state.context&&!selectedAudio())$('video-audio').focus();return;}
    const epoch=state.epoch;state.submitting=true;updatePreparation();
    $('story-empty').hidden=true;$('storyboard').hidden=true;$('video-result').hidden=true;$('project-error').hidden=true;$('project-progress').hidden=false;$('project-badge').textContent='DÉMARRAGE';$('progress-label').textContent='Envoi de la demande de préparation…';$('progress-value').textContent='0 %';$('progress-bar').value=0;
    $('project-progress').scrollIntoView({behavior:'smooth',block:'center'});
    try{const project=await api('/api/video-ads/prepare',{lead_id:Number($('video-lead').value),audio_id:$('video-audio').value,format:state.format,visual_mode:$('video-visual-mode').value,client_instructions:$('video-client-instructions').value});if(epoch===state.epoch){showProject(project);notice('Création des scènes originales à partir du style du site.');}}
    catch(error){if(epoch===state.epoch){$('project-progress').hidden=true;$('project-error').hidden=false;$('project-error').textContent=error.message;$('project-badge').textContent='PRÉPARATION IMPOSSIBLE';state.project=null;preparationMessage(error.message,true);notice(error.message);}}
    finally{if(epoch===state.epoch){state.submitting=false;updatePreparation();if(!$('project-error').hidden)preparationMessage($('project-error').textContent,true);}}
  };
  $('add-slide').onclick=()=>{if(state.project.slides.length>=8)return;state.project.slides.push({page_index:0,caption:$('video-visual-mode').value==='cinematic'?(state.project.slides.at(-1)?.caption||''):'',on_screen_text:'',duration:3,layout:'spotlight'});dirty();drawSlides();};
  async function submitStoryboard(previewOnly=false){
    if($('video-visual-mode').value==='cinematic'&&state.project.slides.some(s=>(s.on_screen_text||'').length>100||(s.on_screen_text||'').trim().split(/\s+/).filter(Boolean).length>7)){notice('Gardez au maximum 7 mots et 100 caractères par plan à l’écran.');return;}
    if(state.project.slides.some(s=>!s.caption.trim()||s.caption.length>700||!Number.isFinite(s.duration)||s.duration<.5||s.duration>300)){notice('Vérifiez les textes et les durées de vos scènes.');return;}
    const button=$(previewOnly?'refresh-scenes':'render-video'),epoch=state.epoch;button.disabled=true;
    try{const project=await api('/api/video-ads/'+state.project.id+'/render',{slides:state.project.slides,preview_only:previewOnly,visual_mode:$('video-visual-mode').value,client_instructions:$('video-client-instructions').value});if(epoch===state.epoch)showProject(project);}catch(error){notice(error.message);}finally{button.disabled=false;}
  }
  $('render-video').onclick=()=>submitStoryboard();
  $('refresh-scenes').onclick=()=>submitStoryboard(true);

  const toBase64=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Fichier illisible.'));reader.readAsDataURL(file);});
  $('save-existing').onclick=async()=>{const file=$('existing-audio').files[0],script=$('existing-script').value.trim(),lead=Number($('video-lead').value);if(!file||file.size>20*1024*1024||!script){notice('Choisissez un audio de 20 Mo maximum et renseignez son texte de voix off.');return;}const button=$('save-existing'),epoch=state.epoch;button.disabled=true;try{const audio=await api('/api/ads/audio',{lead_id:lead,script,audio:await toBase64(file)});if(epoch===state.epoch){await loadContext(audio.id);notice('Audio et texte associés à ce lead.');}}catch(error){notice(error.message);}finally{button.disabled=false;}};
  $('generate-video-message').onclick=async()=>{
    const lead=$('video-lead').value,original=$('video-copy-text').value;if(!lead){notice('Sélectionnez un prospect pour préparer son message.');return;}
    const button=$('generate-video-message');button.disabled=true;button.textContent='L’IA prépare votre message…';
    try{const result=await api('/api/ads/message',{lead_id:Number(lead),tone:$('video-copy-tone').value,duration:Number($('video-copy-duration').value),details:$('video-copy-details').value},150000);if($('video-lead').value!==lead||$('video-copy-text').value!==original){notice('Le profil ou le texte a changé. Relancez la génération pour conserver vos modifications.');return;}$('video-copy-text').value=result.script;$('video-copy-meta').textContent=`OpenAI · environ ${result.estimated_duration} s · relisez et ajustez avant la voix off`;$('use-video-message').disabled=false;notice('Votre message personnalisé est prêt.');}catch(error){notice(error.message);}finally{button.disabled=false;button.textContent='✦ Générer mon message';}
  };
  $('video-copy-text').oninput=()=>{$('use-video-message').disabled=!$('video-copy-text').value.trim();$('video-copy-meta').textContent=$('video-copy-text').value===(selectedAudio()?.script||'')?'Message conservé avec cet audio · utilisé pour préparer les slides.':'Nouveau brouillon : créez sa voix off pour utiliser ce texte avec un nouvel audio.';};
  $('restore-audio-message').onclick=()=>loadAudioMessage();
  $('use-video-message').onclick=()=>{const lead=$('video-lead').value,text=$('video-copy-text').value.trim();if(!lead||!text)return;try{sessionStorage.setItem('ads-message-'+lead,text);location.href='/ads?lead_id='+lead+'&message_draft=1';}catch{notice('Le stockage du navigateur est indisponible. Copiez le texte dans Ads pour créer sa voix off.');}};
  $('video-visual-mode').onchange=()=>{updatePreparation();if(state.project){dirty();drawSlides();}};
  updatePreparation();
  const params=new URLSearchParams(location.search), initialLead=params.get('lead_id')||$('video-lead').dataset.selectedLead;
  if(initialLead&&Array.from($('video-lead').options).some(o=>o.value===initialLead)){
    $('video-lead').value=initialLead;
    loadContext(params.get('audio_id')).then(()=>{
      if(params.get('project_id'))loadProject(params.get('project_id'));
      else if(scopedStudio&&!params.has('audio_id')&&!params.has('new')&&state.context?.projects.length)loadProject(state.context.projects[0].id);
    });
  }
})();
