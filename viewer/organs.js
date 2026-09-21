const JPEG_QUALITY = .84;
const MAX_FRAME_WIDTH = 1920;
const DIFF_WIDTH = 64;
const DIFF_HEIGHT = 36;
const WATCH_SAMPLE_MS = 5000;
const WATCH_STILL_MS = 60000;
const WATCH_COOLDOWN_MS = 180000;
const WATCH_HEARTBEAT_MS = 10000;
const PIXEL_CHANGE_THRESHOLD = 4;
const POSE_SAMPLE_MS = 180;
const POSTURE_PUBLISH_MS = 300;
const POSE_VISIBILITY_MIN = .45;
const HEAD_DOWN_NOSE_RATIO = .24;
const FACE_DOWN_PITCH = .22;
const SLOUCH_SHOULDER_DELTA = .08;
const SLOUCH_NOSE_RATIO = .15;
const MEDIAPIPE_VERSION = '0.10.22-rc.20250304';
const POSE_MODEL = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task';
const FACE_MODEL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';

export function pixelDifference(previous, current) {
  if(!previous || previous.length !== current.length) return Infinity;
  let total=0;
  for(let i=0;i<current.length;i+=4) total += Math.abs(current[i]-previous[i])+Math.abs(current[i+1]-previous[i+1])+Math.abs(current[i+2]-previous[i+2]);
  return total/(current.length/4*3);
}

export function postureFromLandmarks(pose, face) {
  const p = pose?.[0]; const f = face?.[0];
  const present = !!(p?.[0] && p[0].visibility >= POSE_VISIBILITY_MIN || f?.[1]);
  if(!present || !p?.[11] || !p?.[12]) return {present,head_down:false,slouched:false};
  const shoulderY = (p[11].y+p[12].y)/2;
  const shoulderWidth = Math.max(Math.abs(p[11].x-p[12].x),.05);
  const neckGap = (shoulderY-p[0].y)/shoulderWidth;
  let facePitch = 0;
  if(f?.[1] && f?.[33] && f?.[263] && f?.[152]) {
    const eyeY = (f[33].y+f[263].y)/2;
    const faceHeight = Math.max(f[152].y-eyeY,.01);
    facePitch = (f[1].y-eyeY)/faceHeight;
  }
  const headDown = neckGap < HEAD_DOWN_NOSE_RATIO && (!f || facePitch > FACE_DOWN_PITCH);
  const slouched = Math.abs(p[11].y-p[12].y)>SLOUCH_SHOULDER_DELTA || neckGap<SLOUCH_NOSE_RATIO;
  return {present,head_down:headDown,slouched};
}

export class Organs {
  constructor({api, answer, say, fail, earsOn, onChange, quietUntil}) {
    Object.assign(this,{api,answer,say,fail,earsOn,onChange,quietUntil});
    this.screenStream=null; this.cameraStream=null; this.screenEnded=false; this.watching=false;
    this.watchBusy=false; this.lastPixels=null; this.lastChange=0; this.lastNudge=0; this.lastDiff=null;
    this.posture={present:false,head_down:false,slouched:false}; this.pose=null; this.face=null;
    this.screenVideo=document.querySelector('#screen-video');this.cameraVideo=document.querySelector('#camera-video');
    this.poseTimer=null;this.watchTimer=null;this.watchHeartbeat=null;this.cameraGeneration=0;this.screenGeneration=0;this.lastPublish=0;
    this.lastOrganFlags='';
    this.organHeartbeat=setInterval(()=>{if(this.live(this.screenStream)||this.live(this.cameraStream))this.publishOrgans();},WATCH_HEARTBEAT_MS);
  }
  live(stream) { return !!stream?.getVideoTracks().some(track=>track.readyState==='live'); }
  state() { return {screen_sharing:this.live(this.screenStream),screen_watch:this.watching,webcam:this.live(this.cameraStream),last_pixel_diff:Number.isFinite(this.lastDiff)?Number(this.lastDiff.toFixed(2)):null,stillness_seconds:this.watching?Math.floor((Date.now()-this.lastChange)/1000):0,watch_gate:this.watchBusy?'thinking':Date.now()-this.lastNudge<WATCH_COOLDOWN_MS?'cooldown':this.watching?'observing':'off',posture:{...this.posture}}; }
  publishOrgans(){
    const flags={screen_sharing:this.live(this.screenStream),screen_watch:this.watching,webcam:this.live(this.cameraStream),full_screen:this.live(this.screenStream)&&this.screenStream.getVideoTracks()[0].getSettings().displaySurface==='monitor'};
    this.lastOrganFlags=JSON.stringify(flags);
    this.api('/organs',flags).catch(error=>this.fail(error.message));
  }
  changed() {
    const current=this.state();
    const flags={screen_sharing:current.screen_sharing,screen_watch:current.screen_watch,webcam:current.webcam,full_screen:current.screen_sharing&&this.screenStream.getVideoTracks()[0].getSettings().displaySurface==='monitor'};
    if(JSON.stringify(flags)!==this.lastOrganFlags)this.publishOrgans();
    this.onChange(current);
  }
  async startScreen(watch=false) {
    if(!navigator.mediaDevices?.getDisplayMedia) throw new Error('שיתוף מסך אינו זמין בדפדפן הזה. פתח את ג׳רוויס ב־Chrome במחשב.');
    if(this.live(this.screenStream)) {
      if(watch && this.screenStream.getVideoTracks()[0].getSettings().displaySurface!=='monitor') {
        this.stopScreen(false);
        this.say('לשמירה על המסך צריך לבחור את כל המסך בחלון השיתוף.');
      } else { if(watch) this.enableWatch(); return; }
    }
    let stream;
    try{stream=await navigator.mediaDevices.getDisplayMedia({video:{displaySurface:'monitor',frameRate:5},audio:false,preferCurrentTab:false,selfBrowserSurface:'exclude',monitorTypeSurfaces:'include',surfaceSwitching:'include'});}
    catch(error){
      if(error.name==='NotAllowedError')throw new Error('שיתוף המסך לא אושר בדפדפן או ב־macOS. אפשר לנסות שוב מכפתור שיתוף המסך ולבדוק את הרשאת הקלטת המסך של Chrome.');
      if(error.name==='InvalidStateError')throw new Error('כדי לפתוח את בחירת המסך צריך ללחוץ על כפתור שיתוף המסך.');
      throw new Error(`לא הצלחתי להתחיל שיתוף מסך: ${error.message}`);
    }
    const track=stream.getVideoTracks()[0];
    if(watch && track.getSettings().displaySurface!=='monitor') {
      stream.getTracks().forEach(t=>t.stop());
      throw new Error('נבחרה לשונית או חלון. כדי לשים לב למסך העבודה צריך לבחור ״כל המסך״. לחץ שוב על שמירה על המסך ובחר מסך שלם.');
    }
    this.screenStream=stream;this.screenEnded=false;this.screenGeneration++;
    this.screenVideo.srcObject=stream;await this.screenVideo.play();
    track.addEventListener('ended',()=>{this.stopScreen(false);this.screenEnded=true;this.fail('שיתוף המסך הסתיים. כדי שאוכל לראות שוב, התחל שיתוף חדש.');},{once:true});
    if(watch)this.enableWatch();
    this.changed();
  }
  enableWatch() {
    if(this.watching)return;
    this.watching=true;this.lastPixels=null;this.lastChange=Date.now();this.lastNudge=0;
    this.watchTimer=setInterval(()=>this.watchTick(),WATCH_SAMPLE_MS);
    this.api('/watch',{enabled:true,full_screen:true}).catch(error=>this.fail(error.message));
    this.watchHeartbeat=setInterval(()=>this.api('/watch',{enabled:this.watching&&this.live(this.screenStream),full_screen:true}).catch(error=>this.fail(error.message)),WATCH_HEARTBEAT_MS);
    this.changed();
  }
  stopScreen(announce=true) {
    clearInterval(this.watchTimer);clearInterval(this.watchHeartbeat);this.watchTimer=null;this.watchHeartbeat=null;this.watching=false;this.screenGeneration++;
    this.api('/watch',{enabled:false,full_screen:false}).catch(()=>{});
    this.screenStream?.getTracks().forEach(t=>t.stop());this.screenStream=null;
    this.screenVideo.srcObject=null;this.lastPixels=null;this.lastDiff=null;this.screenEnded=true;this.changed();
    if(announce)this.say('שיתוף המסך כבוי.');
  }
  capture(source) {
    const stream=source==='webcam'?this.cameraStream:this.screenStream;
    const video=source==='webcam'?this.cameraVideo:this.screenVideo;
    if(!this.live(stream)) throw new Error(source==='webcam'?'המצלמה כבויה. הפעל אותה לפני הבקשה.':this.screenEnded?'שיתוף המסך הסתיים. צריך לשתף שוב לפני שאוכל לענות על המסך.':'אין שיתוף מסך פעיל. לחץ על שיתוף מסך ובחר מה להראות לי.');
    if(!video.videoWidth || video.readyState<2)throw new Error('התמונה עדיין אינה מוכנה. נסה שוב בעוד רגע.');
    const canvas=document.createElement('canvas');
    const scale=Math.min(1,MAX_FRAME_WIDTH/video.videoWidth);
    canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);
    canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
    const image=canvas.toDataURL('image/jpeg',JPEG_QUALITY);
    if(!image.startsWith('data:image/jpeg;base64,'))throw new Error('קידוד תמונת JPEG נכשל.');
    // This frame is created for this question, and never stored on the instance.
    return {image,media_type:'image/jpeg',source};
  }
  async see(question,source='screen') {
    const generation=source==='webcam'?this.cameraGeneration:this.screenGeneration;
    const result=await this.api('/see',{question,...this.capture(source)});
    if(generation!==(source==='webcam'?this.cameraGeneration:this.screenGeneration))throw new Error(source==='webcam'?'המצלמה נסגרה בזמן הבקשה. התשובה לא הוצגה.':'השיתוף הסתיים בזמן הבקשה. התשובה לא הוצגה.');
    return result;
  }
  async watchTick() {
    if(!this.watching || !this.live(this.screenStream) || this.watchBusy)return;
    // A picker can switch from a screen to a tab after startup.
    if(this.screenStream.getVideoTracks()[0].getSettings().displaySurface!=='monitor') {
      this.stopScreen(false);this.fail('השיתוף עבר ללשונית. שמירה על המסך דורשת מסך שלם.');return;
    }
    const canvas=document.createElement('canvas');canvas.width=DIFF_WIDTH;canvas.height=DIFF_HEIGHT;
    const ctx=canvas.getContext('2d',{willReadFrequently:true});
    ctx.drawImage(this.screenVideo,0,0,DIFF_WIDTH,DIFF_HEIGHT);
    const pixels=ctx.getImageData(0,0,DIFF_WIDTH,DIFF_HEIGHT).data;
    this.lastDiff=pixelDifference(this.lastPixels,pixels);this.lastPixels=new Uint8ClampedArray(pixels);
    const now=Date.now();
    if(this.lastDiff>PIXEL_CHANGE_THRESHOLD)this.lastChange=now;
    this.changed();
    if(now<this.quietUntil() || now-this.lastChange<WATCH_STILL_MS || now-this.lastNudge<WATCH_COOLDOWN_MS)return;
    this.watchBusy=true;this.lastNudge=now;this.changed();
    try {
      const result=await this.see('המסך נשאר כמעט ללא שינוי יותר מדקה. הצע צעד מעשי אחד לפי מה שרואים. משפט או שניים, הומור יבש אם מתאים. אל תניח שהמשתמש מוסח ואל תמציא מה חסר מחוץ לתמונה.','screen');
      if(this.watching && Date.now()>=this.quietUntil())this.answer(result);
    } catch(error) { this.fail(error.message); }
    finally {this.watchBusy=false;this.changed();}
  }
  async startCamera() {
    if(this.live(this.cameraStream))return;
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('אין גישה למצלמה בדפדפן הזה.');
    try{this.cameraStream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:640},height:{ideal:480},facingMode:'user'},audio:false});}
    catch(error){
      if(error.name==='NotAllowedError')throw new Error('הגישה למצלמה לא אושרה. בדוק את הרשאת המצלמה לדפדפן ונסה שוב.');
      if(error.name==='NotFoundError')throw new Error('לא נמצאה מצלמה מחוברת.');
      throw new Error(`לא הצלחתי להפעיל את המצלמה: ${error.message}`);
    }
    const generation=++this.cameraGeneration;
    this.cameraVideo.srcObject=this.cameraStream;await this.cameraVideo.play();
    this.cameraStream.getVideoTracks()[0].addEventListener('ended',()=>this.stopCamera(false),{once:true});
    this.changed();
    if(!this.earsOn())this.say('המיקרופון כבוי, אדוני. לחץ על כפתור המיקרופון כדי לדבר איתי.');
    try {
      const {FilesetResolver,PoseLandmarker,FaceLandmarker}=await import(`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VERSION}/vision_bundle.mjs`);
      const files=await FilesetResolver.forVisionTasks(`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VERSION}/wasm`);
      const pose=await PoseLandmarker.createFromOptions(files,{baseOptions:{modelAssetPath:POSE_MODEL,delegate:'CPU'},runningMode:'VIDEO',numPoses:1,minPoseDetectionConfidence:.5,minTrackingConfidence:.5});
      let face;
      try{face=await FaceLandmarker.createFromOptions(files,{baseOptions:{modelAssetPath:FACE_MODEL,delegate:'CPU'},runningMode:'VIDEO',numFaces:1,minFaceDetectionConfidence:.5,minTrackingConfidence:.5});}
      catch(error){pose.close();throw error;}
      if(generation!==this.cameraGeneration){pose.close();face.close();return;}
      this.pose=pose;this.face=face;
      this.poseTimer=setInterval(()=>this.poseTick(),POSE_SAMPLE_MS);
    } catch(error) { if(generation!==this.cameraGeneration)return;this.stopCamera(false);throw new Error(`זיהוי התנוחה המקומי לא נטען. ${error.message}`); }
  }
  async poseTick() {
    if(!this.live(this.cameraStream)||!this.pose||!this.face||this.cameraVideo.readyState<2)return;
    try {
      const now=performance.now();
      const pose=this.pose.detectForVideo(this.cameraVideo,now);
      const face=this.face.detectForVideo(this.cameraVideo,now);
      this.posture=postureFromLandmarks(pose.landmarks,face.faceLandmarks);
      if(now-this.lastPublish>=POSTURE_PUBLISH_MS){this.lastPublish=now;await this.api('/focus/posture',{...this.posture,active:true});}
      this.changed();
    } catch(error) {
      // Failure is visible; never claim that an unloaded detector is watching.
      this.stopCamera(false);this.fail(`זיהוי התנוחה נעצר: ${error.message}`);
    }
  }
  stopCamera(announce=true) {
    this.cameraGeneration++;clearInterval(this.poseTimer);this.poseTimer=null;
    this.cameraStream?.getTracks().forEach(t=>t.stop());this.cameraStream=null;this.cameraVideo.srcObject=null;
    this.pose?.close();this.face?.close();this.pose=null;this.face=null;
    this.posture={present:false,head_down:false,slouched:false};
    // active:false disables the lane rather than counting a stopped camera as absence.
    this.api('/focus/posture',{...this.posture,active:false}).catch(()=>{});
    this.changed();if(announce)this.say('המצלמה כבויה.');
  }
}
