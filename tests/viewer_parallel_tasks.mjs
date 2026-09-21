import assert from 'node:assert/strict';
import {TaskPool} from '../viewer/task-client.js';
const states=new Map(),seen=[];let serial=0;
const api=async(path,body)=>{
 if(path==='/tasks'){const id=(++serial).toString(16).padStart(32,'0');states.set(id,{id,status:'running',title:body.question});return states.get(id);}
 const id=path.split('/')[2];
 if(path.endsWith('/cancel'))states.set(id,{id,status:'cancelled',answer:'stopped'});
 return states.get(id);
};
const pool=new TaskPool({api,onUpdate:t=>seen.push(t),wait:()=>new Promise(r=>setTimeout(r,1))});
const one=pool.run('first','same'),two=pool.run('second','same');
await new Promise(r=>setTimeout(r,10));
assert.equal(pool.jobs.size,2);
const ids=[...states.keys()];
await pool.stop(ids[0]);
assert.equal((await one).status,'cancelled');
assert.equal(pool.jobs.size,1);
assert.equal(states.get(ids[1]).status,'running');
states.set(ids[1],{id:ids[1],status:'completed',answer:'second result'});
assert.equal((await two).answer,'second result');
assert.equal(pool.active,false);
assert.equal(new Set(seen.map(t=>t.observer)).size,2);
console.log('parallel viewer: 6 pass, 0 fail');
