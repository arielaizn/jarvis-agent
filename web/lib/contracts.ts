import {z} from 'zod';
export const CardSchema=z.object({type:z.enum(['meeting','calendar','email','note','insight','action','document','research','source','generic']),title:z.string().max(240),body:z.string().max(12000).optional(),subtitle:z.string().optional(),time:z.string().optional(),url:z.string().url().optional(),id:z.string().optional()});
export const ResponseSchema=z.object({speech:z.string().max(5000),title:z.string().max(240),state:z.enum(['complete','confirmation','error']),cards:z.array(CardSchema).max(40),nodes:z.array(z.number().int().nonnegative()).optional(),sources:z.array(z.object({type:z.string(),name:z.string(),id:z.number().int().optional(),url:z.string().optional()})).max(40)});
export type IntelligenceCard=z.infer<typeof CardSchema>;
export type AgentResponse=z.infer<typeof ResponseSchema>;
export type ActivityEvent={id:number;type:'agent_started'|'skill_selected'|'tool_started'|'tool_completed'|'tool_failed'|'agent_synthesizing'|'response_ready'|'audio_started'|'audio_finished'|'confirmation_required';label:string;tool?:string;timestamp:number};
export type AgentProvider={id:string;available():Promise<boolean>;run(request:{question:string;session:string},onEvent:(event:ActivityEvent)=>void):Promise<AgentResponse>};
export type ToolDefinition={name:string;description:string;permission:'read'|'write';input:Record<string,unknown>};
export async function api<T=any>(path:string, payload?:unknown):Promise<T>{const response=await fetch(path,{method:payload===undefined?'GET':'POST',cache:'no-store',headers:payload===undefined?{}:{'Content-Type':'application/json'},body:payload===undefined?undefined:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.error?.message||'הבקשה נכשלה');return data;}
