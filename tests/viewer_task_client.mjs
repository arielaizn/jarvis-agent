import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../viewer/task-client.js', import.meta.url), 'utf8');
const {TaskClient, isTaskStop, isNotesQuestion} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const id = 'a'.repeat(32);
const immediate = () => Promise.resolve();
const deferred = () => {let resolve;const promise = new Promise(done => resolve = done);return {promise,resolve};};
const storage = () => {const values = new Map();return {getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};

test('normal task is posted once, progress observed, completion clears reconnect state', async () => {
  const calls = [], updates = [], saved = storage();
  let reads = 0;
  const client = new TaskClient({storage:saved,wait:immediate,onUpdate:value=>updates.push(value),api:async(path,payload)=>{
    calls.push({path,payload});
    if(path === '/tasks')return {id,status:'queued'};
    return ++reads === 1 ? {id,status:'running',progress:'working'} : {id,status:'completed',answer:'created'};
  }});
  const result = await client.run('create a file','session');
  assert.equal(result.answer,'created');
  assert.equal(calls.filter(call=>call.path === '/tasks').length,1);
  assert.ok(updates.some(update=>update.progress === 'working'));
  assert.equal(client.savedId,null);
  assert.equal(client.active,false);
});

test('voice stop received while start request is pending cancels once identity arrives', async () => {
  const started = deferred(), calls=[];
  const client = new TaskClient({wait:immediate,onUpdate:()=>{},api:async(path)=>{
    calls.push(path);
    if(path === '/tasks')return started.promise;
    return {id,status:'cancelled'};
  }});
  const running = client.run('work','session');
  await client.stop();
  started.resolve({id,status:'queued'});
  assert.equal((await running).status,'cancelled');
  assert.equal(calls.filter(path=>path.endsWith('/cancel')).length,1);
});

test('switching provider suppresses late task completion and removes saved identity', async () => {
  const reply = deferred(), queried = deferred(), updates=[];
  const client = new TaskClient({wait:immediate,storage:storage(),onUpdate:value=>updates.push(value),api:async(path)=>{
    if(path === '/tasks')return {id,status:'running'};
    queried.resolve();return reply.promise;
  }});
  const running = client.run('work','session');
  await queried.promise;
  client.invalidate();
  reply.resolve({id,status:'completed',answer:'stale answer'});
  assert.equal(await running,null);
  assert.equal(client.savedId,null);
  assert.ok(!updates.some(value=>value.status === 'completed'));
});

test('temporary polling disconnect retains task and reconnects without a second execution', async () => {
  const updates=[];let reads=0,posts=0;
  const client = new TaskClient({wait:immediate,onUpdate:value=>updates.push(value),api:async(path)=>{
    if(path === '/tasks'){posts++;return {id,status:'running'};}
    if(++reads === 1)throw new TypeError('network unavailable');
    return {id,status:'completed',answer:'verified'};
  }});
  assert.equal((await client.run('work','session')).answer,'verified');
  assert.equal(posts,1);
  assert.ok(updates.some(value=>value.progress?.includes('התנתק')));
});

test('reload observes an existing server task without posting the command again', async () => {
  const calls=[];
  const client = new TaskClient({wait:immediate,onUpdate:()=>{},api:async(path)=>{calls.push(path);return {id,status:'completed'};}});
  await client.run('','session',id);
  assert.deepEqual(calls,[`/tasks/${id}`]);
});

test('a missing task fails honestly and clears stale reload identity', async () => {
  const client = new TaskClient({wait:immediate,storage:storage(),onUpdate:()=>{},api:async()=>{const error = new Error('missing');error.status=404;throw error;}});
  await assert.rejects(client.run('','session',id), /אינה זמינה/);
  assert.equal(client.savedId,null);
  assert.equal(client.active,false);
});

test('voice cancellation is deliberate and note mutations remain actions', () => {
  assert.equal(isTaskStop('ג׳רוויס, עצור את המשימה!'),true);
  assert.equal(isTaskStop('cancel the task'),true);
  assert.equal(isTaskStop('create a stop button'),false);
  assert.equal(isNotesQuestion('מה כתוב בהערה על חלון הסיום?'),true);
  assert.equal(isNotesQuestion('what do my notes say about the finish window?'),true);
  assert.equal(isNotesQuestion('סדר לי את ההערות בתיקייה'),false);
  assert.equal(isNotesQuestion('organize my notes into folders'),false);
  assert.equal(isNotesQuestion('צור קובץ בשם hello.txt'),false);
});
