"""승인된 원천 pair를 공식 사이트에서 받아 `data/raw_collection/`에 등록한다.

이름은 운영지침이지만 **주소만 있으면 어떤 원천이든 등록한다.** 국가법령정보센터 본문
HTML, 부처 게시판의 HWPX 첨부, 공정거래위원회 표준약관 첨부가 모두 같은 경로를 탄다.
받을 것은 아래 `PAIRS` 목록이 전부이고, 인자로 `directory` 값을 주면 그것만 받는다.

    python3 source_data/crawlers/collect_guideline_pairs.py <directory 값>

**넣기 전에 `check_candidate.py`로 합격을 받는다.** 이 스크립트는 수락 기준을 보지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw_collection"
CLASSIFIER = REPO / "source_data" / "classify_diff.py"
USER_AGENT = "data-collect/guideline-pairs"

PAIRS = [
    {
        "directory": "regional_industry_guideline_pair",
        "case_id": "regional-industry-guideline-2023__2026",
        "issuer": "산업통상자원부·산업통상부",
        "series": "지역산업지원사업 공통운영요령",
        "before": {
            "file": "before_2023.html",
            "date": "2023-02-03",
            "number": "산업통상자원부고시 제2023-21호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000218883",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000218883&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
        "after": {
            "file": "after_2026.html",
            "date": "2026-02-13",
            "number": "산업통상부고시 제2026-13호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000274750",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000274750&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
    },
    {
        "directory": "mss_rd_guideline_pair",
        "case_id": "mss-rd-guideline-2024__2025",
        "issuer": "중소벤처기업부",
        "series": "중소기업기술개발 지원사업 운영요령",
        "before": {
            "file": "before_2024.hwpx",
            "date": "2024-07-29",
            "number": "중소벤처기업부고시 제2024-54호",
            "page_url": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1052198&cbIdx=127&parentSeq=1052198&searchRltnYn=",
            "file_url": "https://www.mss.go.kr/common/board/Download.do?bcIdx=1052198&cbIdx=127&streFileNm=2afa5ef4-b491-448f-80ec-f1c070514a81.hwpx",
        },
        "after": {
            "file": "after_2025.hwpx",
            "date": "2025-05-20",
            "number": "중소벤처기업부고시 제2025-53호",
            "page_url": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1059007&cbIdx=127",
            "file_url": "https://www.mss.go.kr/common/board/Download.do?bcIdx=1059007&cbIdx=127&streFileNm=3cc5feb5-8723-42d8-bc1a-acfb0c94d251.hwpx",
        },
    },
    {
        "directory": "mof_rd_regulation_pair",
        "case_id": "mof-rd-regulation-2022__2024",
        "issuer": "해양수산부",
        "series": "해양수산 연구개발사업 운영규정",
        "before": {
            "file": "before_2022.hwpx",
            "date": "2022-12-27",
            "number": "해양수산부훈령 제687호",
            "page_url": "https://www.mof.go.kr/doc/ko/selectDoc.do?bbsSeq=35&docSeq=48445&menuSeq=887",
            "file_url": "https://www.mof.go.kr/jfile/readDownloadFile.do?fileNum=3&fileType=MOF_ARTICLE&fileTypeSeq=48445",
        },
        "after": {
            "file": "after_2024.hwpx",
            "date": "2024-10-20",
            "number": "해양수산부훈령 제772호",
            "page_url": "https://www.mof.go.kr/doc/ko/selectDoc.do?bbsSeq=35&docSeq=58895&menuSeq=888",
            "file_url": "https://www.mof.go.kr/jfile/readDownloadFile.do?fileNum=2&fileType=MOF_ARTICLE&fileTypeSeq=58895",
        },
    },
    # 홀드아웃을 늘리려고 2026-08-18에 받았다. 씨앗이 아니라 **채점용**이므로 받는 즉시
    # `training_data/mutate/documents.py`의 `HOLDOUT_SERIES`에 이 디렉터리 이름을 적는다.
    #
    # **판본을 고를 때 국가연구개발혁신법(2021 시행)을 사이에 두면 안 된다.** 처음에
    # 2020-12-30 -> 2024-12-30으로 잡았더니 유사도가 0.2891이고 실질 변경 470블록 중
    # 상위가 전부 법정 용어 일괄 개정이었다 -- `과제 -> 연구개발과제` 224회,
    # `전담기관 -> 전문기관` 131회, `사업 -> 연구개발` 55회. 채점용 자로 쓰면 홀드아웃의
    # 대부분이 명칭 변경이 된다. 그 판본은 `data/rejected/motie_industrial_tech_2020__2024/`에
    # 남겼다 -- `data/raw_collection/` 안에 두면 `annotate.py`가 같이 세어 버린다.
    #
    # 혁신법 이후끼리인 2022-01-04 -> 2024-12-30은 유사도 0.6562에 실질 변경
    # 159블록/141묶음이고 최다 치환이 18회로 흩어져 있다. 채택된 pair의 유사도 범위
    # (해수부 0.5983 ~ 팁스 공고 0.987) 안이다.
    {
        "directory": "motie_industrial_tech_guideline_pair",
        "case_id": "motie-industrial-tech-guideline-2020__2024",
        "issuer": "산업통상자원부",
        "series": "산업기술혁신사업 공통 운영요령",
        "before": {
            "file": "before_2022.html",
            "date": "2022-01-04",
            "number": "산업통상자원부고시 제2022-4호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000208247",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000208247&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
        "after": {
            "file": "after_2024.html",
            "date": "2024-12-30",
            "number": "산업통상자원부고시 제2024-218호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000251982",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000251982&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
    },
    {
        "directory": "mafra_rd_guideline_pair",
        "case_id": "mafra-rd-guideline-2022__2025",
        "issuer": "농림축산식품부",
        "series": "농림축산식품 연구개발사업 운영규정",
        "before": {
            "file": "before_2022.html",
            "date": "2022-09-28",
            "number": "농림축산식품부훈령 제444호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000214779",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000214779&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
        "after": {
            "file": "after_2025.html",
            "date": "2025-03-10",
            "number": "농림축산식품부훈령 제534호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000256254",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000256254&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
    },
    {
        "directory": "me_environment_tech_guideline_pair",
        "case_id": "me-environment-tech-guideline-2023__2024",
        "issuer": "환경부",
        "series": "환경기술개발사업 운영규정",
        "before": {
            "file": "before_2023.html",
            "date": "2023-12-20",
            "number": "환경부훈령 제1619호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000233040",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000233040&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
        "after": {
            "file": "after_2024.html",
            "date": "2024-12-10",
            "number": "환경부훈령 제1668호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000250596",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000250596&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
    },
    {
        "directory": "mohw_health_rd_guideline_pair",
        "case_id": "mohw-health-rd-guideline-2022__2023",
        "issuer": "보건복지부",
        "series": "보건의료기술 연구개발사업 운영·관리규정",
        "before": {
            "file": "before_2022.html",
            "date": "2022-01-01",
            "number": "보건복지부고시 제2021-335호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000207505",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000207505&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
        "after": {
            "file": "after_2023.html",
            "date": "2023-12-26",
            "number": "보건복지부고시 제2023-275호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000233560",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000233560&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
    },
    {
        "directory": "msit_science_rd_guideline_pair",
        "case_id": "msit-science-rd-guideline-2022__2023",
        "issuer": "과학기술정보통신부",
        "series": "과학기술정보통신부 소관 과학기술분야 연구개발사업 처리규정",
        "before": {
            "file": "before_2022.html",
            "date": "2022-01-14",
            "number": "과학기술정보통신부훈령 제193호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000208408",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000208408&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
        "after": {
            "file": "after_2023.html",
            "date": "2023-08-24",
            "number": "과학기술정보통신부훈령 제242호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000228284",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000228284&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
    },
    {
        "directory": "molit_rd_guideline_pair",
        "case_id": "molit-rd-guideline-2021__2024",
        "issuer": "국토교통부",
        "series": "국토교통부소관 연구개발사업 운영규정",
        "before": {
            "file": "before_2021.html",
            "date": "2021-11-17",
            "number": "국토교통부훈령 제1449호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000206215",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000206215&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
        "after": {
            "file": "after_2024.html",
            "date": "2024-01-22",
            "number": "국토교통부훈령 제1708호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000235502",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000235502&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
    },
    {
        "directory": "mss_modoo_startup_notice_pair",
        "case_id": "mss-modoo-startup-2026-208__2026-275",
        "issuer": "중소벤처기업부",
        "series": "모두의 창업 프로젝트",
        "source_class": "지원사업 공고·정정공고",
        "scope_note": "통합 모집공고 원공고와 수정공고. series는 양쪽 제목이 '모집공고'와 '모집 수정공고'로 갈려 공통으로 들어 있는 사업명만 적는다.",
        "match_evidence": {
            "type": "explicit_prior_notice_citation",
            "before_notice_number": "중소벤처기업부 공고 제2026-208호",
            "after_notice_number": "중소벤처기업부 공고 제2026-275호",
            "citation_in_after": "「모두의 창업 프로젝트」 통합 모집 공고(2026.3.26.)에서 주요 변경된 사항을 안내드립니다.",
            "note": "인용은 첨부 본문이 아니라 수정공고 게시글 본문에 있다. 2026.3.26.은 원공고 제2026-208호의 공고일과 일치한다.",
        },
        "before": {
            "file": "before_2026_208.hwpx",
            "date": "2026-03-26",
            "number": "중소벤처기업부 공고 제2026-208호",
            "page_url": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1066642&cbIdx=310",
            "file_url": "https://www.mss.go.kr/common/board/Download.do?bcIdx=1066642&cbIdx=310&streFileNm=6c8d7b2f-a8e6-4cff-88aa-444bd806afeb.hwpx",
        },
        "after": {
            "file": "after_2026_275.hwpx",
            "date": "2026-04-16",
            "number": "중소벤처기업부 공고 제2026-275호",
            "page_url": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1067363&cbIdx=310",
            "file_url": "https://www.mss.go.kr/common/board/Download.do?bcIdx=1067363&cbIdx=310&streFileNm=f63ff4f4-8345-442d-adcc-046535f91e9a.hwpx",
        },
    },
    {
        "directory": "mss_innovation_voucher_notice_pair",
        "case_id": "mss-innovation-voucher-2026-280__2026-317",
        "issuer": "중소벤처기업부",
        "series": "중소기업 혁신바우처(채용지원)",
        "source_class": "지원사업 공고·정정공고",
        "scope_note": "채용지원 사업 지원계획 원공고와 수정공고. series는 양쪽 제목이 '공고'와 '수정 공고'로 갈려 공통으로 들어 있는 사업명만 적는다.",
        "match_evidence": {
            "type": "same_board_preserved_prior_notice",
            "before_notice_number": "중소벤처기업부 공고 제2026-280호",
            "after_notice_number": "중소벤처기업부 공고 제2026-317호",
            "note": "이 pair는 근거가 위 셋 중 가장 약하다. 수정공고 본문도 게시글도 원공고의 번호나 공고일을 인용하지 않고 '수정 공고합니다'라고만 적는다. 근거는 발행처·연도·사업명이 같고 같은 게시판이 원공고를 별도 게시글로 보존한다는 것뿐이다.",
        },
        "before": {
            "file": "before_2026_280.hwpx",
            "date": "2026-04-20",
            "number": "중소벤처기업부 공고 제2026-280호",
            "page_url": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1067475&cbIdx=310",
            "file_url": "https://www.mss.go.kr/common/board/Download.do?bcIdx=1067475&cbIdx=310&streFileNm=17539c8f-6ce1-4f35-b33e-fb5833488c56.hwpx",
        },
        "after": {
            "file": "after_2026_317.hwpx",
            "date": "2026-05-06",
            "number": "중소벤처기업부 공고 제2026-317호",
            "page_url": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1067991&cbIdx=310",
            "file_url": "https://www.mss.go.kr/common/board/Download.do?bcIdx=1067991&cbIdx=310&streFileNm=7c6903b2-6005-4137-93d5-5d7f8eafe974.hwpx",
        },
    },
    {
        "directory": "ftc_deposit_terms_pair",
        "case_id": "ftc-standard-terms-10012-2022__2024",
        "issuer": "공정거래위원회",
        "series": "예금거래기본약관",
        "source_class": "표준약관",
        "scope_note": "공정거래위원회 표준약관 제10012호 예금거래기본약관의 2022년 개정본과 2024년 개정본.",
        "match_evidence": {
            "type": "same_standard_terms_number",
            "value": "표준약관 제10012호",
            "note": "표준약관 번호는 개정 후에도 유지된다. 두 판본 첫머리에 같은 번호가 그대로 찍혀 있다.",
        },
        "before": {
            "file": "before_2022.hwpx",
            "date": "2022-12-23",
            "number": "표준약관 제10012호 (2022. 12. 23. 개정)",
            "page_url": "https://www.ftc.go.kr/www/selectBbsNttView.do?bordCd=201&key=202&nttSn=11192",
            "file_url": "https://www.ftc.go.kr/www/downloadBbsFile.do?atchmnflNo=14856",
        },
        "after": {
            "file": "after_2024.hwpx",
            "date": "2024-09-27",
            "number": "표준약관 제10012호 (2024. 9. 27. 개정)",
            "page_url": "https://www.ftc.go.kr/www/selectBbsNttView.do?bordCd=201&key=202&nttSn=11202",
            "file_url": "https://www.ftc.go.kr/www/downloadBbsFile.do?atchmnflNo=14866",
        },
    },
    {
        "directory": "ftc_gift_certificate_terms_2024_2025_pair",
        "case_id": "ftc-standard-terms-10073-2024__2025",
        "issuer": "공정거래위원회",
        "series": "신유형 상품권 표준약관",
        "source_class": "표준약관",
        "scope_note": "표준약관 제10073호의 2024년 개정본과 2025년 개정본. `ftc_gift_certificate_terms`(2020->2024)와 같은 계열의 두 번째 쌍이고, 그 폴더의 2024년판이 이 쌍의 before와 같은 문서다. 한 계열 세 쌍 한도 중 두 쌍째다.",
        "match_evidence": {
            "type": "same_standard_terms_number",
            "value": "표준약관 제10073호",
            "note": "표준약관 번호는 개정 후에도 유지된다. 두 판본 첫머리에 같은 번호가 그대로 찍혀 있다.",
        },
        "before": {
            "file": "before_2024.hwpx",
            "date": "2024-09-27",
            "number": "표준약관 제10073호 (2024. 9. 27. 개정)",
            "page_url": "https://www.ftc.go.kr/www/selectBbsNttView.do?bordCd=201&key=202&nttSn=11199",
            "file_url": "https://www.ftc.go.kr/www/downloadBbsFile.do?atchmnflNo=14863",
        },
        "after": {
            "file": "after_2025.hwpx",
            "date": "2025-09-11",
            "number": "표준약관 제10073호 (2025. 9. 11. 개정)",
            "page_url": "https://www.ftc.go.kr/www/selectBbsNttView.do?bordCd=201&key=202&nttSn=46431",
            "file_url": "https://www.ftc.go.kr/www/downloadBbsFile.do?atchmnflNo=51574",
        },
    },
    {
        "directory": "moe_school_enterprise_notice_pair",
        "case_id": "moe-school-enterprise-2025-199__2025-231",
        "issuer": "교육부",
        "series": "2025년도 4단계 학교기업 지원사업",
        "source_class": "지원사업 공고·정정공고",
        "scope_note": "학교기업 지원사업 수정공고와 접수기간 연장공고. 같은 공식 게시판이 두 판본을 별도 게시물로 보존한다.",
        "match_evidence": {
            "type": "same_board_preserved_prior_notice",
            "before_notice_number": "교육부 공고 제2025-199호",
            "after_notice_number": "교육부 공고 제2025-231호",
            "citation_in_after": "기존 공고 시 제출한 학교기업도 연장된 공고기간까지 수정 제출 가능",
            "note": "연장공고가 기존 제출분을 직접 언급하고, 한국산업기술진흥원 사업공고 게시판이 제2025-199호와 제2025-231호를 각각 보존한다.",
        },
        "before": {
            "file": "before_2025_199.hwpx",
            "date": "2025-05-14",
            "number": "교육부 공고 제2025-199호",
            "page_url": "https://www.kiat.or.kr/front/board/boardContentsView.do?board_id=90&contents_id=67fcf729004a4ede898908c8dcd21cc7",
            "file_url": "https://www.kiat.or.kr/commonfile/fileidDownLoad.do?file_id=3A4536C9FDB642F9A4879168B59FB49B",
        },
        "after": {
            "file": "after_2025_231.hwpx",
            "date": "2025-06-17",
            "number": "교육부 공고 제2025-231호",
            "page_url": "https://www.kiat.or.kr/front/board/boardContentsView.do?board_id=90&contents_id=7a688123a8f046cb9990c0d6551ec1a7",
            "file_url": "https://www.kiat.or.kr/commonfile/fileidDownLoad.do?file_id=C3E9A0BB397C442189DA77F551ED79F8",
        },
    },
    {
        "directory": "motie_global_talent_notice_pair",
        "case_id": "motie-global-talent-2026-037__2026-269",
        "issuer": "산업통상부",
        "series": "산업혁신인재성장지원(해외연계)-최고급 해외인재유치 지원사업",
        "source_class": "지원사업 공고·정정공고",
        "scope_note": "최고급 해외인재유치 지원사업 시행계획 원공고와 수정공고. 접수기간·지원규모·인건비 조건이 수정됐다.",
        "match_evidence": {
            "type": "same_board_preserved_prior_notice",
            "before_notice_number": "산업통상부 공고 제2026-037호",
            "after_notice_number": "산업통상부 공고 제2026-269호",
            "citation_in_after": "최초 공고 시작일(2026.01.19.) 이전에 신청 기관에서 이미 채용한 자는 신청 불가",
            "note": "수정공고가 원공고 시작일을 직접 보존하고, 한국산업기술진흥원 사업공고 게시판이 두 공고를 각각 보존한다.",
        },
        "before": {
            "file": "before_2026_037.hwpx",
            "date": "2026-01-19",
            "number": "산업통상부 공고 제2026-037호",
            "page_url": "https://www.kiat.or.kr/front/board/boardContentsView.do?board_id=90&contents_id=544455b4974a4dccb8b41b8ef85acca4",
            "file_url": "https://www.kiat.or.kr/commonfile/fileidDownLoad.do?file_id=741A1EECAD6149C7B9B9FE21835FBBF5",
        },
        "after": {
            "file": "after_2026_269.hwpx",
            "date": "2026-04-06",
            "number": "산업통상부 공고 제2026-269호",
            "page_url": "https://www.kiat.or.kr/front/board/boardContentsView.do?board_id=90&contents_id=21ce3c08e30c491bb6b9abb7e4176e48",
            "file_url": "https://www.kiat.or.kr/commonfile/fileidDownLoad.do?file_id=5F0E69ADCEF34199B36D2514EC85DA75",
        },
    },
    {
        "directory": "motie_foreign_students_notice_pair",
        "case_id": "motie-foreign-students-2026-022__2026-138",
        "issuer": "산업통상부",
        "series": "우수 외국인 유학생 지역산업 연계지원 사업",
        "source_class": "지원사업 공고·정정공고",
        "scope_note": "우수 외국인 유학생 지역산업 연계지원 사업 시행계획 원공고와 접수기간 연장공고.",
        "match_evidence": {
            "type": "explicit_prior_notice_citation",
            "before_notice_number": "산업통상부 공고 제2026-022호",
            "after_notice_number": "산업통상부 공고 제2026-138호",
            "citation_in_after": "본 공고는 기 공고된 공고번호 제2026-022호의 연장 공고로써, 최초 공고일(’26.1.12) 이후 접수된 모든 신청서류를 통합하여 심의할 예정임을 알려드리오니 참고하시기 바랍니다.",
        },
        "before": {
            "file": "before_2026_022.hwpx",
            "date": "2026-01-12",
            "number": "산업통상부 공고 제2026-022호",
            "page_url": "https://www.kiat.or.kr/front/board/boardContentsView.do?board_id=90&contents_id=dbbba98d94c948df9a52b0113c988c77",
            "file_url": "https://www.kiat.or.kr/commonfile/fileidDownLoad.do?file_id=93D3A31EFCA34B919CC587DDB02D9CAC",
        },
        "after": {
            "file": "after_2026_138.hwpx",
            "date": "2026-02-20",
            "number": "산업통상부 공고 제2026-138호",
            "page_url": "https://www.kiat.or.kr/front/board/boardContentsView.do?board_id=90&contents_id=65dcb5e23e364bd3b20cab7bcab9946a",
            "file_url": "https://www.kiat.or.kr/commonfile/fileidDownLoad.do?file_id=7542FB6E8832475498DEB61505A242A6",
        },
    },
    {
        "directory": "kisa_blockchain_university_notice_pair",
        "case_id": "kisa-blockchain-university-2026-0124__2026-0185",
        "issuer": "과학기술정보통신부·한국인터넷진흥원",
        "series": "2026년 블록체인 특성화 대학(원) 지원사업 모집 공고",
        "source_class": "지원사업 공고·정정공고",
        "scope_note": "블록체인 특성화 대학(원) 지원사업 원공고와 정정공고. 접수기한과 지방자치단체 매칭 조건이 수정됐다.",
        "match_evidence": {
            "type": "same_board_preserved_prior_notice",
            "before_notice_number": "과학기술정보통신부 공고 제2026-0124호",
            "after_notice_number": "과학기술정보통신부 공고 제2026-0185호",
            "citation_in_after": "(정정공고)2026년 블록체인 특성화 대학(원) 지원사업 모집 공고",
            "note": "한국인터넷진흥원 공식 게시판이 원공고와 정정공고를 각각 보존하고, 정정공고 게시물에 전후 비교표를 함께 제공한다.",
        },
        "before": {
            "file": "before_2026_0124.hwpx",
            "date": "2026-02-06",
            "number": "과학기술정보통신부 공고 제2026-0124호",
            "page_url": "https://www.kisa.or.kr/403/form?postSeq=10455",
            "file_url": "https://www.kisa.or.kr/post/fileDownload?menuSeq=403&postSeq=10455&attachSeq=1&lang_type=KO",
        },
        "after": {
            "file": "after_2026_0185.hwpx",
            "date": "2026-02-20",
            "number": "과학기술정보통신부 공고 제2026-0185호",
            "page_url": "https://www.kisa.or.kr/403/form?postSeq=10467",
            "file_url": "https://www.kisa.or.kr/post/fileDownload?menuSeq=403&postSeq=10467&attachSeq=1&lang_type=KO",
        },
    },
    {
        "directory": "kisa_public_blockchain_notice_pair",
        "case_id": "kisa-public-blockchain-2025-0488__2025-0556",
        "issuer": "과학기술정보통신부·한국인터넷진흥원",
        "series": "2025년 블록체인 공공분야 집중사업 사업자 모집 공고",
        "source_class": "지원사업 공고·정정공고",
        "scope_note": "블록체인 공공분야 집중사업 원공고와 정정공고. 접수기한과 기술적 요구사항이 수정됐다.",
        "match_evidence": {
            "type": "explicit_prior_notice_citation",
            "before_notice_number": "과학기술정보통신부 공고 제2025-0488호",
            "after_notice_number": "과학기술정보통신부 공고 제2025-0556호",
            "citation_in_after": "2025년 4월 30일자에 게재된 과학기술정보통신부공고 제2025-0488호 「2025년 블록체인 공공분야 집중사업 사업자 모집 공고」 건을 아래와 같이 정정공고하오니, 수정된 공고 및 제안요청서 등을 반드시 확인하시어 참여하시기 바랍니다.",
        },
        "before": {
            "file": "before_2025_0488.hwpx",
            "date": "2025-04-30",
            "number": "과학기술정보통신부 공고 제2025-0488호",
            "page_url": "https://www.kisa.or.kr/403/form?postSeq=10134",
            "file_url": "https://www.kisa.or.kr/post/fileDownload?menuSeq=403&postSeq=10134&attachSeq=1&lang_type=KO",
        },
        "after": {
            "file": "after_2025_0556.hwpx",
            "date": "2025-05-21",
            "number": "과학기술정보통신부 공고 제2025-0556호",
            "page_url": "https://www.kisa.or.kr/403/form?postSeq=10164",
            "file_url": "https://www.kisa.or.kr/post/fileDownload?menuSeq=403&postSeq=10164&attachSeq=1&lang_type=KO",
        },
    },
]


def download(url: str, path: Path) -> tuple[str, int]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
        content_type = response.headers.get_content_type()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return content_type, len(payload)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(path: Path) -> tuple[list[str], Path]:
    sys.path.insert(0, str(REPO / "source_data"))
    from extract import blocks

    extracted = blocks(path)
    text_path = path.with_suffix(".txt")
    text_path.write_text("\n".join(extracted) + "\n", encoding="utf-8")
    return extracted, text_path


def collect_pair(pair: dict) -> None:
    directory = RAW / pair["directory"]
    sources = {}
    paths = {}
    for side in ("before", "after"):
        spec = pair[side]
        path = directory / spec["file"]
        if path.suffix.lower() in (".pdf", ".hwp"):
            raise RuntimeError(
                f"{path.name}: PDF와 구형 HWP는 문단 단위로 자를 수 없고 추출 경로도 없다. "
                f"HWPX나 HTML 판본을 쓴다")
        url = spec.get("file_url", spec["page_url"])
        content_type, byte_size = download(url, path)
        if path.read_bytes()[:4] == b"%PDF":
            raise RuntimeError(
                f"{path.name}: {path.suffix}로 적었는데 실제로 온 것은 PDF다. "
                f"주소가 가리키는 첨부를 다시 본다")
        if path.suffix == ".hwpx" and not zipfile.is_zipfile(path):
            raise RuntimeError(f"{path.name}: HWPX ZIP signature missing")
        blocks, text_path = extract(path)
        joined = "".join(blocks)
        if pair["series"].replace(" ", "") not in joined.replace(" ", ""):
            raise RuntimeError(f"{path.name}: document title missing from extracted text")
        # 하한이 5,000자였는데 이미 채택한 공정위 표준약관 2020년판이 4,868자라 스스로
        # 걸렸다. `check_candidate.py`의 MIN_CHARACTERS와 같은 값으로 맞춘다.
        if len(joined) < 2_000:
            raise RuntimeError(f"{path.name}: extracted body is too short ({len(joined)} characters)")
        paths[side] = path
        sources[side] = {
            "document_title": pair["series"],
            "effective_date": spec["date"],
            "authority_number": spec["number"],
            "page_url": spec["page_url"],
            "file_url": url,
            "local_file": path.name,
            "mime": content_type,
            "byte_size": byte_size,
            "sha256": digest(path),
            "extracted_text_file": text_path.name,
            "extracted_blocks": len(blocks),
            "extracted_text_characters": len(joined),
        }

    output = directory / f"{paths['before'].stem}__{paths['after'].stem}.classify.json"
    subprocess.run(
        [sys.executable, str(CLASSIFIER), str(paths["before"]), str(paths["after"]), "--json", str(output), "--show", "0"],
        check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    comparison = json.loads(output.read_text(encoding="utf-8"))
    manifest = {
        "case_id": pair["case_id"],
        "source_class": pair.get("source_class", "기관 운영지침·사업시행지침"),
        "collected_at": datetime.now().astimezone().isoformat(),
        "issuer": pair["issuer"],
        "document_series": pair["series"],
        "match_evidence": pair.get("match_evidence", {
            "type": "official_administrative_rule_history",
            "note": "국가법령정보센터의 동일 제명 연혁과 각 판본의 일부개정 발령번호로 연결한다.",
        }),
        "sources": sources,
        "comparison": {
            "classifier_file": output.name,
            "similarity": comparison["similarity"],
            "changed_regions": comparison["regions"],
            "no_real_change_blocks": comparison["no_real_change"]["blocks"],
            "added_blocks": len(comparison["added"]),
            "deleted_blocks": len(comparison["deleted"]),
            "real_change_blocks": comparison["real_change"]["blocks"],
            "real_change_groups": comparison["real_change"]["groups"],
        },
        "acceptance": "accepted_meaningful_change",
        "scope_note": pair.get(
            "scope_note", "수정 명세에 따라 사업 운영지침 성격의 행정규칙을 포함한다."),
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    selected = set(sys.argv[1:])
    for pair in PAIRS:
        if not selected or pair["directory"] in selected:
            collect_pair(pair)


if __name__ == "__main__":
    main()
