import json
from pathlib import Path
from types import SimpleNamespace
import threading
import pytest
from build import NoteIndex
from core.command_center import CommandCenter, safe_note, validate_response
from core.galaxy_brain import BrainError

@pytest.fixture
def center(tmp_path):
    notes=tmp_path/'notes';notes.mkdir();(notes/'Existing.md').write_text('# Existing\nfinish window 900 milliseconds')
    index=NoteIndex(notes)
    app=SimpleNamespace(root=tmp_path,index=index,started_at=0,events=SimpleNamespace(emit=lambda *a:None))
    return CommandCenter(app)

def test_direct_write_requires_real_confirmation(center):
    with pytest.raises(BrainError,match='אישור'):center.tool('create_note',{'title':'New','content':'Do not write yet'})
    assert len(list(center.app.index.root.rglob('*.md')))==1

def test_approval_single_use_and_immediate_index(center):
    def plan(messages):return {'tool':'create_note','args':{'title':'Capture','content':'zebra finish window 901 milliseconds'}}
    center.plan=plan
    job={'id':'job','events':[],'status':'running'};center.jobs['job']=job
    center.run(job,'remember zebra','session')
    assert job['status']=='confirmation'
    assert not center.app.index.search('zebra')
    token=job['confirmation']['id']
    result=center.approve({'id':token,'approve':True})
    assert result['status']=='completed'
    assert center.app.index.search('zebra')
    assert list((center.app.index.root/'Inbox'/'JARVIS').glob('*.md'))
    with pytest.raises(BrainError):center.approve({'id':token,'approve':True})

def test_cancel_never_writes(center):
    center.plan=lambda _: {'tool':'create_note','args':{'title':'No','content':'not permitted'}}
    job={'id':'job','events':[],'status':'running'};center.jobs['job']=job;center.run(job,'note','s')
    center.approve({'id':job['confirmation']['id'],'approve':False})
    assert len(list(center.app.index.root.rglob('*.md')))==1

@pytest.mark.parametrize('name',['../secret.md','/etc/passwd','a/../../secret.md','.hidden.md','bad.txt','a\\secret.md'])
def test_traversal(center,name):
    with pytest.raises(BrainError):safe_note(center.app.index.root,name)

def test_symlink_rejected(center,tmp_path):
    (center.app.index.root/'link.md').symlink_to(tmp_path/'private.md')
    with pytest.raises(BrainError):safe_note(center.app.index.root,'link.md')

def test_unknown_tool_and_approval_flag_fail_closed(center):
    with pytest.raises(BrainError):center.tool('shell',{'command':'anything'})
    with pytest.raises(BrainError):center.tool('create_note',{'title':'a','content':'b','confirmed':True})

def test_settings_never_returns_secret(center):
    result=center.save_settings({'elevenlabs_api_key':'secret-test-marker'})
    assert result['elevenlabs_configured']
    assert 'secret-test-marker' not in json.dumps(center.status())
    assert center.settings_path.stat().st_mode&0o077==0

def test_model_html_is_only_plain_text(center):
    result=validate_response({'speech':'test','cards':[{'type':'email','title':'<script>x</script>','url':'javascript:alert(1)'}],'sources':[]})
    assert 'url' not in result['cards'][0]
    assert 'אדוני' in result['speech']

def test_holo_requires_user_gesture_and_preserves_local_assets():
    root=Path(__file__).resolve().parents[1]
    html=(root/'viewer/holo/holo.html').read_text()
    assert '\nstartCamera();' not in html
    assert '/holo/vendor/vision_bundle.mjs' in html
    assert 'HOLO SHIM' in (root/'viewer/holo/vendor/wasm/vision_wasm_internal.js').read_text()
