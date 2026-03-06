# Groupware RAG Bot - Flow Work & AI Study Report (2026-02-26)

## 1. 프로젝트 개요
- 프로젝트명: **Groupware RAG Bot (Self-Hosted MVP)**
- 목적: 사내 문서를 수집(ingest)하고 RAG로 질문에 답변하며, 답변 근거(출처 청크)를 제공
- 핵심 스택: FastAPI + PostgreSQL/pgvector + Ollama + 웹 콘솔

## 2. 런타임 아키텍처
- API 계층: `app/main.py`
- RAG 로직: `app/services/rag.py`
- LLM 연동: `app/services/llm.py`
- 웹 UI: `app/web/index.html`, `app/web/app.js`

## 3. 서버 시작 플로우
1. FastAPI startup 이벤트 실행
2. DB 확장/테이블/인덱스 초기화
3. 실패 시 서비스 시작 중단

## 4. 헬스 체크 (`GET /health`)
1. DB 연결 확인 (`SELECT 1`)
2. Ollama 가용성 확인 (`/api/tags`)
3. 필수 모델 존재 여부 확인 (임베딩/챗)
4. 정상 시 `status=ok`, 실패 시 503 반환

## 5. 텍스트 수집 (`POST /documents/text`)
1. 요청 스키마 및 ACL 메타데이터 검증
2. 텍스트 정규화 + 청크 분할
3. SHA-256 해시 생성
4. 동일 해시 문서 중복 삽입 방지
5. 임베딩 배치 생성
6. 문서/청크 트랜잭션 저장

## 6. 파일 수집 (`POST /documents/file`)
- 지원 확장자: `.txt`, `.md`, `.pdf`, `.pptx`
- 업로드 용량 제한 검사
- 파일 타입별 텍스트 추출
- `metadata_json` 파싱 및 형식 검증

## 7. 질의응답 (`POST /chat`)
1. 질문 임베딩 생성
2. 벡터 코사인 거리 기반 후보 검색
3. ACL 필터 적용 (`allowed_departments`, `allowed_roles`)
4. 상위 컨텍스트 선별
5. LLM 호출 후 답변 + 출처 청크 반환

## 8. 튜닝 파라미터
- `CHUNK_SIZE`, `CHUNK_OVERLAP`
- `MAX_CONTEXT_CHUNKS`
- `SEARCH_CANDIDATE_MULTIPLIER`
- `INGEST_EMBEDDING_BATCH_SIZE`
- `OLLAMA_CHAT_TEMPERATURE`

## 9. 개선 과제
1. 통합 테스트 추가
2. Alembic 마이그레이션 도입
3. 구조화 로그 + 요청 추적 ID
4. 프롬프트 인젝션 방어 강화
5. reranker 도입
6. 하이브리드 검색(BM25 + 벡터) 도입

## 10. 결론
이 코드베이스는 ACL 기반 RAG MVP의 핵심 흐름(수집 -> 임베딩 -> 검색 -> 근거 기반 답변)이 구현되어 있으며,
다음 단계는 평가 체계와 자동화 테스트 강화입니다.
