"""
SIGVIEW Calendar - Supabase 클라이언트
DB 연결 관리 모듈

키 우선순위:
1. SUPABASE_SERVICE_KEY (쓰기 권한, GitHub Actions용)
2. SUPABASE_KEY (읽기 전용, 프론트엔드용 폴백)
"""
import os
from supabase import create_client, Client


def get_client() -> Client:
    """Supabase 클라이언트 반환 (service_role 우선)"""
    url = os.environ.get("SUPABASE_URL")

    # 쓰기가 필요한 작업(GitHub Actions)은 SERVICE_KEY 사용
    # 없으면 일반 anon key로 폴백 (읽기만 가능)
    key = (
        os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
    )

    if not url or not key:
        raise ValueError(
            "SUPABASE_URL과 SUPABASE_SERVICE_KEY (또는 SUPABASE_KEY) "
            "환경변수가 필요합니다. GitHub Actions Secrets를 확인하세요."
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
