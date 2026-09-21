import pytest

from preflight import Harness


def test_busy_provider_can_recover_but_requires_a_real_success_response(tmp_path, monkeypatch):
    harness = Harness("http://127.0.0.1:4700", tmp_path)
    responses = iter([(503, {"error": {"code": "PROVIDER_BUSY"}}), (200, {"ok": True})])
    requests = []
    def request(route, body):
        requests.append((route, body))
        return next(responses)
    monkeypatch.setattr(harness, "request", request)
    monkeypatch.setattr("preflight.time.sleep", lambda delay: None)
    assert harness.api('/preflight/api', {}) == {"ok": True}
    assert requests == [('/preflight/api', {}), ('/preflight/api', {})]


def test_persistent_busy_is_still_a_failed_check(tmp_path, monkeypatch):
    harness = Harness("http://127.0.0.1:4700", tmp_path)
    monkeypatch.setattr(harness, "request", lambda *args: (503, {"error": {"code": "PROVIDER_BUSY"}}))
    monkeypatch.setattr("preflight.time.sleep", lambda delay: None)
    harness.check('live model', lambda: harness.api('/preflight/model', {}))
    assert harness.counts == {'pass': 0, 'fail': 1, 'warn': 0}
    assert harness.transient_retries == 1


def test_daily_quota_is_never_retried_or_reported_as_pass(tmp_path, monkeypatch):
    harness = Harness("http://127.0.0.1:4700", tmp_path)
    monkeypatch.setattr(harness, "request", lambda *args: (429, {"error": {"code": "API_DAILY_QUOTA"}}))
    monkeypatch.setattr("preflight.time.sleep", lambda delay: pytest.fail('daily quota must fail without sleeping'))
    harness.check('live model', lambda: harness.api('/preflight/model', {}))
    assert harness.counts == {'pass': 0, 'fail': 1, 'warn': 0}
    assert harness.transient_retries == 0
