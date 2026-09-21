// The task belongs to the server. This client observes it and requests a stop;
// a slow request or a closed tab is never evidence that execution has stopped.
export const TASK_POLL_MS = 200;
export const TASK_STORAGE_KEY = 'jarvis-codex-task';

export function isTaskStop(text) {
  return /^(?:(?:jarvis|ג[׳'’]?רוויס)[,\s]+)?(?:stop|cancel(?: the)? task|stop(?: the)? task|עצור|תעצור|עצור את המשימה|תעצור את המשימה|בטל את המשימה|תבטל את המשימה)[.!?]*$/i.test(String(text).trim());
}

export function isNotesQuestion(text, recentNotes = false) {
  if(recentNotes && /^(?:what|how|when|why|which|where|is|does|can you tell|and|מה|ומה|כמה|וכמה|מתי|למה|איך|האם|אז|עוד)\b/i.test(text)) return true;
  if(recentNotes && /^(?:מה|ומה|כמה|וכמה|מתי|למה|איך|האם|אז|עוד)(?:\s|[?!])/u.test(text)) return true;
  const note = /(?:\b(?:my notes|the notes|this note|that note|note titled|notes about)\b|(?:בהער(?:ה|ות)|ההער(?:ה|ות)|מההער(?:ה|ות)|על ההער(?:ה|ות)|לפי ההער(?:ה|ות)|כתבתי|רשמתי|שמרתי))/i.test(text);
  const question = /(?:\b(?:what|which|where|when|why|how|tell me|summari[sz]e|show me|according to)\b|(?:^|\s)(?:מה|מי|איך|מתי|כמה|איזה|האם|תסכם|סכם|הצג|ספר לי|לפי)(?:\s|$))/i.test(text);
  return note && question;
}

export class TaskClient {
  constructor({api, onUpdate, storage = null, wait = ms => new Promise(resolve => setTimeout(resolve, ms))}) {
    this.api = api;
    this.onUpdate = onUpdate;
    this.storage = storage;
    this.wait = wait;
    this.generation = 0;
    this.id = null;
    this.active = false;
    this.stopping = false;
  }

  get savedId() {
    try { const value = this.storage?.getItem(TASK_STORAGE_KEY); return /^[a-f0-9]{32}$/.test(value || '') ? value : null; }
    catch { return null; }
  }

  remember(id) {
    try { if (id) this.storage?.setItem(TASK_STORAGE_KEY, id); else this.storage?.removeItem(TASK_STORAGE_KEY); } catch {}
  }

  invalidate() {
    this.generation++;
    this.id = null;
    this.active = false;
    this.stopping = false;
    this.remember(null);
  }

  async stop() {
    if (!this.active) return;
    this.stopping = true;
    this.onUpdate({status:'running', progress:'מבקש לעצור את המשימה', stopping:true});
    if (this.id) {
      try { await this.api(`/tasks/${this.id}/cancel`, {}); }
      catch (error) { this.stopping = false; throw error; }
    }
  }

  async run(question, sessionId, resumeId = null, mode = null) {
    const generation = ++this.generation;
    this.active = true;
    this.stopping = false;
    this.onUpdate({status:resumeId ? 'running' : 'queued', progress:resumeId ? 'מתחבר למשימה שרצה' : 'מעביר את הבקשה ל־Codex'});
    let result;
    try { result = resumeId ? {id:resumeId, status:'running'} : await this.api('/tasks', {question, session_id:sessionId, ...(mode ? {mode} : {})}); }
    catch (error) { if (generation === this.generation) this.active = false; throw error; }
    if (generation !== this.generation) return null;
    this.id = result.id;
    if (!/^[a-f0-9]{32}$/.test(this.id || '')) { this.active = false; throw new Error('השרת לא החזיר מזהה משימה תקין.'); }
    this.remember(this.id);
    if (this.stopping) {
      try { await this.api(`/tasks/${this.id}/cancel`, {}); }
      catch { this.stopping = false; this.onUpdate({status:'running', progress:'בקשת העצירה לא אושרה. אפשר לנסות לעצור שוב.'}); }
    }
    while (generation === this.generation) {
      this.onUpdate({...result, stopping:this.stopping});
      if (['completed', 'failed', 'cancelled'].includes(result.status)) {
        this.id = null;
        this.active = false;
        this.remember(null);
        return result;
      }
      await this.wait(TASK_POLL_MS);
      if (generation !== this.generation) return null;
      try {
        result = await this.api(`/tasks/${this.id}`);
      } catch (error) {
        if (generation !== this.generation) return null;
        if (error.status === 404) {
          this.id = null;
          this.active = false;
          this.remember(null);
          throw new Error('המשימה כבר אינה זמינה בשרת. ייתכן שהשרת הופעל מחדש.');
        }
        this.onUpdate({status:'running', progress:'החיבור למעקב התנתק. בודק שוב את מצב המשימה.', stopping:this.stopping});
        await this.wait(TASK_POLL_MS * 2);
      }
    }
    return null;
  }
}


// Each observer owns exactly one server task. A new request never invalidates
// another observer. Server state is the authority when a tab reloads.
export class TaskPool {
  constructor({api, onUpdate, wait}) {
    this.api=api; this.onUpdate=onUpdate; this.wait=wait;
    this.jobs=new Map(); this.sequence=0;
  }
  get active(){return this.jobs.size>0;}
  get savedId(){return null;}
  has(id){return [...this.jobs.values()].some(c=>c.id===id||c.resumeId===id);}
  invalidate(){for(const c of this.jobs.values())c.invalidate();this.jobs.clear();}
  async stop(id=null){
    const clients=[...this.jobs.values()].filter(c=>!id||c.id===id);
    await Promise.all(clients.map(c=>c.stop()));
  }
  async run(question, sessionId, resumeId=null, mode=null){
    if(resumeId&&this.has(resumeId))return null;
    const key=resumeId||`pending-${++this.sequence}`;
    const client=new TaskClient({api:this.api,wait:this.wait,
      onUpdate:t=>this.onUpdate({...t,observer:key,title:t.title||question})});
    client.resumeId=resumeId;
    this.jobs.set(key,client);
    try{return await client.run(question,sessionId,resumeId,mode);}
    catch(error){this.onUpdate({observer:key,status:'failed',title:question,progress:error.message});throw error;}
    finally{this.jobs.delete(key);}
  }
}
