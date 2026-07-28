# 01. 공공데이터 활용 사전검토 데이터

공공데이터 활용 시 확인해야 하는 법령, 이용조건, 개인정보와 저작권 관련 공식
자료를 수집하고, 사전검토용 SFT 데이터셋을 만들 수 있는지 검증한다.

이 디렉터리는 모델이나 챗봇 서비스를 구현하지 않는다. 공식 원천을 재현 가능하게
수집하고, 출처와 버전을 보존하며, 판단 사례를 구조화할 수 있는지 확인하는 데
집중한다.

## 현재 범위

- 국가법령정보 공동활용 Open API
  - 현행법령 및 행정규칙
  - 법령해석례
  - 개인정보보호위원회·행정안전부·문화체육관광부의 부처별 법령해석
  - 판례·행정심판례·결정례
  - 법령용어 및 관련 연계정보
- 공공데이터포털 목록조회서비스
- 개인정보보호위원회 안내서
- 공공누리 이용조건

초기 구현은 국가법령정보의 현행법령 검색과 공공데이터포털의 데이터셋 목록 조회를
대상으로 한다. 두 API의 응답 형식과 저장 가능성을 확인한 뒤 수집 범위를 확장한다.

세부 계획은 `docs/PLAN.md`에서 관리한다.

## 인증정보 설정

저장소에 포함된 `config.example.env`를 참고하여 이 디렉터리에 `.env` 파일을 직접
만든다.

```dotenv
LAW_OPEN_API_OC=국가법령정보 공동활용에서 직접 정한 OC
DATA_GO_KR_SERVICE_KEY=공공데이터포털 일반 인증키
```

`.env`는 Git에서 무시된다. 인증값을 코드, manifest, 명령행 인자 또는 채팅에
기록하지 않는다.

공공데이터포털 키는 우선 `일반 인증키(Decoding)` 값을 사용한다. 호출 결과가 인증
오류인 경우에만 API 명세와 키 인코딩 방식을 다시 확인한다.

## 실행 환경

- Python 3.11 이상 권장
- 외부 Python 패키지 없음
- 인터넷 연결 필요

## 최소 수집 테스트

국가법령정보에서 법령명으로 검색한다.

```powershell
python .\01_public_data_review\crawlers\law.py `
  --query "개인정보 보호법" `
  --display 5
```

공공데이터포털에서 전체 데이터셋의 첫 페이지를 조회한다.

```powershell
python .\01_public_data_review\crawlers\data_portal.py `
  --endpoint dataset `
  --per-page 5
```

다른 목록은 `--endpoint`로 선택한다.

```text
dataset
file-data-list
open-data-list
standard-data-list
```

## 산출물

API 수집 응답:

```text
data/01_public_data_review/raw/
├── data_portal/
└── law/
```

수집 manifest:

```text
manifests/01_public_data_review.jsonl
```

manifest에는 다음 정보만 남긴다.

- 공식 원천명과 인증정보가 제거된 endpoint
- 수집시각
- 요청 종류와 비밀정보가 아닌 검색 조건
- 응답 파일의 상대 경로, 크기와 SHA-256

## 보안 및 데이터 관리

- `.env`와 `data/`는 Git에 커밋하지 않는다.
- API가 응답 링크에 인증값을 포함하면 저장 전에 `<redacted>`로 마스킹한다.
- API 오류 메시지에도 인증값이 포함되지 않도록 요청 URL 전체를 출력하지 않는다.
- 법령 및 안내서의 출처·시행일·개정일을 보존한다.
- 원본 응답을 수정하지 않고 후속 파서는 별도의 `interim` 결과를 만든다.
- 법률 판단을 임의로 Gold 라벨로 만들지 않는다.
