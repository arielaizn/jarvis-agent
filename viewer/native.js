export const EMBEDDED=new URLSearchParams(location.search).get('embedded')==='1';
const BRIDGE_TIMEOUT_MS=10000;

let bridge=null;
export function nativeBridge(){return bridge;}

function loadWebChannel(){
  if(window.QWebChannel)return Promise.resolve();
  return new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src='qrc:///qtwebchannel/qwebchannel.js';
    script.onload=resolve;script.onerror=()=>reject(new Error('החיבור לחלון ג׳רוויס לא נטען.'));
    document.head.append(script);
  });
}

export async function connectNative({onEars,onUtterance}){
  if(!EMBEDDED)return null;
  const connect=async()=>{
    if(window.jarvisNativeReady)await window.jarvisNativeReady;
    if(window.jarvisNative)bridge=window.jarvisNative;
    else{
      if(!window.qt?.webChannelTransport)throw new Error('הגלקסיה נפתחה בלי חיבור לאפליקציית ג׳רוויס.');
      await loadWebChannel();
      bridge=await new Promise(resolve=>new QWebChannel(qt.webChannelTransport,channel=>resolve(channel.objects.jarvisNative)));
    }
    if(!bridge)throw new Error('החיבור הקולי לאפליקציה אינו זמין.');
    bridge.earsChanged?.connect?.(enabled=>onEars(!!enabled));
    bridge.utterance?.connect?.(text=>onUtterance(String(text||'')));
    if(typeof bridge.earState==='function')bridge.earState(enabled=>onEars(!!enabled));
    else if(typeof bridge.earsEnabled==='boolean')onEars(bridge.earsEnabled);
    return bridge;
  };
  let timer;
  try{return await Promise.race([connect(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('האפליקציה לא ענתה לחיבור הקולי.')),BRIDGE_TIMEOUT_MS);})]);}
  finally{clearTimeout(timer);}
}
