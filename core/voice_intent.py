"""Decide whether a completed transcript is meant for Jarvis, before any speech.

No raw transcript, background conversation or judgment is persisted. The only
cached value is a short-lived digest used to suppress duplicate ASR results.
Explicit address is the fast path; ambiguous speech needs a bounded judgment.
"""
import hashlib
import re
import threading
import time
from core import typesafe_client

JUDGMENT_TIMEOUT_SECONDS = 1.25
ADDRESSED_PROBABILITY = .86
DUPLICATE_SECONDS = 4.0
MAX_TRANSCRIPT_CHARS = 1500
NAME = r"(?:jarvis|ג[׳'’]?אר?וויס|ג[׳'’]?רוויס|גארוויס|ג'ארוויס|ג׳ארוויס)"
ADDRESS = re.compile(r"^\s*(?:(?:hey|hi|hello|היי|הי|שלום|אוקיי|טוב)\s+)?" + NAME + r"(?:\b|[,،:!?.\s])", re.I)
NOISE = re.compile(r"^(?:[\W_\d]+|אה+|אמ+|ממ+|המ+|אוקיי|okay|ok|uh+|um+|hmm+|תודה|thanks|thank you|תודה רבה|תודה שצפיתם|תודה על הצפייה|music|מוזיקה|רעש|silence|צחוק|laughter)[.!?\s]*$", re.I)
QUOTED = re.compile(r"(?:אמרתי ל|אמר לו|תגיד לו|הוא אמר|היא אמרה|told (?:him|her)|he said|she said)",re.I)
QUESTIONS = {'address': {
    'type': 'choice',
    'instructions': ('Classify only the utterance in state. It came from an open microphone. '
        'Accept a clear direct request, command or question addressed to the desktop AI assistant Jarvis, '
        'including natural Hebrew requests without a wake word such as תפתח את בלנדר or מה יש לי בלוח השנה. '
        'Reject incidental speech, quoted commands, conversation with another person, television, '
        'a narration, filler, ASR noise, fragments and ambiguous cases. Do not execute anything. '
        'An isolated yes/no is not a command unless awaiting_answer is true.'),
    'criteria': {'direct_request': 'A clear utterance directed at the assistant.',
                 'background_or_noise': 'Ambient speech, narration, noise or another conversation.',
                 'uncertain': 'Not enough evidence of an intentional request to the assistant.'},
}}


class VoiceIntentGate:
    def __init__(self, judge=None, clock=time.monotonic):
        self._judge = judge or typesafe_client.evaluate
        self._clock = clock
        self._lock = threading.Lock()
        self._recent = {}

    def decide(self, text, *, awaiting_answer=False, task_active=False):
        if not isinstance(text, str) or not 2 <= len(text.strip()) <= MAX_TRANSCRIPT_CHARS:
            return {'accepted': False, 'reason': 'empty_or_invalid'}
        text = ' '.join(text.split())
        if task_active and re.fullmatch(r'(?:stop|cancel|עצור|תעצור|בטל|תבטל)(?: את המשימה)?[.!?]?',text,re.I):
            return {'accepted':True,'reason':'active_task_stop','text':text}
        if NOISE.fullmatch(text):
            return {'accepted': False, 'reason': 'noise'}
        digest = hashlib.sha256(text.casefold().encode()).digest()
        now = self._clock()
        with self._lock:
            self._recent = {key: expiry for key, expiry in self._recent.items() if expiry > now}
            if digest in self._recent:
                return {'accepted': False, 'reason': 'duplicate'}
            self._recent[digest] = now + DUPLICATE_SECONDS
        direct = ADDRESS.match(text)
        if direct and len(text[direct.end():].strip(' ,.!?:')) >= 2 and not QUOTED.search(text):
            clean = text[direct.end():].strip(' ,.!?:')
            if NOISE.fullmatch(clean):return {'accepted':False,'reason':'noise'}
            return {'accepted': True, 'reason': 'explicit_address', 'text': clean}
        if awaiting_answer:
            return {'accepted': True, 'reason': 'answer_window', 'text': text}
        if len(re.findall(r"[\w]+", text)) < 2:
            return {'accepted': False, 'reason': 'fragment'}
        try:
            result = self._judge({'utterance': text, 'awaiting_answer': False}, QUESTIONS,
                                 timeout=JUDGMENT_TIMEOUT_SECONDS)
            answer = result['answers']['address']
            accepted = (answer['choice'] == 'direct_request'
                        and answer['probabilities']['direct_request'] >= ADDRESSED_PROBABILITY)
            return ({'accepted':True,'reason':'direct_request','text':text} if accepted
                    else {'accepted':False,'reason':'not_addressed'})
        except Exception:
            # An unavailable classifier must not turn room noise into commands.
            return {'accepted': False, 'reason': 'use_explicit_address'}
