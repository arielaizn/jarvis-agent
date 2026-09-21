import {Galaxy, cameraPlan} from './galaxy.js';
import {Organs} from './organs.js';
import {routeCommand, prettyModel, DEFAULT_FOCUS_MINUTES} from './commands.js';
import {EMBEDDED,connectNative,nativeBridge} from './native.js';
import {TaskPool,isTaskStop,isNotesQuestion} from './task-client.js';

const STATE_POLL_MS=1000;
const RECOGNITION_RESTART_MS=180;
const MUTED=new URLSearchParams(location.search).get('mute')==='1';
const DEBUG=new URLSearchParams(location.search).get('focusdebug')==='1';
const PROBE=new URLSearchParams(location.search).get('focusprobe')==='1';
const SESSION_ID=sessionStorage.getItem('jarvis-galaxy-session')||crypto.randomUUID();
sessionStorage.setItem('jarvis-galaxy-session',SESSION_ID);
const $=selector=>document.querySelector(selector);
const state={ready:false,busy:false,switching:false,ears:false,earRequests:0,speaking:false,focus:{},model:'',provider:'',brainEpoch:0,noteContext:false,quietUntil:0,recognition:null,recognitionActive:false,polling:false,sse:false};
let galaxy;
function applyCapture(result){
  const node=result.node||result.graph?.nodes?.[result.node_id];
  if(!node||!result.graph)return;
  const existing=galaxy.nodes[node.id];
  const alreadyIndexed=existing&&existing.label===node.label;
  galaxy.update(result.graph,alreadyIndexed?null:{...result,node});
}

export async function api(path,payload) {
  const response=await fetch(path,{method:payload===undefined?'GET':'POST',cache:'no-store',headers:payload===undefined?{}:{'Content-Type':'application/json'},body:payload===undefined?undefined:JSON.stringify(payload)});
  let data;
  try{data=await response.json();}catch{throw new Error('השרת החזיר תשובה שאינה תקינה.');}
  if(!response.ok){const error=new Error(data.error?.message||data.answer||data.error||`הבקשה נכשלה (${response.status}).`);error.code=data.error?.code;error.status=response.status;throw error;}
  return data;
}

function setStatus(text,busy=false){$('#assistant-status').textContent=text;$('#assistant-dot').style.opacity=busy?'.4':'1';}
function showText(text,error=false){if(!text)return;$('#answer').textContent=text;$('#answer').classList.toggle('is-error',error);}
function recognitionStart(){
  if(!state.ears||state.speaking||state.recognitionActive||!state.recognition)return;
  try{state.recognition.lang=$('#speech-language').value;state.recognition.start();}catch{}
}
let voiceAudio=null,voiceGeneration=0,ackAudio=null;
if(!MUTED&&!EMBEDDED)api('/ack').then(result=>{ackAudio=result.audio;}).catch(()=>{});
function acknowledge(){
  if(MUTED)return;
  if(EMBEDDED&&nativeBridge()?.acknowledge)nativeBridge().acknowledge();
  else speak('מייד, אדוני. מתחיל לטפל בבקשה.','ack',ackAudio);
}
function stopSpeech(){voiceGeneration++;if(voiceAudio){voiceAudio.pause();voiceAudio.src='';voiceAudio=null;}state.speaking=false;}
async function speak(text,kind='answer',audio=null){
  if(!text||MUTED)return;
  if(EMBEDDED){
    const bridge=nativeBridge();
    if(audio&&bridge?.playAudio)bridge.playAudio(audio);
    else if(bridge?.say)bridge.say(String(text),kind);
    else setStatus('החיבור לקול של האפליקציה אינו זמין');
    return;
  }
  stopSpeech();const generation=voiceGeneration;
  state.speaking=true;
  if(state.recognitionActive)state.recognition?.abort();
  const finish=()=>{if(generation===voiceGeneration){state.speaking=false;setTimeout(recognitionStart,RECOGNITION_RESTART_MS);}};
  try{
    const source=audio||(await api('/speech',{text:String(text).slice(0,2400)})).audio;
    if(generation!==voiceGeneration)return;
    if(typeof source!=='string'||!source.startsWith('data:audio/wav;base64,'))throw new Error();
    voiceAudio=new Audio(source);voiceAudio.onended=finish;
    voiceAudio.onerror=()=>{setStatus('השמעת הקול נכשלה');finish();};
    await voiceAudio.play();
  }catch{if(generation===voiceGeneration){setStatus('הקול של Gemini 3.8 Live אינו זמין כרגע');finish();}}
}
function fail(message){showText(message,true);setStatus('צריך לבדוק משהו');speak(message);}
function answer(response){
  if(response.model&&response.intent!=='task')setModel(response);
  if(response.answer)showText(response.answer);
  const plan=galaxy?.prove(response)||{mode:'none',nodes:[]};
  if(plan.mode==='cluster'){$('#note-panel').hidden=true;document.body.classList.remove('showing-note');}
  const chips=$('#source-chips');chips.replaceChildren();
  for(const id of plan.nodes){const node=galaxy.nodes[id];const button=document.createElement('button');button.className='source-chip';button.textContent=node.label;button.addEventListener('click',()=>galaxy.select(id));chips.append(button);}
  const spoken=response.intent==='task'?String(response.answer||'').split(/(?<=[.!?])\s+|\n+/).slice(0,3).join(' ').slice(0,600):response.answer;
  speak(spoken,'answer',response.audio||null);
  setStatus(plan.mode==='cluster'?`${plan.nodes.length} מקורות מוארים`:plan.mode==='single'?'המקור פתוח לידך':'אני כאן');
}
function noteSelected(node,neighbours){
  $('#note-group').textContent=node.group;$('#note-title').textContent=node.label;$('#note-excerpt').textContent=node.excerpt||'';$('#note-panel').hidden=false;
  document.body.classList.add('showing-note');
  const links=$('#note-links');links.replaceChildren();
  for(const other of neighbours.slice(0,8)){const button=document.createElement('button');button.textContent=other.label;button.addEventListener('click',()=>galaxy.select(other.id));links.append(button);}
  if(neighbours.length>8){const more=document.createElement('span');more.className='tiny';more.textContent=`ועוד ${neighbours.length-8} הערות מקושרות`;links.append(more);}
}
function graphChanged(nodes,colors){
  const count=nodes.length;$('#empty-state').hidden=count>0;
  const links=galaxy?.inspection();
  $('#graph-summary').textContent=count?`${count.toLocaleString('he-IL')} הערות · ${colors.size} תיקיות${links&&links.linkCount>links.visibleLinkCount?` · ${links.visibleLinkCount.toLocaleString('he-IL')} מתוך ${links.linkCount.toLocaleString('he-IL')} קשרים מוצגים`:''}`:'תיקיית ההערות עדיין לא מחוברת';
  const groups=$('#groups');groups.replaceChildren();
  const counts=new Map();nodes.forEach(node=>counts.set(node.group,(counts.get(node.group)||0)+1));
  for(const [name,count] of [...counts].sort((a,b)=>b[1]-a[1]).slice(0,7)){
    const row=document.createElement('span');row.className='group-item';
    const dot=document.createElement('span');dot.className='group-dot';dot.style.background=galaxy.color(name);
    const label=document.createElement('span');label.textContent=`${name} · ${count.toLocaleString('he-IL')}`;row.append(dot,label);groups.append(row);
  }
}
function setModel(data){
  if(data.provider&&state.provider&&data.provider!==state.provider){
    state.brainEpoch++;tasks.invalidate();state.busy=false;$('#send-button').disabled=state.switching;$('#task-panel').hidden=true;
  }
  state.provider=data.provider||state.provider;
  state.model=data.model||state.model;
  const codex=state.provider==='codex';
  $('#model-label').textContent=codex?'Codex · GPT 6 Astra · High':data.model_label||prettyModel(state.model);
  $('#brain-mode-label').textContent=codex?'Codex High · קול ומסך: Gemini 3.8 Live':'Gemini 3.8 Flash · קול ומסך: Gemini 3.8 Live';
  $('#brain-codex').setAttribute('aria-pressed',String(codex));
  $('#brain-gemini').setAttribute('aria-pressed',String(state.provider==='gemini'));
  $('#model-form').hidden=codex;$('#model-options').hidden=codex;
  updateQuestionHint();
}

function updateQuestionHint(){
  $('#question').placeholder=(state.focus.intent_window||state.focus.intent_window_open)?'על מה עובדים? כתוב או אמור לי':$('#notes-mode').checked?'מה תרצה לדעת מתוך ההערות שלך?':state.provider==='codex'?'מה לעשות בשבילך? אפשר לדבר או להקליד':'מה תרצה לדעת? אפשר גם: תזכור ש...';
}

const taskCards=new Map();
function taskProgress(task){
  $('#task-panel').hidden=false;
  const key=task.observer||task.id||'status';
  let card=taskCards.get(key);
  if(!card){
    card=document.createElement('div');card.className='agent-task';
    const detail=document.createElement('div');detail.className='task-detail';
    const title=document.createElement('strong'),progress=document.createElement('span'),result=document.createElement('p');
    detail.append(title,progress,result);
    const stop=document.createElement('button');stop.type='button';stop.textContent='עצור';
    card.append(detail,stop);$('#agent-tasks').prepend(card);
    card.parts={title,progress,result,stop};taskCards.set(key,card);
    // Keep active cards; bound completed display history.
    for(const [oldKey,old] of taskCards){if(taskCards.size<=20)break;if(old.dataset.terminal==='true'){old.remove();taskCards.delete(oldKey);}}
  }
  const terminal=['completed','failed','cancelled'].includes(task.status);
  card.dataset.terminal=String(terminal);
  const labels={queued:'בתור',running:'עובד',completed:'הסתיים',failed:'נכשל',cancelled:'נעצר'};
  card.parts.title.textContent=`${task.agent?'סוכן '+task.agent:'משימה'} · ${labels[task.status]||'מתחבר'} · ${String(task.title||'').slice(0,120)}`;
  card.parts.progress.textContent=String(task.progress||'').slice(0,500);
  if(terminal)card.parts.result.textContent=task.answer||'';
  card.parts.stop.hidden=terminal;card.parts.stop.disabled=!!task.stopping||!task.id;
  if(task.id)card.parts.stop.onclick=()=>cancelTask(task.id);
  $('#task-status').textContent='סוכנים ומשימות';
  $('#task-progress').textContent='עד 3 סוכנים במקביל. שליטה במחשב עוברת בתור.';
  $('#cancel-task').disabled=!tasks.active;
}
const tasks=new TaskPool({api,onUpdate:taskProgress});
async function runTask(text,resumeId=null){
  const epoch=state.brainEpoch;
  const mode=!resumeId&&$('#task-mode').value==='background'?'background':null;
  const result=await tasks.run(text,SESSION_ID,resumeId,mode);
  if(!result||epoch!==state.brainEpoch)return;
  if(result.status==='completed')answer({...result,nodes:[],note_question:false,camera:'none'});
  else if(result.status==='cancelled'){showText(result.answer);speak(result.answer);}
  else fail(result.error?.message||result.answer||'אדוני, המשימה נכשלה.');
}
function resumeTask(id){
  if(state.switching||tasks.has(id))return;
  const epoch=state.brainEpoch;
  runTask('',id).catch(error=>{if(epoch===state.brainEpoch)fail(error.message);});
}
async function cancelTask(id=null){
  if(!tasks.active)return;
  try{await tasks.stop(id);}catch{fail('אדוני, בקשת העצירה לא אושרה. אפשר לנסות שוב.');}
}
async function changeBrain(provider){
  state.switching=true;$('#send-button').disabled=true;
  $('#brain-codex').disabled=true;$('#brain-gemini').disabled=true;$('#model-error').textContent='';
  try{
    const result=await api('/brain',{provider});
    // A repeated selection also replaces the server task manager.
    state.brainEpoch++;tasks.invalidate();state.busy=false;$('#task-panel').hidden=true;
    setModel(result);answer(result);
  }catch(error){$('#model-error').textContent=error.message;}
  finally{state.switching=false;$('#send-button').disabled=state.busy;$('#brain-codex').disabled=false;$('#brain-gemini').disabled=false;}
}
function organsChanged(organState){
  $('#share-indicator').hidden=!organState.screen_sharing;$('#share-label').textContent=organState.screen_watch?'שמירה על כל המסך פעילה':'שיתוף מסך פעיל';
  $('#camera-indicator').hidden=!organState.webcam;
  $('#screen-button').setAttribute('aria-pressed',String(organState.screen_sharing));$('#watch-button').setAttribute('aria-pressed',String(organState.screen_watch));$('#camera-button').setAttribute('aria-pressed',String(organState.webcam));
  $('#privacy-label').textContent=organState.webcam?'זיהוי תנוחה מקומי; תמונה נשלחת רק בבקשה מפורשת':organState.screen_sharing?'תמונה נשלחת כששואלים או אחרי דקת מסך קבוע בשמירה':state.ears?'המיקרופון פעיל':'מצלמה ומיקרופון כבויים';
  updateDebug();
}
const organs=new Organs({api,answer,say:speak,fail,earsOn:()=>state.ears,onChange:organsChanged,quietUntil:()=>state.quietUntil});

function focusState(data){
  state.focus=data.focus||data;
  const focus=state.focus;
  if(focus.relief_remaining||focus.snooze_remaining)state.quietUntil=Math.max(state.quietUntil,Date.now()+Math.max(focus.relief_remaining||0,focus.snooze_remaining||0)*1000);
  const active=!!(focus.on??focus.active);
  $('#focus-card').hidden=!active;
  $('#focus-button').classList.toggle('active',active);
  $('#focus-card').classList.toggle('is-drifting',!!focus.drifting);
  const remaining=Math.max(0,Math.ceil(focus.seconds_remaining??focus.remaining_seconds??0));
  $('#focus-timer').textContent=`${Math.floor(remaining/60).toString().padStart(2,'0')}:${(remaining%60).toString().padStart(2,'0')}`;
  $('#focus-status').textContent=focus.paused?'בהשהיה':focus.deferred?'מחכה לנעילת יעד':focus.drifting?'חוזרים לעבודה':'מפגש ריכוז';
  $('#focus-detail').textContent=focus.deferred?'עבור לחלון העבודה והישאר בו רגע':focus.intent_window?'על מה עובדים? אפשר לומר או להקליד':focus.excused?'היציאה אושרה עד החזרה ליעד':`${focus.drifts||0} יציאות מהעבודה · רצף ${focus.streak||0}`;
  $('#focus-pause').textContent=focus.paused?'המשך':'השהיה';
  updateQuestionHint();
  updateDebug();
}
function updateDebug(diag){
  if(!DEBUG)return;
  const flags={};
  for(const [name,value]of Object.entries(state.focus))if(typeof value==='boolean'||typeof value==='number')flags[name]=value;
  const organState=organs.state();
  Object.assign(flags,{mic_enabled:state.ears,intent_window_open:!!(state.focus.intent_window||state.focus.intent_window_open),last_pixel_diff:organState.last_pixel_diff,watch_gate:organState.watch_gate,sse_connected:state.sse});
  if(diag)flags.diag=diag;
  $('#debug-content').textContent=JSON.stringify(flags,null,2);
}
async function focusAction(action,payload={}){
  if(action==='relief')state.quietUntil=Date.now()+180000;
  if(action==='snooze')state.quietUntil=Date.now()+(payload.seconds||15)*1000;
  const result=await api(`/focus/${action}`,payload);focusState(result);return result;
}
async function changeModel(name){
  const result=await api('/model',{name});setModel(result);answer(result);$('#model-dialog').close();return result;
}
async function submit(raw){
  const text=String(raw||'').trim();if(!text)return;
  // Stop remains reachable by voice while execution is busy.
  if(isTaskStop(text)&&tasks.active){await cancelTask();return;}
  if(state.switching){showText('המוח מתחלף. אפשר לשלוח את הבקשה בעוד רגע.');return;}
  if(state.busy){showText('המשימה עדיין רצה. אפשר לומר ״עצור את המשימה״.');return;}
  const epoch=state.brainEpoch;
  state.busy=true;$('#send-button').disabled=true;galaxy?.hold();setStatus('מקשיב וחושב',true);
  acknowledge();
  try{
    const command=routeCommand(text,!!(state.focus.on||state.focus.active));
    if(command.type==='focus')await focusAction(command.action,command.payload);
    else if(command.type==='remember'){
      if(!command.text)throw new Error('מה לשמור? התחל ב״תזכור ש״ והוסף את מה שחשוב לך.');
      const result=await api('/remember',{text:command.text});
      if(!result.node||!result.graph)throw new Error('השרת לא אישר שההערה נשמרה ונוספה למפה.');
      applyCapture(result);state.noteContext=true;
      // Birth camera movement is intentional. The confirmation never reads the note.
      showText(result.answer||'נשמר ונוסף לגלקסיה, אדוני.');speak(result.answer||'נשמר ונוסף לגלקסיה, אדוני.');
    }
    else if(command.type==='model')await changeModel(command.name);
    else if(command.type==='watch')await organs.startScreen(true);
    else if(command.type==='screen-start')await organs.startScreen(false);
    else if(command.type==='stop-screen')organs.stopScreen();
    else if(command.type==='camera-start')await organs.startCamera();
    else if(command.type==='camera-stop')organs.stopCamera();
    else if(command.type==='see'){const result=await organs.see(command.question,command.source);if(epoch===state.brainEpoch)answer(result);}
    else if(state.focus.intent_window||state.focus.intent_window_open)await focusAction('intent',{text});
    else if(organs.live(organs.screenStream)&&!command.smalltalk){const result=await organs.see(text,'screen');if(epoch===state.brainEpoch)answer(result);}
    else if(['codex','gemini'].includes(state.provider)&&!$('#notes-mode').checked&&!isNotesQuestion(text,state.noteContext)&&!command.smalltalk){state.noteContext=false;runTask(text).catch(error=>{if(epoch===state.brainEpoch)fail(error.message);});}
    else {const result=await api('/chat',{question:text,session_id:SESSION_ID});if(epoch===state.brainEpoch){if(result.note_question)state.noteContext=true;answer(result);}}
  }catch(error){if(epoch===state.brainEpoch)fail(error.message);}
  finally{if(epoch===state.brainEpoch){state.busy=false;$('#send-button').disabled=false;if($('#assistant-status').textContent==='מקשיב וחושב')setStatus('אני כאן');}}
}

function setupEars(){
  if(EMBEDDED){
    // Native Qt header owns the microphone. Web content cannot enable it.
    $('#ear-button').hidden=true;
    $('#speech-language').closest('label').hidden=true;
    return;
  }
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){$('#ear-button').disabled=true;$('#ear-button').title='זיהוי קולי אינו נתמך בדפדפן הזה';return;}
  const recognition=new Recognition();state.recognition=recognition;recognition.continuous=true;recognition.interimResults=false;
  recognition.onstart=()=>{state.recognitionActive=true;$('#ear-button').textContent='מקשיב';};
  recognition.onend=()=>{state.recognitionActive=false;if(state.ears&&!state.speaking)setTimeout(recognitionStart,RECOGNITION_RESTART_MS);};
  recognition.onresult=event=>{
    if(state.speaking||!state.ears)return;
    for(let i=event.resultIndex;i<event.results.length;i++)if(event.results[i].isFinal){
      const text=event.results[i][0].transcript;
      api('/voice/intent',{text}).then(decision=>{
        if(decision.accepted&&state.ears&&!state.speaking)submit(decision.text||text);
        else if(decision.reason==='use_explicit_address')$('#ear-button').title='אמור ג׳רוויס בתחילת הבקשה';
      }).catch(()=>{});
    }
  };
  recognition.onerror=event=>{
    if(['not-allowed','service-not-allowed','audio-capture'].includes(event.error)){
      state.ears=false;$('#ear-button').setAttribute('aria-pressed','false');$('#ear-button').textContent='מיקרופון כבוי';
      fail('המיקרופון אינו זמין. בדוק את הרשאת המיקרופון של הדפדפן.');
    }else if(event.error==='network'){
      state.ears=false;$('#ear-button').setAttribute('aria-pressed','false');$('#ear-button').textContent='מיקרופון כבוי';
      fail('שירות זיהוי הדיבור של הדפדפן אינו זמין כרגע. אפשר להקליד.');
    }
  };
  $('#ear-button').addEventListener('click',()=>{
    state.earRequests++;
    state.ears=!state.ears;$('#ear-button').setAttribute('aria-pressed',String(state.ears));$('#ear-button').textContent=state.ears?'מפעיל מיקרופון':'מיקרופון כבוי';
    $('#ear-button').title=state.ears?'כיבוי מיקרופון':'הפעלת מיקרופון';
    if(state.ears)recognitionStart();else recognition.abort();organsChanged(organs.state());
  });
  $('#speech-language').addEventListener('change',()=>{if(state.recognitionActive)recognition.abort();});
}
function events(){
  const source=new EventSource('/events');
  source.onopen=async()=>{
    state.sse=true;
    // Reconnect may mean a server restart. Reload its current index ordering.
    if(state.ready)try{galaxy.update(await api('/graph'),null,true);}catch(error){fail(error.message);}
  };source.onerror=()=>{state.sse=false;};
  source.addEventListener('say',event=>{
    try{
      const message=JSON.parse(event.data);
      // Distraction labels exist only in this callback and speech synthesis.
      // Never put transient speech into the answer, DOM, history or logs.
      if(message.text)speak(message.text,message.kind||'focus');
    }catch{}
  });
  source.addEventListener('capture',async event=>{
    try{
      const capture=JSON.parse(event.data);
      if(!Number.isInteger(capture.node_id))return;
      const graph=await api('/graph');
      applyCapture({...capture,graph});
    }catch(error){fail(`ההערה נשמרה, אבל עדכון המפה נכשל: ${error.message}`);}
  });
  source.addEventListener('provenance',event=>{
    try{
      const provenance=JSON.parse(event.data);
      const plan=galaxy?.prove(provenance);
      if(plan?.mode==='cluster'){$('#note-panel').hidden=true;document.body.classList.remove('showing-note');}
    }catch{}
  });
  source.addEventListener('brain',event=>{try{const data=JSON.parse(event.data);state.brainEpoch++;tasks.invalidate();state.busy=false;$('#send-button').disabled=state.switching;$('#task-panel').hidden=true;setModel(data);}catch{}});
  source.addEventListener('fallback',event=>{try{setModel(JSON.parse(event.data));setStatus('אדוני, המכסה של Codex נגמרה. עברתי ל־Gemini.');}catch{}});
  window.addEventListener('pagehide',()=>source.close(),{once:true});
}
async function poll(){
  if(state.polling)return;state.polling=true;
  try{
    const result=await api('/state');setModel(result);if(result.focus)focusState(result.focus);
    // A hidden native Galaxy must not become a second narrator for a HUD task.
    if(['codex','gemini'].includes(result.provider)&&(!EMBEDDED||!document.hidden)){for(const task of result.tasks||[result.task].filter(Boolean))if(!tasks.has(task.id))resumeTask(task.id);}
    $('#connection-status').textContent=result.key_configured?'מחובר':result.provider==='codex'?'נדרשת התחברות ל־Codex':'נדרש מפתח API בשרת';
    if(DEBUG)updateDebug(await api('/focus/diag'));
  }catch{$('#connection-status').textContent='אין חיבור לשרת';}
  finally{state.polling=false;}
}
function bind(){
  $('#mute-label').hidden=!MUTED;$('#focus-debug').hidden=!DEBUG;
  $('#chat-form').addEventListener('submit',event=>{event.preventDefault();const question=$('#question').value;$('#question').value='';submit(question);});
  $('#notes-mode').addEventListener('change',updateQuestionHint);
  $('#cancel-task').addEventListener('click',()=>cancelTask());
  window.addEventListener('jarvis-interrupt',()=>cancelTask());
  $('#brain-codex').addEventListener('click',()=>changeBrain('codex'));
  $('#brain-gemini').addEventListener('click',()=>changeBrain('gemini'));
  $('#fit-button').addEventListener('click',()=>{galaxy.fit();$('#note-panel').hidden=true;document.body.classList.remove('showing-note');});
  $('#close-note').addEventListener('click',()=>{$('#note-panel').hidden=true;document.body.classList.remove('showing-note');});
  const safe=fn=>async()=>{try{await fn();}catch(error){fail(error.message);}};
  $('#focus-button').addEventListener('click',safe(()=>state.focus.on?$('#focus-card').hidden=false:focusAction('start',{minutes:DEFAULT_FOCUS_MINUTES,from_jarvis:true})));
  $('#focus-pause').addEventListener('click',safe(()=>focusAction(state.focus.paused?'resume':'pause')));
  $('#focus-end').addEventListener('click',safe(()=>focusAction('end')));
  $('#focus-retarget').addEventListener('click',safe(()=>focusAction('retarget',{from_jarvis:true})));
  $('#screen-button').addEventListener('click',safe(()=>organs.live(organs.screenStream)?organs.stopScreen():organs.startScreen(false)));
  $('#watch-button').addEventListener('click',safe(()=>organs.watching?organs.stopScreen():organs.startScreen(true)));
  $('#camera-button').addEventListener('click',safe(()=>organs.live(organs.cameraStream)?organs.stopCamera():organs.startCamera()));
  $('#stop-share').addEventListener('click',()=>organs.stopScreen());$('#stop-camera').addEventListener('click',()=>organs.stopCamera());
  $('#model-chip').addEventListener('click',()=>{$('#model-error').textContent='';$('#model-dialog').showModal();});
  $('#model-form').addEventListener('submit',async event=>{event.preventDefault();try{await changeModel($('#model-name').value);}catch(error){$('#model-error').textContent=error.message;speak(error.message);}});
  $('#help-button').addEventListener('click',()=>$('#help-dialog').showModal());$('#demo-button').addEventListener('click',()=>$('#demo-dialog').showModal());
  document.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>document.getElementById(button.dataset.closeDialog).close()));
  $('#demo-single').addEventListener('click',()=>{if(!galaxy.nodes.length){fail('אין עדיין הערות במפה.');return;}$('#demo-dialog').close();submit(`מה כתוב בהערה ״${galaxy.nodes[0].label}״? ענה רק מההערה הזאת.`);});
  $('#demo-cluster').addEventListener('click',()=>{if(galaxy.nodes.length<4){fail('לבדיקה הזאת דרושות לפחות ארבע הערות.');return;}$('#demo-dialog').close();submit(`מה הקשר בין ההערות הבאות? השתמש בכל אחת מארבע ההערות אם יש בהן מידע מתאים: ${galaxy.nodes.slice(0,4).map(node=>node.label).join(' ; ')}.`);});
  $('#demo-smalltalk').addEventListener('click',()=>{$('#demo-dialog').close();submit('בוקר טוב');});
  window.addEventListener('pagehide',()=>{if(!EMBEDDED)stopSpeech();state.ears=false;state.recognition?.abort();if(organs.watching)fetch('/watch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:false,full_screen:false}),keepalive:true}).catch(()=>{});});
}

async function boot(){
  bind();setupEars();events();
  if(EMBEDDED)connectNative({onEars:enabled=>{
    state.ears=enabled;$('#ear-button').setAttribute('aria-pressed',String(enabled));$('#ear-button').textContent=enabled?'מיקרופון פעיל':'מיקרופון כבוי';
    $('#ear-button').title=enabled?'כיבוי המיקרופון באפליקציה':'הפעלת המיקרופון באפליקציה';organsChanged(organs.state());
  },onUtterance:text=>{if(state.ears)submit(text);}}).catch(error=>fail(error.message));
  try{
    galaxy=new Galaxy($('#galaxy'),noteSelected,graphChanged);
    const [graph,initial]=await Promise.all([api('/graph'),api('/state')]);
    galaxy.update(graph);setModel(initial);if(initial.focus)focusState(initial.focus);
    if(initial.key_configured===false)showText(initial.provider==='codex'?'הגלקסיה מוכנה. נדרשת התחברות ל־Codex CLI במחשב.':'הגלקסיה מוכנה. אפשר להזין מפתח Gemini בהגדרות.');
    const aliases=initial.aliases||[];const options=$('#model-options');
    for(const alias of (Array.isArray(aliases)?aliases:Object.keys(aliases)).slice(0,8)){
      const button=document.createElement('button');button.textContent=alias;button.addEventListener('click',async()=>{try{await changeModel(alias);}catch(error){$('#model-error').textContent=error.message;speak(error.message);}});options.append(button);
    }
    state.ready=true;await poll();setInterval(poll,STATE_POLL_MS);
    if(initial.provider==='codex'&&tasks.savedId&&!tasks.active)resumeTask(tasks.savedId);
    if(PROBE){const {runProbe}=await import('./probe.js');await runProbe({galaxy,organs,state,cameraPlan,routeCommand,prettyModel});}
  }catch(error){fail(`הגלקסיה לא נטענה: ${error.message}`);if(PROBE)document.title='FOCUSPROBE FAIL boot';}
}
// Test instrumentation contains counters and flags only. No frames, API keys,
// distraction identities, transcripts or session intent are exposed here.
window.JarvisGalaxy=Object.freeze({inspect:()=>({ready:state.ready,muted:MUTED,embedded:EMBEDDED,native_bridge:!!nativeBridge(),ears:state.ears,sse:state.sse,...galaxy?.inspection(),screen_sharing:organs.live(organs.screenStream),screen_watch:organs.watching,webcam:organs.live(organs.cameraStream)})});
boot();
