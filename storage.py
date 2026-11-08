"""Server-only, write-only persistence. No cross-session result lookup."""

from urllib.parse import urlparse
from uuid import UUID

from supabase import create_client, ClientOptions


def save_result(result, exam_id, session_id, current_session_id, config):
    if session_id != current_session_id:
        raise PermissionError("다른 세션의 결과는 저장할 수 없습니다.")
    UUID(exam_id)
    UUID(session_id)
    url = config.get("SUPABASE_URL", "")
    key = config.get("SUPABASE_SECRET_KEY") or config.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return "미연결 · Supabase URL과 서버 키를 설정하면 저장할 수 있습니다."
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return "저장 실패 · Supabase URL은 HTTPS 주소여야 합니다."
    try:
        client = create_client(url, key, options=ClientOptions(postgrest_client_timeout=8))
        client.table("exam_results").upsert({"id": exam_id, "session_id": session_id,
                                            "result": result}, on_conflict="id").execute()
        return "저장 완료"
    except Exception:
        return "저장 실패 · Supabase 키·테이블·서버 연결을 확인하고 다시 저장해 주세요."
