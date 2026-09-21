'use client';
import {useEffect,useRef,useState} from 'react';
export function Face(props:{state:string;level:number;intensity?:number;motion?:{open:number;wide:number;at:number}}){
 const host=useRef<HTMLDivElement>(null),current=useRef(props);current.current=props;
 const [error,setError]=useState(false);
 useEffect(()=>{let stopped=false,dispose:(()=>void)|undefined;const mount=()=>{if(stopped||!host.current)return;try{dispose=(window as any).jarvisFaceMount(host.current,()=>current.current)}catch{setError(true)}};
  if((window as any).jarvisFaceMount)mount();else{const script=document.createElement('script');script.type='module';script.src='/presence.js';script.onload=mount;script.onerror=()=>setError(true);document.body.appendChild(script)}
  return()=>{stopped=true;dispose?.()};
 },[]);
 return <div className="presence-face" ref={host}>{error&&<p className="face-fallback">התצוגה התלת־ממדית אינה זמינה. אפשר להמשיך לדבר ולכתוב.</p>}</div>;
}
