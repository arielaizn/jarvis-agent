"""ElevenLabs credentials and audio stay on the local server boundary."""
import base64
import json
import re
import urllib.error
import urllib.request
import uuid
from core.credentials import read_config
from core.galaxy_brain import BrainError

API_ROOT='https://api.elevenlabs.io/v1'
MAX_AUDIO_BYTES=8_000_000
TIMEOUT_SECONDS=35

def config(path):
    data=read_config(path)
    if not data.get('elevenlabs_api_key'):raise BrainError('VOICE_KEY_MISSING','הזן מפתח ElevenLabs בהגדרות.',409)
    return data

def request(path,body,headers,key):
    try:
        req=urllib.request.Request(API_ROOT+path,data=body,headers={**headers,'xi-api-key':key},method='POST')
        with urllib.request.urlopen(req,timeout=TIMEOUT_SECONDS) as response:
            raw=response.read(MAX_AUDIO_BYTES+1)
            if len(raw)>MAX_AUDIO_BYTES:raise BrainError('VOICE_TOO_LARGE','תוצאת הקול גדולה מדי.',413)
            return raw
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError):
        raise BrainError('ELEVENLABS_UNAVAILABLE','ElevenLabs לא החזיר קול. בדוק מפתח, מכסה ומזהה קול בהגדרות.',503) from None

def speech(path,text):
    if not isinstance(text,str) or not text.strip() or len(text)>2400:raise BrainError('INVALID_SPEECH','הטקסט ריק או ארוך מדי.',400)
    data=config(path);voice=data.get('elevenlabs_voice','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',voice):raise BrainError('VOICE_ID_MISSING','הזן מזהה קול ElevenLabs בהגדרות.',409)
    body=json.dumps({'text':text,'model_id':'eleven_v3'}).encode()
    raw=request('/text-to-speech/'+voice+'/stream?output_format=mp3_44100_128',body,{'Content-Type':'application/json','Accept':'audio/mpeg'},data['elevenlabs_api_key'])
    return {'audio':'data:audio/mpeg;base64,'+base64.b64encode(raw).decode(),'voice_provider':'elevenlabs'}

def transcribe(path,payload):
    data=config(path);mime=payload.get('mime');audio=payload.get('audio')
    if mime not in {'audio/webm','audio/ogg','audio/mp4','audio/wav'} or not isinstance(audio,str) or len(audio)>MAX_AUDIO_BYTES*1.4:raise BrainError('INVALID_AUDIO','פורמט ההקלטה אינו תקין.',400)
    try:raw=base64.b64decode(audio,validate=True)
    except ValueError:raise BrainError('INVALID_AUDIO','ההקלטה אינה תקינה.',400) from None
    if not 0<len(raw)<=MAX_AUDIO_BYTES:raise BrainError('INVALID_AUDIO','ההקלטה ריקה או גדולה מדי.',400)
    boundary='jarvis-'+uuid.uuid4().hex
    def field(name,value):return ('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"\r\n\r\n'+value+'\r\n').encode()
    body=field('model_id','scribe_v2')+field('language_code','heb')+field('tag_audio_events','false')
    body+=('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="speech.'+mime.split('/')[1]+'"\r\nContent-Type: '+mime+'\r\n\r\n').encode()+raw+('\r\n--'+boundary+'--\r\n').encode()
    result=request('/speech-to-text',body,{'Content-Type':'multipart/form-data; boundary='+boundary},data['elevenlabs_api_key'])
    try:text=json.loads(result)['text']
    except (ValueError,KeyError):raise BrainError('INVALID_TRANSCRIPT','שירות הדיבור לא החזיר תמלול.',502) from None
    return {'text':str(text)[:12000]}
