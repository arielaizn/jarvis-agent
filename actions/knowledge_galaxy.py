"""Native voice gateway to the live galaxy service."""
import json
from urllib.error import HTTPError
from core.galaxy_service import GalaxyServiceError, call, ensure_running, open_viewer

SAFE_ERRORS = {
    'API_KEY_NOT_CONFIGURED': 'המוח עדיין בלי מפתח API. פעולות מקומיות ושמירת הערות זמינות.',
    'API_AUTH_FAILED': 'ספק המודל דחה את המפתח או את ההרשאה למודל.',
    'API_CREDITS_REQUIRED': 'ספק המודל דיווח שאין יתרה זמינה בחשבון.',
    'API_RATE_LIMIT': 'ספק המודל הגיע למגבלת בקשות. נסה שוב בעוד רגע.',
    'MODEL_UNAVAILABLE': 'המודל המדויק אינו זמין דרך הספק. המוח נשאר כפי שהיה.',
    'UNKNOWN_MODEL': 'המודל המבוקש אינו ברשימת המודלים המוכרים. אפשר לראות את הרשימה בגלקסיה.',
    'CAPTURE_FAILED': 'לא הצלחתי להשלים את השמירה והאינדוקס. ההערה עדיין אינה זמינה לשאלות.',
    'PROVIDER_UNREACHABLE': 'אין כרגע חיבור לספק המודל.',
    'UNVERIFIED_SOURCES': 'המודל החזיר מקורות שאי אפשר לאמת. התשובה לא הוצגה.',
}


def _compact_capture(result):
    if isinstance(result.get('node'), dict) and 'graph' in result:
        return {'ok': result.get('ok', False), 'answer': result.get('answer', ''),
                'node_id': result['node'].get('id'), 'revision': result.get('revision')}
    return result


def knowledge_galaxy(parameters, ui=None, player=None, **_):
    ui = ui or player
    try:
        if not isinstance(parameters, dict):
            return json.dumps({'ok': False, 'code': 'INVALID_REQUEST', 'error': 'נדרשת פעולה תקינה.'}, ensure_ascii=False)
        action = parameters.get('action', 'open')
        if action == 'open':
            if ui is not None and callable(getattr(ui, 'open_galaxy', None)):
                ui.open_galaxy()
                result = {'ok': True, 'answer': 'גלקסיית ההערות נפתחת בתוך ג׳רוויס.'}
            else:
                result = open_viewer()
        else:
            ensure_running()
            if action == 'status':
                result = call()
            elif action in ('chat', 'remember', 'model'):
                field = {'chat': 'question', 'remember': 'text', 'model': 'name'}[action]
                payload = {field: parameters.get('text', '')}
                if action == 'chat':
                    payload.update(session_id='native-jarvis', client='native')
                result = call('/' + action, payload)
            elif action == 'focus':
                result = call('/chat', {'question': parameters.get('text', ''), 'session_id': 'native-jarvis', 'client': 'native'})
            elif action == 'diag':
                result = call('/focus/diag')
            else:
                raise ValueError('פעולה לא מוכרת')
        return json.dumps(_compact_capture(result), ensure_ascii=False)
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read(65537))
            code = payload.get('code') if isinstance(payload, dict) else None
            if code not in SAFE_ERRORS:
                code = 'SERVER_REQUEST_FAILED'
        except Exception:
            code = 'SERVER_REQUEST_FAILED'
        return json.dumps({'ok': False, 'code': code, 'error': SAFE_ERRORS.get(code, 'שרת הגלקסיה דחה את הבקשה.')}, ensure_ascii=False)
    except GalaxyServiceError as exc:
        return json.dumps({'ok': False, 'code': 'LOCAL_SERVICE_ERROR', 'error': str(exc)}, ensure_ascii=False)
    except Exception:
        return json.dumps({'ok': False, 'code': 'LOCAL_SERVICE_ERROR', 'error': 'לא הצלחתי להשלים את הפעולה בגלקסיה.'}, ensure_ascii=False)


TOOL = {
    'name': 'knowledge_galaxy',
    'description': 'גלקסיית ההערות בתוך ג׳רוויס: פתיחה, שאלה מתוך ההערות, זכירה בקובץ Markdown, החלפת מוח וסשן מיקוד. החלפת מוח חלה על הגלקסיה. מסך ומצלמה מופעלים בכפתורים בחלון ג׳רוויס.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'action': {'type': 'STRING', 'enum': ['open', 'status', 'chat', 'remember', 'model', 'focus', 'diag']},
        'text': {'type': 'STRING'}
    }, 'required': ['action']},
    'handler': knowledge_galaxy,
}
