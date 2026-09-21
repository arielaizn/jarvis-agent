from types import SimpleNamespace
from core import desktop_activity as activity


def test_information_questions_and_background_speech_do_not_compact():
    for question in ('מה זה בלנדר?', 'explain Blender materials', 'סכם את ההערות שלי'):
        assert not activity.desktop_request(question)
    for question in ('תפתח את בלנדר ותבנה דגם', 'תגלול בדפדפן', 'open Google Chrome'):
        assert activity.desktop_request(question)


def test_mac_activation_reuses_the_app_and_does_not_launch_new_instance(monkeypatch):
    commands=[]
    monkeypatch.setattr(activity.platform,'system',lambda:'Darwin')
    monkeypatch.setattr(activity.subprocess,'run',lambda args,**kwargs:commands.append(args) or SimpleNamespace(returncode=0))
    assert activity.present_requested_app('תקפיץ את בלנדר')['activated']
    assert commands==[['open','-a','Blender']]


def test_activation_failure_never_claims_success(monkeypatch):
    monkeypatch.setattr(activity.platform,'system',lambda:'Darwin')
    monkeypatch.setattr(activity.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    assert not activity.present_requested_app('תפתח את בלנדר')['activated']
