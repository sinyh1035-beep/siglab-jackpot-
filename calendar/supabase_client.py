"""
SIGVIEW Calendar - Supabase 클라이언트
DB 연결 관리 모듈
"""
import os
from supabase import create_client, Client


def get_client() -> Client:
    """Supabase 클라이언트 반환"""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        raise ValueError(
            "SUPABASE_URL과 SUPABASE_KEY 환경변수가 필요합니다. "
            "GitHub Actions Secrets 또는 로컬 .env 확인하세요."
        )

    return create_client(url, key)


def test_connection():
    """연결 테스트 - 로컬에서 직접 실행 시 사용"""
    try:
        client = get_client()
        result = client.table("stocks").select("*").limit(1).execute()
        print(f"✅ Supabase 연결 성공!")
        print(f"   현재 stocks 테이블 행 수: {len(result.data)}개 (샘플)")
        return True
    except Exception as e:
        print(f"❌ Supabase 연결 실패: {e}")
        return False


if __name__ == "__main__":
    test_connection()
