"""Bounded TypeSafe judgments. Credentials stay in Jarvis's private store."""
from __future__ import annotations

import json
import math
import sys
import urllib.error
import urllib.request

from core.credentials import read_config

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_SECONDS = 45
MAX_BYTES = 256_000
MAX_QUESTIONS = 32


class TypeSafeError(ValueError):
    """Only stable error codes, never remote bodies or authorization headers."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _valid_data(value):
    return isinstance(value, (str, dict, list)) and bool(value)


def _number(value, low=0, high=1):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and low <= value <= high)


def _request_data(state, questions):
    if not _valid_data(state) or not isinstance(questions, dict) or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise TypeSafeError("TYPESAFE_INVALID_REQUEST")
    for name, question in questions.items():
        if not isinstance(name, str) or not name or not isinstance(question, dict):
            raise TypeSafeError("TYPESAFE_INVALID_QUESTION")
        kind, criteria = question.get("type"), question.get("criteria")
        if not isinstance(kind, str) or kind not in {"choice", "noul", "score"} or not _valid_data(question.get("instructions")):
            raise TypeSafeError("TYPESAFE_INVALID_QUESTION")
        if kind == "choice" and (not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255
                                 or not all(isinstance(k, str) and k for k in criteria)):
            raise TypeSafeError("TYPESAFE_INVALID_CRITERIA")
        if kind == "score" and (not isinstance(criteria, list) or not 2 <= len(criteria) <= 10):
            raise TypeSafeError("TYPESAFE_INVALID_CRITERIA")
        if kind == "noul" and criteria is not None and (not isinstance(criteria, dict) or not set(criteria) <= {"true", "false"}):
            raise TypeSafeError("TYPESAFE_INVALID_CRITERIA")
    try:
        data = json.dumps({"state": state, "model": MODEL, "questions": questions},
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise TypeSafeError("TYPESAFE_INVALID_REQUEST") from None
    if len(data) > MAX_BYTES:
        raise TypeSafeError("TYPESAFE_REQUEST_TOO_LARGE")
    return data


def _answers(result, questions):
    if not isinstance(result, dict) or not isinstance(result.get("model"), str):
        raise TypeSafeError("TYPESAFE_INVALID_RESPONSE")
    answers = result.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise TypeSafeError("TYPESAFE_INVALID_RESPONSE")
    clean = {}
    for name, question in questions.items():
        answer, kind = answers[name], question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            raise TypeSafeError("TYPESAFE_INVALID_RESPONSE")
        if kind == "noul":
            if not _number(answer.get("noul")):
                raise TypeSafeError("TYPESAFE_INVALID_RESPONSE")
            clean[name] = {"type": kind, "noul": answer["noul"]}
            continue
        expected = (set(question["criteria"]) if kind == "choice"
                    else {str(i) for i in range(len(question["criteria"]))})
        probs = answer.get("probabilities")
        if (not isinstance(probs, dict) or set(probs) != expected
                or not all(_number(p) for p in probs.values())
                or abs(sum(probs.values()) - 1) > .02
                or not _number(answer.get("confidence"))):
            raise TypeSafeError("TYPESAFE_INVALID_RESPONSE")
        if kind == "choice" and (not isinstance(answer.get("choice"), str) or answer["choice"] not in expected):
            raise TypeSafeError("TYPESAFE_INVALID_RESPONSE")
        if kind == "score" and not _number(answer.get("score"), 0, len(expected) - 1):
            raise TypeSafeError("TYPESAFE_INVALID_RESPONSE")
        clean[name] = {k: answer[k] for k in ("type", kind, "probabilities", "confidence")}
        if kind == "score":
            clean[name]["legend"] = {str(i): text for i, text in enumerate(question["criteria"])}
    return {"model": result["model"], "answers": clean}


def evaluate(state, questions):
    """Send only the explicitly supplied state. No automatic notes or screen access."""
    data = _request_data(state, questions)
    try:
        key = read_config().get("typesafe_api_key", "")
    except Exception:
        raise TypeSafeError("TYPESAFE_CREDENTIAL_UNREADABLE") from None
    if not isinstance(key, str) or not key or any(c.isspace() for c in key):
        raise TypeSafeError("TYPESAFE_KEY_MISSING")
    request = urllib.request.Request(ENDPOINT, data=data, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise TypeSafeError("TYPESAFE_RESPONSE_TOO_LARGE")
        return _answers(json.loads(raw), questions)
    except urllib.error.HTTPError as exc:
        raise TypeSafeError("TYPESAFE_HTTP_" + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise TypeSafeError("TYPESAFE_CONNECTION_FAILED") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise TypeSafeError("TYPESAFE_INVALID_RESPONSE") from None


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise TypeSafeError("TYPESAFE_REQUEST_TOO_LARGE")
        data = json.loads(raw)
        result = evaluate(data["state"], data["questions"])
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (TypeSafeError, KeyError, TypeError, ValueError) as exc:
        code = str(exc) if isinstance(exc, TypeSafeError) else "TYPESAFE_INVALID_REQUEST"
        print(json.dumps({"ok": False, "error": code}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
