import {api} from './contracts';
// Capture is created only after the ear button. Silence ends a turn; a new
// utterance interrupts playback immediately, before network transcription.
export async function startElevenInput({onText,onLevel,onSpeech,onError}:{onText:(s:string)=>void;onLevel:(n:number)=>void;onSpeech:()=>void;onError:(s:string)=>void}){
 const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
 const context=new AudioContext(),analyser=context.createAnalyser();context.createMediaStreamSource(stream).connect(analyser);analyser.fftSize=1024;
 const samples=new Float32Array(analyser.fftSize);let recorder:MediaRecorder|null=null,chunks:Blob[]=[],lastSound=0,started=0,alive=true,speaking=false,busy=false;
 const mime=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(m=>MediaRecorder.isTypeSupported(m));
 const begin=()=>{chunks=[];recorder=new MediaRecorder(stream,mime?{mimeType:mime}:{});recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};recorder.onstop=async()=>{if(!alive||busy)return;busy=true;try{const blob=new Blob(chunks,{type:recorder?.mimeType||mime});if(blob.size<1000)return;const bytes=new Uint8Array(await blob.arrayBuffer());let raw='';for(const byte of bytes)raw+=String.fromCharCode(byte);const result=await api('/command/transcribe',{audio:btoa(raw),mime:blob.type.split(';')[0]});if(alive&&result.text)onText(result.text)}catch(e){onError((e as Error).message)}finally{busy=false}};recorder.start();started=Date.now();};
 const interval=setInterval(()=>{if(!alive)return;analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((n,v)=>n+v*v,0)/samples.length);onLevel(Math.min(1,rms*10));if(rms>.025){lastSound=Date.now();if(!speaking&&!busy){speaking=true;onSpeech();begin();}}if(speaking&&(Date.now()-lastSound>700||Date.now()-started>25000)){speaking=false;if(recorder?.state==='recording')recorder.stop();}},50);
 return ()=>{alive=false;clearInterval(interval);if(recorder?.state==='recording')recorder.stop();stream.getTracks().forEach(t=>t.stop());void context.close();onLevel(0)};
}
