import {TaskPool} from './task-client.js';
import {pixelDifference,postureFromLandmarks} from './organs.js';

const PROBE_VIEWPORT={width:1440,height:900};
const nextPaint=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));

export async function runProbe({galaxy,organs,state,cameraPlan,routeCommand,prettyModel}) {
  const output=document.querySelector('#probe-results');output.hidden=false;
  const heading=document.createElement('strong');heading.textContent='Browser probe · real rendering + isolated behaviour checks';output.append(heading);
  let pass=0,fail=0;
  const check=async(name,fn)=>{
    const line=document.createElement('p');
    try{await fn();line.textContent=`PASS ${name}`;line.className='probe-pass';pass++;}
    catch(error){line.textContent=`FAIL ${name}: ${error.message}`;line.className='probe-fail';fail++;}
    output.append(line);
  };
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  await check('visible viewport 1440 × 900',()=>assert(innerWidth===PROBE_VIEWPORT.width&&innerHeight===PROBE_VIEWPORT.height&&document.visibilityState==='visible',`actual ${innerWidth}x${innerHeight}, ${document.visibilityState}`));
  await check('test tab is muted',()=>assert(new URLSearchParams(location.search).get('mute')==='1','load test tabs with ?mute=1'));
  await check('parallel task controls remain available',()=>assert(!!document.querySelector('#task-mode')&&!!document.querySelector('#agent-tasks')&&!document.querySelector('#send-button').disabled,'task controls missing or disabled'));
  await check('parallel observers cancel independently',async()=>{
    const records=new Map();let sequence=0;
    const api=async(path,body)=>{
      if(path==='/tasks'){const id=String(++sequence).padStart(32,'0');const task={id,status:'running'};records.set(id,task);return task;}
      const id=path.split('/')[2];
      if(path.endsWith('/cancel'))records.set(id,{id,status:'cancelled',answer:'stopped'});
      return records.get(id);
    };
    const pool=new TaskPool({api,onUpdate:()=>{},wait:()=>new Promise(r=>setTimeout(r,0))});
    const first=pool.run('one','probe'),second=pool.run('two','probe');
    await nextPaint();const ids=[...records.keys()];
    assert(ids.length===2&&pool.jobs.size===2,'observers did not coexist');
    await pool.stop(ids[0]);assert((await first).status==='cancelled','first was not cancelled');
    assert(pool.active&&records.get(ids[1]).status==='running','second task was cancelled too');
    records.set(ids[1],{id:ids[1],status:'completed',answer:'second'});
    assert((await second).answer==='second'&&!pool.active,'second result lost');
  });
  await check('Hebrew RTL document',()=>assert(document.documentElement.lang==='he'&&document.documentElement.dir==='rtl','document direction'));
  await check('real WebGL canvas and indexed notes',()=>assert(galaxy.inspection().rendered&&galaxy.nodes.length>0&&galaxy.nodes.every((node,index)=>node.id===index),'missing canvas, notes or index IDs'));
  await check('graph retains complete adjacency',()=>assert(galaxy.links.length>=galaxy.inspection().visibleLinkCount,'edge subset exceeds source data'));
  await check('one source flies and opens its note',async()=>{
    const count=galaxy.flyCount;galaxy.prove({nodes:[0],note_question:true});await nextPaint();
    assert(galaxy.flyCount===count+1&&!document.querySelector('#note-panel').hidden,'source was not shown');
  });
  await check('four sources light a cluster without flying',()=>{
    assert(galaxy.nodes.length>=4,'four notes required for this rendering check');
    const count=galaxy.flyCount;galaxy.prove({nodes:[0,1,2,3],note_question:true});
    assert(galaxy.flyCount===count&&galaxy.active.size===4&&galaxy.lastMode==='cluster','cluster moved the camera');
  });
  await check('small talk never flies or resumes rotation',()=>{
    const count=galaxy.flyCount;galaxy.prove({nodes:[0],note_question:false,intent:'smalltalk'});
    assert(galaxy.flyCount===count&&!galaxy.graph.controls().autoRotate,'small talk moved the graph');
  });
  await check('only valid integer source indexes survive',()=>{
    const plan=cameraPlan({nodes:[0,0,-1,'1',galaxy.nodes.length+1],note_question:true},galaxy.nodes.length);
    assert(JSON.stringify(plan.nodes)==='[0]','invalid indexes were used');
  });
  await check('natural retarget commands precede screen routing',()=>{
    for(const text of ['lock on this tab','keep me in this tab','this is the tab','stay on this tab',"okay, I'm gonna need you to keep me in this tab.",'תנעל על הלשונית הזאת']){
      const command=routeCommand(text,true);assert(command.type==='focus'&&command.action==='retarget',text);
    }
  });
  await check('remember routes to durable capture',()=>{
    for(const text of ['remember that the finish window should be 900 milliseconds','תזכור שחלון הסיום הוא 900 מילישניות'])assert(routeCommand(text).type==='remember',text);
  });
  await check('requested model version remains exact',()=>assert(routeCommand('switch to opus 99').name==='opus 99','version was discarded'));
  await check('pretty model version dots only join digits',()=>assert(prettyModel('openai/gpt-6-astra')==='GPT 6 ASTRA'&&prettyModel('anthropic/fable-5-1')==='FABLE 5.1','incorrect model label'));
  await check('screen phrases never take a webcam frame',()=>assert(routeCommand('what do you think of this screen?').source==='screen'&&routeCommand('what do you think of my shirt?').source==='webcam','wrong image source'));
  await check('deictic screen questions require a fresh share',()=>assert(routeCommand('what am I looking at').source==='screen'&&routeCommand('מה דעתך על זה?').source==='screen','screen question fell through to notes'));
  await check('small talk does not request a screen frame',()=>assert(routeCommand('good morning').smalltalk&&routeCommand('tell me a joke').smalltalk&&routeCommand('בוקר טוב').smalltalk,'small talk classification failed'));
  await check('relief command covers all organs',()=>assert(routeCommand('give me a minute').action==='relief'&&routeCommand('תן לי דקה').action==='relief','relief route missing'));
  await check('spoken curly apostrophe excuse is accepted',()=>assert(routeCommand('it’s okay, I’m doing research').action==='excuse','excuse was treated as a question'));
  await check('camera organs never request the microphone',()=>assert(state.earRequests===0,'mic was requested without ear button'));
  await check('a stopped share cannot return a cached frame',()=>{
    assert(!organs.live(organs.screenStream),'probe must start without an active share');
    let rejected=false;try{organs.capture('screen');}catch{rejected=true;}assert(rejected,'inactive share supplied a frame');
  });
  await check('thumbnail diff sees change and stillness locally',()=>{
    const black=new Uint8ClampedArray([0,0,0,255,0,0,0,255]);
    const white=new Uint8ClampedArray([255,255,255,255,255,255,255,255]);
    assert(pixelDifference(black,black)===0&&pixelDifference(black,white)===255,'diff output incorrect');
  });
  await check('posture output contains only the boolean whitelist',()=>{
    const posture=postureFromLandmarks([],[]);
    assert(JSON.stringify(Object.keys(posture).sort())==='["head_down","present","slouched"]'&&Object.values(posture).every(value=>typeof value==='boolean'),'posture identity escaped');
  });
  await check('page has no horizontal layout overflow',()=>assert(document.documentElement.scrollWidth<=innerWidth,'horizontal overflow'));
  galaxy.fit();document.querySelector('#note-panel').hidden=true;
  document.body.classList.remove('showing-note');
  const summary=`FOCUSPROBE: ${pass} pass, ${fail} fail, 0 warn`;
  const line=document.createElement('p');line.textContent=summary;line.className=fail?'probe-fail':'probe-pass';output.append(line);
  document.title=`FOCUSPROBE ${fail?'FAIL':'PASS'} | ${pass} pass, ${fail} fail, 0 warn`;
  output.dataset.summary=summary;
  return {pass,fail,warn:0,summary};
}
