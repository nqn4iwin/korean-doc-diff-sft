# data_collect

최종 후보 두 건의 데이터 수집 가능성을 검증하는 저장소입니다. 각 프로젝트 폴더는 수집 코드, 설정 예시, 계획, Solar 파일럿 입력과 결과를 독립적으로 보관합니다.

## 후보

- `01_public_data_review/`: 공공데이터 활용 사전검토
- `02_rfp_analysis/`: 공공사업 RFP·과업지시서 분석

각 폴더의 `README.md`에서 데이터 출처, 환경변수, 수집 명령과 현재 상태를 확인합니다. Solar 파일럿의 입력·프롬프트·실행 결과는 각 프로젝트의 `prompt_test/`에 있습니다.

## 로컬 데이터

수집 결과는 Git에서 제외되는 `data/<프로젝트명>/`에 생성합니다. 현재 `data/`는 재수집을 위해 비어 있으며, 수집 코드가 필요한 하위 경로를 만듭니다. 01번의 수집 이력은 `01_public_data_review/manifests/01_public_data_review.jsonl`에 남아 있습니다.

## 현재 구조

```text
.
├── 01_public_data_review/
│   ├── crawlers/
│   ├── docs/PLAN.md
│   └── prompt_test/
├── 02_rfp_analysis/
│   ├── crawlers/
│   ├── docs/PLAN.md
│   └── prompt_test/
├── solar.config.example.env
├── solar_request.json
└── docs/PLAN.md
```
