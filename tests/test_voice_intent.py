from core.voice_intent import VoiceIntentGate


def judge(choice='direct_request', probability=.98):
    return lambda *args,**kwargs: {'answers':{'address':{'choice':choice,'probabilities':{'direct_request':probability}}}}


def test_noise_never_reaches_semantic_service():
    def forbidden(*a,**k):raise AssertionError('noise leaked to classifier')
    gate=VoiceIntentGate(judge=forbidden)
    for text in ('אההה','תודה שצפיתם','...', '123', 'hmm', 'okay', 'ג׳רוויס תודה'):
        assert not gate.decide(text)['accepted']


def test_explicit_address_is_fast_and_removed_for_stop_routing():
    def forbidden(*a,**k):raise AssertionError('explicit command should not wait on network')
    gate=VoiceIntentGate(judge=forbidden)
    assert gate.decide('ג׳רוויס תפתח את בלנדר')['text']=='תפתח את בלנדר'
    assert gate.decide('Jarvis, stop')['text']=='stop'


def test_direct_natural_requests_and_ambient_speech_are_distinct():
    assert VoiceIntentGate(judge=judge()).decide('תפתח בבקשה את בלנדר')['accepted']
    assert not VoiceIntentGate(judge=judge('background_or_noise',.01)).decide('יוסי תביא לי מים')['accepted']
    assert not VoiceIntentGate(judge=judge('uncertain',.6)).decide('אולי נעשה את זה')['accepted']


def test_classifier_failure_is_silent_and_closed():
    def broken(*a,**k):raise TimeoutError()
    result=VoiceIntentGate(judge=broken).decide('אולי זה תמלול של הטלוויזיה')
    assert result=={'accepted':False,'reason':'use_explicit_address'}
    assert 'text' not in result


def test_duplicate_asr_does_not_create_a_second_task_or_store_transcripts():
    now=[0]
    gate=VoiceIntentGate(judge=judge(),clock=lambda:now[0])
    text='ג׳רוויס תפתח את בלנדר'
    assert gate.decide(text)['accepted']
    assert gate.decide(text)['reason']=='duplicate'
    assert text not in repr(vars(gate))
    now[0]=5
    assert gate.decide(text)['accepted']


def test_short_answer_requires_an_explicit_answer_window():
    assert not VoiceIntentGate(judge=judge()).decide('כן')['accepted']
    assert VoiceIntentGate(judge=judge()).decide('כן',awaiting_answer=True)['accepted']
