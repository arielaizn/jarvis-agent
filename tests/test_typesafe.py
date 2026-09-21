import io
import json
import urllib.error

import pytest

from core import typesafe_client as client

QUESTIONS = {"route": {"type": "choice", "instructions": "Which category fits?",
                       "criteria": {"code": "Software", "none": "No matching category"}}}
REPLY = {"model": "jev-test", "answers": {"route": {
    "type": "choice", "choice": "code", "probabilities": {"code": .9, "none": .1}, "confidence": .8}}}


def test_auth_private_fixed_endpoint_and_whitelisted_response(monkeypatch):
    seen = []
    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            assert timeout == client.TIMEOUT_SECONDS
            return io.BytesIO(json.dumps(REPLY | {"unexpected": "do not expose"}).encode())
    monkeypatch.setattr(client, "read_config", lambda: {"typesafe_api_key": "private-sentinel"})
    monkeypatch.setattr(client.urllib.request, "build_opener", lambda *args: Opener())
    result = client.evaluate("Fix this error", QUESTIONS)
    assert result == REPLY and "private-sentinel" not in json.dumps(result)
    assert seen[0].full_url == client.ENDPOINT
    assert seen[0].headers["Authorization"] == "Bearer private-sentinel"
    assert "private-sentinel" not in seen[0].data.decode()


def test_remote_error_cannot_expose_headers_or_body(monkeypatch):
    class Opener:
        def open(self, *args, **kwargs):
            raise urllib.error.HTTPError(client.ENDPOINT, 401, "private-sentinel", {},
                                         io.BytesIO(b"private-sentinel"))
    monkeypatch.setattr(client, "read_config", lambda: {"typesafe_api_key": "private-sentinel"})
    monkeypatch.setattr(client.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(client.TypeSafeError, match="^TYPESAFE_HTTP_401$"):
        client.evaluate("test", QUESTIONS)


@pytest.mark.parametrize("change", [
    {"choice": "invented"}, {"choice": []}, {"confidence": float("nan")},
    {"probabilities": {"code": .5, "unexpected": .5}},
    {"probabilities": {"code": .1, "none": .1}}, {"type": "score"},
])
def test_invalid_decisions_are_rejected(change):
    reply = json.loads(json.dumps(REPLY))
    reply["answers"]["route"].update(change)
    with pytest.raises(client.TypeSafeError, match="TYPESAFE_INVALID_RESPONSE"):
        client._answers(reply, QUESTIONS)


def test_redirects_never_forward_credentials():
    assert client._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid") is None


def test_malformed_question_type_is_a_clean_error():
    with pytest.raises(client.TypeSafeError, match="TYPESAFE_INVALID_QUESTION"):
        client._request_data("test", {"route": {"type": {}, "instructions": "Choose"}})


def test_request_bounded_before_reading_credentials(monkeypatch):
    monkeypatch.setattr(client, "read_config", lambda: pytest.fail("credential read too early"))
    with pytest.raises(client.TypeSafeError, match="TYPESAFE_REQUEST_TOO_LARGE"):
        client.evaluate("a" * client.MAX_BYTES, QUESTIONS)


def test_noul_and_score_validate_ranges():
    questions = {"n": {"type": "noul"}, "s": {"type": "score", "criteria": ["Low", "High"]}}
    result = {"model": "test", "answers": {"n": {"type": "noul", "noul": .6},
              "s": {"type": "score", "score": .7, "probabilities": {"0": .3, "1": .7}, "confidence": .5}}}
    assert client._answers(result, questions)["answers"]["s"]["legend"] == {"0": "Low", "1": "High"}
    result["answers"]["n"]["noul"] = True
    with pytest.raises(client.TypeSafeError):
        client._answers(result, questions)
