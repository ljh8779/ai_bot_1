# EC2 배포 복구/재사용 가이드 (ai_bot_1)

## 한눈에 요약
- 목표: EC2에 `ai_bot_1`를 올리고, 웹에서 RAG 챗봇을 안정적으로 운영
- 핵심 구성: `db(pgvector)` + `api(FastAPI)` + `caddy(리버스프록시)`
- 점검 기준: 내부는 `127.0.0.1 + Host 헤더`, 외부는 `https://도메인`

## 1. 처음 배포(최소 절차)
### 1) 레포 준비
```bash
cd /tmp
git clone https://github.com/ljh8779/ai_bot_1.git
cd ai_bot_1
```

### 2) 환경파일 준비
```bash
cp .env.prod.example .env.prod
```

필수값:
- `DOMAIN=13.239.240.225.nip.io`
- `ACME_EMAIL=실사용이메일`
- `GOOGLE_API_KEY=유효한키`
- `POSTGRES_PASSWORD=강한비밀번호`
- `BULK_INGEST_HOST_DIR=/opt/ai_bot_folder` (권장)

### 3) 일괄처리 폴더 준비
```bash
mkdir -p /opt/ai_bot_folder
```

### 4) 배포
```bash
bash scripts/deploy_prod.sh
```

## 2. 정상 여부 확인
### 컨테이너 상태
```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

### 내부 라우팅 체크(Caddy 경유)
```bash
source .env.prod
curl -i -H "Host: ${DOMAIN}" http://127.0.0.1/health
```

### 외부 접속 체크
```bash
curl -I https://${DOMAIN}/health
```

## 3. 자주 발생한 오류와 해결
### A) `api`가 `unhealthy`
증상:
- `ai_bot_1-api-1 is unhealthy`
- 로그에 `/health 503` 반복

이유:
- `/health`가 DB만 보는 게 아니라 LLM 연결/모델 존재까지 검사
- Google 키/쿼터/모델 이슈면 503

조치:
```bash
bash scripts/fix_unhealthy_now.sh
```

### B) `curl 127.0.0.1:8000` 연결 실패
이유:
- 프로덕션에서 `api`는 `expose`만 사용(호스트 8000 미공개)

정상 체크:
```bash
curl -i -H "Host: ${DOMAIN}" http://127.0.0.1/health
```

### C) HTTPS 443 타임아웃
대표 원인:
- 보안그룹 인바운드가 22만 열림

해결:
- 인바운드 규칙 추가
- `HTTP 80 / 0.0.0.0/0`
- `HTTPS 443 / 0.0.0.0/0`

### D) `Google API key not valid`
해결:
```bash
sed -i 's|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=새키|' .env.prod
sudo docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --force-recreate api
```

추가 확인:
- Google 키 제한(Referrer/IP/API 제한)
- `Generative Language API` 허용 여부

## 4. HTTPS 안 될 때 임시 운영(HTTP)
```bash
bash scripts/run_http_only.sh
```

접속:
- `http://${DOMAIN}`

## 5. 일괄처리 파일 위치
파일 넣는 위치:
- 호스트: `BULK_INGEST_HOST_DIR` 값 (예: `/opt/ai_bot_folder`)
- 컨테이너: `/bulk_ingest`로 마운트

사용:
- 웹 UI `일괄처리` 버튼 클릭
- `.zip` 지원 (압축 내부 지원 파일도 처리)

## 6. 운영 빠른 명령
### 일반 재기동
```bash
bash scripts/run_prod_now.sh
```

### 장애 복구
```bash
bash scripts/fix_unhealthy_now.sh
```

### 상태/로그 확인
```bash
bash scripts/check_prod.sh
```

## 7. 재사용 체크리스트
- [ ] `.env.prod` 최신화 (DOMAIN/KEY/PASSWORD)
- [ ] 보안그룹 22/80/443 열림
- [ ] `docker compose ps`에서 `db/api/caddy` 상태 확인
- [ ] 내부 체크(`127.0.0.1 + Host`) 성공
- [ ] 외부 도메인 접속 성공

## 8. 다음 배포 때 바로 할 3개
1. `.env.prod`의 `ACME_EMAIL`, `GOOGLE_API_KEY` 유효값 유지
2. 배포 후 `bash scripts/check_prod.sh` 실행
3. 장애 시 `bash scripts/fix_unhealthy_now.sh` 먼저 실행 후 로그 확인
