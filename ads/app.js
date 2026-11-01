const $ = id => document.getElementById(id);
const state = { voice: null, music: null, voiceURL: null, mixURL: null, mixBlob: null, exportScript: null, voiceScript: null, exportLeadId: null };
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.remove('show'), 5500); }
function bars(selector, count, scale) { const el = document.querySelector(selector); for(let i=0;i<count;i++){const bar=document.createElement('i');bar.style.height=`${(0.15+Math.abs(Math.sin(i*1.7)*Math.cos(i*.31))*.85)*scale}px`;el.append(bar);} }
bars('.orb-bars', 19, 64); bars('.mix-wave', 65, 31);
function countWords(){const count=$('ad-text').value.trim().split(/\s+/).filter(Boolean).length;$('word-count').textContent=`${count} mots · ≈ ${Math.round(count/2.5)} s`;}
function invalidateMix(){if(state.mixURL) URL.revokeObjectURL(state.mixURL);state.mixURL=null;state.mixBlob=null;$('save-video-audio').hidden=true;$('mix-player').pause();$('mix-player').removeAttribute('src');$('mix-player').hidden=true;$('download').hidden=true;}
function setVoice(blob, name){invalidateMix();if(state.voiceURL)URL.revokeObjectURL(state.voiceURL);state.voice=blob;state.voiceURL=URL.createObjectURL(blob);$('voice-player').src=state.voiceURL;$('voice-player').hidden=false;$('voice-filename').textContent=name;}
$('ad-text').addEventListener('input',countWords);
$('generate-text').addEventListener('click',()=>{
 const company=$('company').value.trim(), activity=$('activity').value.trim(), city=$('city').value.trim(), details=$('details').value.trim();
 if(!company||!activity){toast('Renseignez le nom et l’activité de votre entreprise.');return;}
 const openings={warm:`Et si votre prochaine belle découverte se trouvait${city?' à '+city:' tout près de vous'} ?`,bold:`Envie de nouveauté${city?' à '+city:''} ? Faites place à ${company} !`,premium:`Découvrez une autre idée de ${activity.toLowerCase()}${city?', à '+city:''}.`};
 const duration=Number($('duration').value);const intro=duration===15?`Découvrez ${company}${city?', à '+city:''}.`:openings[$('tone').value]+` ${company}, ${activity.toLowerCase()}.`;
 $('ad-text').value=intro+(details?' '+details:'')+(duration===45?' Prenez le temps de découvrir notre univers et de trouver ce qui vous ressemble.':'')+` Contactez ${company} pour en savoir plus.`;
 countWords();toast('Votre proposition est prête. Ajustez le texte et sa durée avant la voix off.');
});
$('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('ad-text').value);toast('Script copié.');}catch{toast('Sélectionnez le texte pour le copier dans votre navigateur.');}});
for(const kind of ['voice','music']) $(kind+'-file').addEventListener('change',event=>{const file=event.target.files[0];if(!file)return;if(file.size>20*1024*1024){toast('Ce fichier dépasse la limite de 20 Mo.');event.target.value='';return;}if(!file.type.startsWith('audio/')&&!/\.(mp3|wav|m4a|ogg|flac|aac|webm)$/i.test(file.name)){toast('Choisissez un fichier audio.');event.target.value='';return;}if(kind==='voice'){setVoice(file,file.name);state.voiceScript=null;}else{state.music=file;$('music-filename').textContent=file.name;invalidateMix();}toast(kind==='voice'?'Voix off importée.':'Musique importée.');});
for(const kind of ['voice','music']) $(kind+'-volume').addEventListener('input',()=>{$(kind+'-value').textContent=$(kind+'-volume').value+' %';invalidateMix();});
$('duck').addEventListener('change',invalidateMix);
async function request(url, data){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!response.ok){let error;try{error=await response.json();}catch{error={error:'Le serveur ne répond pas correctement.'};}throw new Error(error.error||'La requête a échoué.');}return response.blob();}
async function busy(id, operation){const button=$(id),original=button.innerHTML;button.disabled=true;button.textContent='Traitement en cours…';try{await operation();}catch(error){toast(error.message);}finally{button.disabled=false;button.innerHTML=original;}}
$('generate-voice').addEventListener('click',()=>busy('generate-voice',async()=>{
 const provider=$('voice-provider').value;
 if(!$('ad-text').value.trim())throw new Error('Préparez votre texte publicitaire avant de générer la voix.');
 if(provider==='elevenlabs'&&!$('voice-id').value.trim())throw new Error('Renseignez un identifiant de voix ElevenLabs.');
 const voiceScript=$('ad-text').value;
 const blob=await request('/api/voice',{provider,text:voiceScript,voice:$('openai-voice').value,instructions:$('voice-instructions').value,voice_id:$('voice-id').value.trim()});
 setVoice(blob,provider==='openai'?'Voix OpenAI.mp3':'Voix ElevenLabs.mp3');state.voiceScript=voiceScript;toast('Voix off générée. Écoutez-la avant le mixage.');
}));
function base64(blob){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Impossible de lire le fichier audio.'));reader.readAsDataURL(blob);});}
$('export').addEventListener('click',()=>busy('export',async()=>{if(!state.voice)throw new Error('Générez ou importez une voix off pour créer votre spot.');const voice=state.voice,music=state.music,script=state.voiceScript||$('ad-text').value,leadId=$('ads-lead').value;const data={voice:await base64(voice),music:music?await base64(music):null,voice_volume:Number($('voice-volume').value)/100,music_volume:Number($('music-volume').value)/100,duck:$('duck').checked};const blob=await request('/api/mix',data);invalidateMix();state.mixBlob=blob;state.exportScript=script;state.exportLeadId=leadId;state.mixURL=URL.createObjectURL(blob);$('save-video-audio').hidden=false;$('mix-player').src=state.mixURL;$('mix-player').hidden=false;$('download').href=state.mixURL;$('download').download=($('company').value.trim().replace(/[^\p{L}\p{N}-]+/gu,'-')||'publicite')+'-ads.mp3';$('download').hidden=false;toast('Votre spot audio est prêt à être écouté et téléchargé.');}));
document.querySelectorAll('.step').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('.step').forEach(el=>el.classList.remove('selected'));button.classList.add('selected');$(button.dataset.target).scrollIntoView({behavior:'smooth',block:'start'});}));
$('reset').addEventListener('click',()=>{if(($('ad-text').value||state.voice||state.music)&&!confirm('Effacer le projet en cours ? Les fichiers téléchargés seront conservés.'))return;invalidateMix();if(state.voiceURL)URL.revokeObjectURL(state.voiceURL);state.voice=null;state.music=null;state.voiceURL=null;state.voiceScript=null;$('voice-player').pause();$('voice-player').removeAttribute('src');$('voice-player').hidden=true;for(const id of ['company','activity','city','details','ad-text','voice-file','music-file'])$(id).value='';$('voice-filename').textContent='Importer une voix off';$('music-filename').textContent='Ajouter une musique de fond';$('voice-volume').value=100;$('music-volume').value=18;$('voice-value').textContent='100 %';$('music-value').textContent='18 %';$('duck').checked=true;$('ads-lead').value='';$('voice-provider').value='openai';$('openai-voice').value='coral';$('voice-id').value='';updateProvider();countWords();$('company').focus();toast('Votre nouveau projet est prêt.');});
let providerStatus=null;
function updateProvider(){
 const isOpenAI=$('voice-provider').value==='openai';
 $('openai-options').hidden=!isOpenAI;$('elevenlabs-options').hidden=isOpenAI;
 $('voice-provider-label').textContent=isOpenAI?'OpenAI':'ElevenLabs';
 if(providerStatus){const name=isOpenAI?'OpenAI':'ElevenLabs';$('connection-status').textContent=providerStatus[isOpenAI?'openai':'elevenlabs']?name+' · clé configurée':name+' · clé non configurée, import audio disponible';}
}
$('voice-provider').addEventListener('change',updateProvider);
fetch('/api/status').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(status=>{providerStatus=status;updateProvider();if(!status.ffmpeg){$('export').disabled=true;$('export').textContent='FFmpeg requis pour le mixage';}}).catch(()=>{$('connection-status').textContent='Serveur indisponible · démarrez ProfileFinder';});
updateProvider();countWords();

$('save-video-audio').addEventListener('click',()=>busy('save-video-audio',async()=>{
 if(!state.mixBlob)throw new Error('Créez votre spot audio avant de l’enregistrer.');
 if(!$('ads-lead').value||$('ads-lead').value!==state.exportLeadId)throw new Error('Sélectionnez un lead, puis recréez le mix pour l’associer à ce profil.');
 if(!state.exportScript?.trim())throw new Error('Renseignez le texte exact de la voix off, puis recréez le mix.');
 const response=await fetch('/api/ads/audio',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lead_id:Number(state.exportLeadId),script:state.exportScript,audio:await base64(state.mixBlob)})});
 const audio=await response.json();if(!response.ok)throw new Error(audio.detail||'Enregistrement impossible.');
 location.href='/video-ads?lead_id='+audio.lead_id+'&audio_id='+audio.id;
}));
fetch('/api/ads/leads').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(leads=>{
 leads.forEach(lead=>$('ads-lead').add(new Option(lead.name+(lead.city?' · '+lead.city:''),String(lead.id))));
 function applyLead(){const lead=leads.find(l=>String(l.id)===$('ads-lead').value);invalidateMix();state.voiceScript=null;if(state.voiceURL)URL.revokeObjectURL(state.voiceURL);state.voiceURL=null;state.voice=null;$('voice-player').pause();$('voice-player').removeAttribute('src');$('voice-player').hidden=true;$('voice-filename').textContent='Importer une voix off';$('ad-text').value='';countWords();if(lead){$('company').value=lead.name;$('activity').value=lead.activity.replaceAll('_',' ');$('city').value=lead.city;$('details').value='';$('ads-lead-status').textContent='Audio et script pourront être sauvegardés pour ce lead.';}else $('ads-lead-status').textContent='Choisissez un lead pour réutiliser votre audio dans Video Ads.';}
 $('ads-lead').addEventListener('change',applyLead);
 const leadId=new URLSearchParams(location.search).get('lead_id');if(leads.some(l=>String(l.id)===leadId)){$('ads-lead').value=leadId;applyLead();}
 if(!leads.length)$('ads-lead-status').textContent='Ajoutez un prospect pour créer une annonce liée à son profil.';
}).catch(()=>{$('ads-lead-status').textContent='Liste des leads indisponible dans ce serveur. Utilisez l’application complète.';});
