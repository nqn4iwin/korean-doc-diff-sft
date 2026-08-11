"""개정문이 문서에 실릴 수 있는 문장인지 기계로 본다. BM7.

파일 이름이 `inspect.py`가 아닌 이유는 스크립트 폴더가 sys.path 맨 앞에 오기 때문이다.
그 이름이면 표준 라이브러리 `inspect`를 가리고, argparse가 내부에서 그것을 쓰다가 터진다.

BM1~BM5는 형식과 라벨만 본다 -- JSON인가, 서식 차이만은 아닌가, 분류 어휘가 샜는가, 변경
폭이 작은가, 셜록이 같은 라벨을 짚는가. **문장이 말이 되는지, 원문에 없는 것을 지어냈는지
보는 자리가 하나도 없다.** 첫 실행에서 게이트 다섯 개를 모두 통과한 10건 중 셋이 비문
이거나 지어낸 것이었고, 셜록은 셋 다 지시한 라벨로 정확히 판정했다.

**이 검사를 Solar에게 시키면 안 된다.** 모리아티가 지어낸 `5급 이상 공무원`을 셜록이
사실로 읽었다 -- 같은 모델은 같은 오류를 낸다(`docs/기획서_최종.md` 5.2절 "역할 A·B의
오류 상관"). 그래서 규칙으로 짰다.

규칙 넷은 실패 사례에서 거꾸로 뽑았다. 셋이 서로 다른 징후를 냈기 때문이다.

  C1  주체를 접속해 놓고 주격·주제 조사로 닫지 않았다   -> 비문
  C2  새로 세운 주체가 문서 어디에도 없다              -> 지어냄
  C3  새 수치가 문서 어디에도 없다                    -> 지어냄
  C4  다른 조항을 받는 조항에서 주체를 통째로 갈았다      -> 참조가 깨진다

**하드 게이트가 아니라 표시다.** 사람이 판정한 표본이 10건뿐이라 문턱을 세울 근거가 없다.
걸린 것은 버리지 말고 사람 검수로 보낸다. `docs/기획서_최종.md` 2.3절이 200건마다 10건을
요구하는데, 그 10건을 무작위로 뽑는 대신 여기 걸린 것부터 읽으면 같은 품으로 더 많이
잡는다.
"""
from __future__ import annotations

import re

# 주격·주제 조사. 뒤에 공백이나 쉼표가 와야 조사다 -- `기관은행`의 `은`을 거르기 위해서다.
JOSA = re.compile(r'(?:은|는|이|가)(?=[\s,])')
CONJ = re.compile(r'\s(?:및|과|와)\s')
# 문서가 주체를 부르는 방식. 코퍼스에 실제로 나오는 꼬리만 넣었다.
ACTOR = re.compile(r'[가-힣]{2,14}(?:의 장|기관|담당관|위원회|장관|공무원|연구자'
                   r'|연구책임자|평가단|위원|부서)')
NUM = re.compile(r'\d+\s*(?:급|호봉|퍼센트|%|일|개월|년|명|개|배|등급|호)')
XREF = re.compile(r'제\s*\d+\s*(?:항|조|호)(?:에 따라|에 따른|의)')
SUBJ = re.compile(r'([가-힣]{2,15})(?:은|는|이|가)(?=[\s,])')

# `수치·기준`과 `기한·시점`은 새 값을 넣으라는 지시다. 문서에 없는 값이 나오는 것이
# 정상이므로 C3를 걸지 않는다. 이것을 안 빼면 정당한 개정을 지어냄으로 잡는다.
VALUE_TARGETS = {"수치·기준", "기한·시점"}


def inspect(clause: str, after: str, target: str, document: str) -> list[str]:
    """개정문에서 의심스러운 곳을 찾는다. 빈 목록이면 걸린 것이 없다는 뜻이다."""
    found: list[str] = []

    # C1 -- `A 및 B` 꼴로 주체를 늘려 놓고 주격·주제 조사로 닫지 않으면 주어가 성립하지
    # 않는다. `사업담당관 및 자체 연구개발과제의 …`가 그 사례다. 주체를 늘리라는 지시일
    # 때만 본다. `제출물·기재사항`에서는 목적어를 접속하므로 `…자료를`로 닫는 것이 맞다.
    if target == "수행 주체" and CONJ.search(clause) is None:
        for match in CONJ.finditer(after):
            if not JOSA.search(after[match.end():match.end() + 35]):
                head = after[max(0, match.start() - 12):match.end() + 22]
                found.append(f"C1 접속 뒤 주격조사 없음: …{head}…")
                break

    # C2 -- 조항에 없던 주체가 문서 전체에도 없으면 지어낸 것이다. 조항만 보면 안 된다.
    # 다른 조항에서 데려온 진짜 기관명까지 걸리기 때문이다.
    for word in sorted(set(ACTOR.findall(after)) - set(ACTOR.findall(clause))):
        if word not in document:
            found.append(f"C2 문서에 없는 주체: {word}")

    # C3 -- 같은 논리를 수치에 적용한다. 값을 바꾸라는 지시일 때는 건너뛴다.
    if target not in VALUE_TARGETS:
        for word in sorted(set(NUM.findall(after)) - set(NUM.findall(clause))):
            if re.sub(r"\s", "", word) not in re.sub(r"\s", "", document):
                found.append(f"C3 문서에 없는 수치: {word}")

    # C4 -- `제1항에 따라 사업담당관이 …`처럼 다른 조항을 받는 조항에서 그 주체를 갈면,
    # 문장 자체는 멀쩡해도 앞 조항과 어긋난다. 읽는 사람도 놓치기 쉬운 형태다.
    if XREF.search(clause):
        missing = [s for s in SUBJ.findall(clause) if s not in after]
        if missing:
            found.append(f"C4 참조 조항인데 주체가 사라짐: {missing}")
    return found
