# Solar 파일럿 — 02 공문서 차이 분석·해석

이 폴더에는 두 공문서의 고정 입력, 프롬프트, 실행 코드와 실행 결과가 있다. 현재 표본은 사전규격·입찰공고지만, 프롬프트의 분석 목적은 문서 유형에 제한되지 않는다. Solar·Langfuse 설정은 저장소 루트의 `.env`에서 읽고, 비밀값 없는 항목은 루트의 `solar.config.example.env`를 참고한다.

```powershell
python .\synthetic_generation\prompt_test\run.py
```

실행 결과와 해석은 `experiment_report.md` 및 `runs/`에서 확인한다.
