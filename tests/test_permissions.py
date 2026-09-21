import json
import pytest
from core import permissions as p
from core import computer_mcp
from core import task_routing as routing


def test_onboarding_is_once_but_does_not_grant_access(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'runtime_root',lambda:tmp_path)
    changes=[];monkeypatch.setattr(p,'save_integrations',lambda v:changes.append(v))
    assert p.needs_onboarding()
    p.complete_onboarding()
    assert not p.needs_onboarding()
    assert not changes
    assert p.onboarding_path().stat().st_mode&0o077==0
    p.set_computer_access(True)
    assert changes==[{'codex':{'access_mode':'full'}}]
    with pytest.raises(ValueError):p.set_computer_access('true')


def test_full_setting_never_claims_os_permission(monkeypatch,tmp_path):
    monkeypatch.setattr(p,'runtime_root',lambda:tmp_path)
    monkeypatch.setattr(p,'load_integrations',lambda:{'codex':{'access_mode':'full'}})
    monkeypatch.setattr(p.platform,'system',lambda:'Darwin')
    monkeypatch.setattr(p,'_mac_bool',lambda *a:'required')
    result=p.capabilities()
    assert result['access_mode']=='full'
    assert result['accessibility']=='required'
    assert result['files']=='manual_check'
    assert result['network']=='not_checked'
    assert str(tmp_path) not in json.dumps(result)


def test_settings_destinations_are_allowlisted(monkeypatch):
    commands=[]
    monkeypatch.setattr(p.platform,'system',lambda:'Darwin')
    monkeypatch.setattr(p.subprocess,'Popen',lambda cmd,**kw:commands.append(cmd))
    assert not p.open_system_permission('files; arbitrary command')
    assert p.open_system_permission('accessibility')
    assert len(commands)==1 and commands[0][0]=='open'


def test_revoked_access_blocks_existing_mcp_process(monkeypatch):
    monkeypatch.setattr(computer_mcp,'load_integrations',lambda:{'codex':{'access_mode':'workspace'}})
    monkeypatch.setattr(computer_mcp,'registry',lambda:pytest.fail('Must not load or execute tools'))
    assert computer_mcp.computer_action('file_controller',{})['error']=='COMPUTER_ACCESS_DISABLED'
    assert computer_mcp.computer_tools()['error']=='COMPUTER_ACCESS_DISABLED'


@pytest.mark.parametrize('text',['תיצור תיקייה בהורדות','תפתח את בלנדר','copy this file into a new folder'])
def test_file_and_app_requests_reach_computer(text):
    assert routing.choose_lane(text,judge=lambda *a,**kw:pytest.fail('Fast path'))=='computer'


def test_uncertain_route_does_not_grant_access():
    def judge(*args,**kw):return {'answers':{'lane':{'choice':'computer','probabilities':{'computer':.4}}}}
    assert routing.choose_lane('something ambiguous',judge)=='workspace'
    assert routing.choose_lane('יש לך גישה לקבצים?',judge)=='capability'


def test_clean_install_uses_bundled_acknowledgment(tmp_path,monkeypatch):
    from core import acknowledgment
    monkeypatch.setattr(acknowledgment,'ROOT',tmp_path)
    monkeypatch.setattr(acknowledgment,'get_voice',lambda:'hebrew-deep')
    asset=tmp_path/'assets/voice/ack-hebrew-deep.wav';asset.parent.mkdir(parents=True)
    asset.write_bytes(b'RIFFtest-fixed-cue')
    assert acknowledgment.path()==asset
    assert acknowledgment.audio().startswith('data:audio/wav;base64,')
