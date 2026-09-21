const NUMBER_WORDS = {'one':1,'two':2,'three':3,'five':5,'ten':10,'fifteen':15,'twenty':20,'thirty':30,'forty five':45,'sixty':60,'דקה':1,'אחת':1,'שתיים':2,'שתי':2,'שלוש':3,'חמש':5,'עשר':10,'חמש עשרה':15,'עשרים':20,'שלושים':30,'ארבעים וחמש':45,'שישים':60};
export const DEFAULT_FOCUS_MINUTES = 30;

export function durationValue(text, fallback) {
  const match = text.match(/\b(\d+(?:\.\d+)?)\b/);
  if(match) return Number(match[1]);
  for(const [word,value] of Object.entries(NUMBER_WORDS).sort((a,b) => b[0].length-a[0].length)) if(text.includes(word)) return value;
  return fallback;
}

export function routeCommand(raw, focusActive = false) {
  const text = raw.trim().replace(/[.!?]+$/,'');
  const low = text.toLowerCase().replaceAll('’',"'");
  // Re-target always precedes screen commands, including a natural lead-in.
  if(/(?:lock(?:\s+on)?|keep me in|stay on|this is)\s+(?:this|the)\s+tab|(?:תנעל|תינעל|נעל|תישאר|תשאיר אותי|זו|זאת)\s+(?:על\s+|ב)?(?:הלשונית|הטאב|הלשונית הזאת|הטאב הזה)/i.test(low)) return {type:'focus',action:'retarget',payload:{}};
  const capture = text.match(/^(?:remember that|remember this|תזכור ש|תזכר ש|זכור ש|תזכור את זה[:\s]*)\s*(.+)$/is);
  if(capture) return {type:'remember',text:capture[1].trim()};
  if(/^(?:remember that|remember this|תזכור ש|תזכר ש|זכור ש)$/i.test(low)) return {type:'remember',text:''};
  const model = text.match(/(?:switch to|try on|change (?:your )?brain to|תחליף ל[־-]?|החלף ל[־-]?|תעבור ל[־-]?)\s*(.+)$/i);
  if(model) return {type:'model',name:model[1].trim()};
  if(/go back to your normal brain|(?:תחזור|חזור) ל(?:מוח|מודל) (?:הרגיל|המקורי)/i.test(low)) return {type:'model',name:'default'};
  if(/no jarvis.*(?:important|need)|give me a minute|(?:אני צריך לעשות משהו חשוב|תן לי דקה|צריכה לעשות משהו חשוב)/i.test(low)) return {type:'focus',action:'relief',payload:{seconds:180}};
  if(/(?:drill sergeant|be strict|תקפיד איתי|מצב רס[״"]?ר|תהיה קשוח)/.test(low)) return {type:'focus',action:'drill',payload:{enabled:true}};
  if(/(?:stop being strict|normal callouts|תפסיק להיות קשוח|קצב רגיל)/.test(low)) return {type:'focus',action:'drill',payload:{enabled:false}};
  if(/(?:call me out|nag me).*every|(?:תעיר לי|תזכיר לי|תקרא לי).*כל/.test(low)) return {type:'focus',action:'cadence',payload:{seconds:durationValue(low,30)}};
  if(/(?:give me|snooze).*seconds|(?:תן לי|שקט ל|נמנם).*שניות/.test(low)) return {type:'focus',action:'snooze',payload:{seconds:durationValue(low,15)}};
  if(/(?:it'?s okay|it is okay|i am doing research|i'm doing research|excuse this)|(?:זה בסדר|אני עושה מחקר|זה לצורך מחקר)/.test(low)) return {type:'focus',action:'excuse',payload:{}};
  if(/(?:pause|השהה|תשהה|הפסקה)/.test(low) && (focusActive || /focus|session|ריכוז/.test(low))) return {type:'focus',action:'pause',payload:{}};
  if(/(?:resume|continue.*focus|תמשיך|המשך)/.test(low) && focusActive) return {type:'focus',action:'resume',payload:{}};
  if(/(?:abort|cancel.*session|בטל.*ריכוז|תבטל.*מפגש)/.test(low)) return {type:'focus',action:'abort',payload:{}};
  if(/(?:end.*session|finish.*session|סיים.*ריכוז|סיים.*מפגש)/.test(low)) return {type:'focus',action:'end',payload:{}};
  if(/(?:extend|add .*minutes|תוסיף.*דקות|הארך)/.test(low) && focusActive) return {type:'focus',action:'extend',payload:{minutes:durationValue(low,5)}};
  if(/(?:minutes on this|start.*focus|focus for|חצי שעה על זה|דקות על זה|התחל.*ריכוז|תתחיל.*ריכוז)/.test(low)) return {type:'focus',action:'start',payload:{minutes:/חצי שעה/.test(low)?30:durationValue(low,DEFAULT_FOCUS_MINUTES),from_jarvis:false}};
  if(/(?:watch my screen|תשמור על המסך|תעקוב אחרי המסך)/.test(low)) return {type:'watch'};
  if(/(?:stop.*(?:sharing|watching)|עצור.*שיתוף|תפסיק.*(?:שיתוף|לשמור))/.test(low)) return {type:'stop-screen'};
  if(/(?:share my screen|lock my screen|שתף.*מסך|תשתף.*מסך)/.test(low)) return {type:'screen-start'};
  if(/(?:turn (?:the )?(?:camera|eyes) on|start.*camera|הפעל.*מצלמה|תפעיל.*מצלמה)/.test(low)) return {type:'camera-start'};
  if(/(?:turn (?:the )?(?:camera|eyes) off|stop.*camera|כבה.*מצלמה|תכבה.*מצלמה)/.test(low)) return {type:'camera-stop'};
  // A screen question wins over all webcam phrases.
  if(/screen|מסך/.test(low)) return {type:'see',source:'screen',question:text};
  if(/look at me|(?:what.*(?:shirt|wearing|outfit))|תסתכל עליי|תסתכל עלי|(?:מה.*(?:חולצה|לובש|לובשת))/.test(low)) return {type:'see',source:'webcam',question:text};
  if(/what (?:do you think of this|am i looking at)|מה (?:דעתך על זה|אתה חושב על זה)|על מה אני מסתכל/.test(low)) return {type:'see',source:'screen',question:text};
  const smalltalk=/^(?:good morning|good evening|hello|hi|hey|thanks|thank you|tell me (?:a )?joke|בוקר טוב|ערב טוב|שלום|היי|תודה|ספר לי בדיחה)(?:\s+(?:jarvis|sir|ג.?רוויס|אחי))?$/.test(low);
  return {type:'question',question:text,smalltalk};
}

export function prettyModel(id) {
  return String(id || '').split('/').pop().replace(/(?<=\d)-(?=\d)/g,'.').replaceAll('-',' ').toUpperCase();
}
