import * as T from './holo/vendor/three.module.js';
import {HEAD} from './presence-mesh.js';
// Audio is supplied by the actual output player. No idle oscillator drives lips.
window.jarvisFaceMount = (host, read) => {
 const renderer=new T.WebGLRenderer({alpha:true,antialias:true,powerPreference:'low-power'});
 renderer.setPixelRatio(Math.min(devicePixelRatio,2)); renderer.setClearColor(0x000000,0);
 renderer.outputColorSpace=T.SRGBColorSpace; renderer.toneMapping=T.ACESFilmicToneMapping;
 renderer.toneMappingExposure=1.35; host.append(renderer.domElement);
 renderer.domElement.setAttribute('aria-label','פני ג׳רוויס');renderer.domElement.setAttribute('role','img');
 const scene=new T.Scene(),camera=new T.PerspectiveCamera(32,1,.1,50);camera.position.set(0,-.18,5.6);camera.lookAt(0,-.18,0);
 const group=new T.Group();scene.add(group);
 scene.add(new T.HemisphereLight(0xd9f9f5,0x0a151b,2));
 for(const [color,power,x,y,z] of [[0xc3e6e5,3,-3,4,5],[0x46d9d0,4,3,1,-2],[0x3a758c,1,-4,-2,1]]){const l=new T.DirectionalLight(color,power);l.position.set(x,y,z);scene.add(l)}
 const base=new Float32Array(HEAD.verts.flat()),pos=new Float32Array(base),geometry=new T.BufferGeometry();
 geometry.setAttribute('position',new T.BufferAttribute(pos,3));geometry.setIndex(HEAD.faces.flat());geometry.computeVertexNormals();
 const material=new T.MeshStandardMaterial({color:0x648a89,metalness:.36,roughness:.58,side:T.DoubleSide});
 const head=new T.Mesh(geometry,material);group.add(head);
 const edges=new T.LineSegments(new T.WireframeGeometry(geometry),new T.LineBasicMaterial({color:0x70e7dd,transparent:true,opacity:.025}));group.add(edges);
 const average=ids=>ids.reduce((a,i)=>a.add(new T.Vector3(...HEAD.verts[i])),new T.Vector3()).divideScalar(ids.length);
 const eyes=[];
 for(const ids of [HEAD.landmarks.eye_l,HEAD.landmarks.eye_r].filter(Boolean)){
  const center=average(ids),eye=new T.Group();eye.position.copy(center);eye.position.z-=.015;
  const ball=new T.Mesh(new T.SphereGeometry(.118,32,20),new T.MeshStandardMaterial({color:0x315653,metalness:.3,roughness:.2}));ball.scale.set(1.1,.72,.7);eye.add(ball);
  const iris=new T.Group();iris.position.z=.09;
  const ring=new T.Mesh(new T.TorusGeometry(.035,.0045,8,40),new T.MeshBasicMaterial({color:0x79eee1}));iris.add(ring);
  const pupil=new T.Mesh(new T.CircleGeometry(.029,32),new T.MeshBasicMaterial({color:0x06171c}));pupil.position.z=.001;iris.add(pupil);
  const glint=new T.Mesh(new T.CircleGeometry(.009,16),new T.MeshBasicMaterial({color:0xe2fff8}));glint.position.set(-.012,.014,.003);iris.add(glint);
  eye.add(iris);group.add(eye);eyes.push({eye,iris,center,ids});
 }
 const lipGeo=new T.BufferGeometry();lipGeo.setAttribute('position',new T.BufferAttribute(new Float32Array(HEAD.landmarks.lips_in.length*3),3));
 const lip=new T.LineLoop(lipGeo,new T.LineBasicMaterial({color:0x254e51,transparent:true,opacity:.8}));group.add(lip);
 let raf=0,previous=performance.now(),elapsed=0,mouth=0,width=.5,gazeX=0,gazeY=0,targetX=0,targetY=0,lastCamera=0,blinkAt=2.8;
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const pointer=e=>{if(performance.now()-lastCamera<1000)return;const box=host.getBoundingClientRect();targetX=Math.max(-1,Math.min(1,(e.clientX-box.left-box.width/2)/(box.width/2)));targetY=Math.max(-1,Math.min(1,(e.clientY-box.top-box.height/2)/(box.height/2)))};
 const track=e=>{if(e.detail?.present){lastCamera=performance.now();targetX=e.detail.x;targetY=e.detail.y}};
 const leave=()=>{targetX=0;targetY=0};
 window.addEventListener('pointermove',pointer);window.addEventListener('jarvis:gaze',track);document.addEventListener('pointerleave',leave);
 const resize=()=>{const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()};const observer=new ResizeObserver(resize);observer.observe(host);resize();
 const draw=now=>{raf=requestAnimationFrame(draw);if(document.hidden)return;const dt=Math.min(.05,(now-previous)/1000);previous=now;elapsed+=dt;const state=read();
  const speaking=state.state==='speaking',fresh=now-(state.motion?.at||0)<180;
  const target=speaking?(fresh?state.motion.open:Math.max(0,state.level||0)**.7):0;
  mouth+=(target-mouth)*(1-Math.exp(-dt/(target>mouth?.025:.018)));width+=((fresh?state.motion.wide:.5)-width)*.3;
  gazeX+=(targetX-gazeX)*.09;gazeY+=(targetY-gazeY)*.09;
  const motion=reduced.matches?0:(state.intensity??1);
  group.rotation.y=gazeX*.12+Math.sin(elapsed*.34)*.025*motion;group.rotation.x=gazeY*.055;
  group.position.y=Math.sin(elapsed*.7)*.009*motion;
  let blink=0;if(motion&&elapsed>blinkAt){const phase=(elapsed-blinkAt)/.18;blink=phase<1?Math.sin(phase*Math.PI):0;if(phase>=1)blinkAt=elapsed+3.2+Math.random()*2.8}
  for(let i=0;i<HEAD.verts.length;i++){const j=i*3,jaw=HEAD.jaw[i];pos[j]=base[j]*(1+(width-.5)*.16*HEAD.lips[i]*mouth);pos[j+1]=base[j+1]-.15*jaw*mouth;pos[j+2]=base[j+2]-.028*jaw*mouth;}
  for(const {eye,iris,center,ids} of eyes){eye.scale.y=1-blink*.96;iris.position.x=gazeX*.022;iris.position.y=-gazeY*.022;for(const i of ids)pos[i*3+1]=center.y+(base[i*3+1]-center.y)*(1-blink*.97)}
  geometry.attributes.position.needsUpdate=true;geometry.computeVertexNormals();
  const lips=lipGeo.attributes.position.array;HEAD.landmarks.lips_in.forEach((id,i)=>{lips[i*3]=pos[id*3];lips[i*3+1]=pos[id*3+1];lips[i*3+2]=pos[id*3+2]+.001});lipGeo.attributes.position.needsUpdate=true;
  host.dataset.mouth=mouth.toFixed(3);host.dataset.gaze=(now-lastCamera<1000?'camera':'pointer');host.dataset.rendered='true';renderer.render(scene,camera);
 };raf=requestAnimationFrame(draw);
 return()=>{cancelAnimationFrame(raf);observer.disconnect();window.removeEventListener('pointermove',pointer);window.removeEventListener('jarvis:gaze',track);document.removeEventListener('pointerleave',leave);scene.traverse(o=>{o.geometry?.dispose();if(o.material)for(const m of [o.material].flat())m.dispose()});renderer.dispose();renderer.domElement.remove()};
};
