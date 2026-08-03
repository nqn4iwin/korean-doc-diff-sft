{
  "case_id": "R26BD00244326_R26BK01607991-001",
  "project_summary": "한국마케팅진흥원이 2026년 소상공인 상생협업교육을 위해 5개 지역 7개 교육장에 노트북 및 라우터 임차, AI Tool 계정 구매·운영을 지원하는 용역이다. 총 29개 기수, 약 1,150명 교육생을 대상으로 하며 사업예산은 97,020,000원이다.",
  "changes": [
    {
      "change_id": "C01",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0062", "prior_spec-B0063"],
      "bid_block_ids": ["bid_notice-B0062", "bid_notice-B0063"],
      "before": "7/9(목)",
      "after": "일정 8월 이후로 변경 예정",
      "changed_span": {
        "before": "7/9(목)",
        "after": "일정 8월 이후로 변경 예정"
      },
      "direct_impact": "1기 및 2기 교육 일정이 7월에서 8월 이후로 변경되어 해당 회차 장비 납품·회수 일정 및 물류 계획 조정이 필요함.",
      "confidence": "high"
    },
    {
      "change_id": "C02",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0225"],
      "bid_block_ids": ["bid_notice-B0225"],
      "before": "7/7·7/14·7/21·8/18 (화)",
      "after": "7/14·7/21·8/18 (화)",
      "changed_span": {
        "before": "7/7·7/14·7/21·8/18 (화)",
        "after": "7/14·7/21·8/18 (화)"
      },
      "direct_impact": "교육일정② 1기 1회차 일정이 7/7에서 삭제되어 해당 회차 장비 배송·설치 일정 조정이 필요함.",
      "confidence": "high"
    },
    {
      "change_id": "C03",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0226"],
      "bid_block_ids": ["bid_notice-B0226"],
      "before": "서울 드림스퀘어(서울 마포구)",
      "after": "※ 8월 일정 1회 추가 예정",
      "changed_span": {
        "before": "서울 드림스퀘어(서울 마포구)",
        "after": "※ 8월 일정 1회 추가 예정"
      },
      "direct_impact": "1기 교육장 정보가 삭제되고 8월 일정 추가 예정 주석이 삽입되어, 제안사는 8월 추가 일정에 대한 장비 및 인력 대응 계획을 수립해야 함.",
      "confidence": "high"
    },
    {
      "change_id": "C04",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0231"],
      "bid_block_ids": ["bid_notice-B0231"],
      "before": "7/8·7/15·7/22·8/19 (수)",
      "after": "7/15·7/22·8/19 (수)",
      "changed_span": {
        "before": "7/8·7/15·7/22·8/19 (수)",
        "after": "7/15·7/22·8/19 (수)"
      },
      "direct_impact": "교육일정② 2기 1회차 일정이 7/8에서 삭제되어 해당 회차 장비 배송·설치 일정 조정이 필요함.",
      "confidence": "high"
    },
    {
      "change_id": "C05",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0232"],
      "bid_block_ids": ["bid_notice-B0232"],
      "before": "서울 드림스퀘어(서울 마포구)",
      "after": "※ 8월 일정 1회 추가 예정",
      "changed_span": {
        "before": "서울 드림스퀘어(서울 마포구)",
        "after": "※ 8월 일정 1회 추가 예정"
      },
      "direct_impact": "2기 교육장 정보가 삭제되고 8월 일정 추가 예정 주석이 삽입되어, 제안사는 8월 추가 일정에 대한 장비 및 인력 대응 계획을 수립해야 함.",
      "confidence": "high"
    }
  ],
  "issuer_intent": [
    {
      "claim": "발주자는 1기 및 2기 교육 일정을 7월에서 8월 이후로 연기하고, 교육일정②의 1회차를 삭제하여 8월에 추가 일정을 편성하려는 의도를 가짐.",
      "basis_change_ids": ["C01", "C02", "C03", "C04", "C05"],
      "support_level": "supported",
      "reason": "사전규격의 구체적 날짜(7/9, 7/7, 7/8)가 입찰공고에서 '8월 이후로 변경 예정' 또는 날짜 삭제로 대체되었으며, 교육장 정보 대신 '8월 일정 1회 추가 예정' 주석이 삽입되어 일정 조정 및 추가 편성 의도가 명확히 드러남."
    }
  ],
  "uncertainties": [
    {
      "question": "8월에 추가될 일정의 구체적 날짜, 교육장, 인원 수는 언제 확정되는가?",
      "why_it_matters": "장비 임차 수량, 배송·회수 일정, AI 계정 운영 계획 등 제안서의 핵심 물류 및 운영 계획 수립에 직접적인 영향을 미치므로, 확정 시점 및 기준에 대한 정보가 없으면 제안사의 대응 계획 수립이 어려움."
    },
    {
      "question": "1기 및 2기의 7월 일정이 완전히 취소되는 것인지, 아니면 8월로 단순 이동하는 것인지?",
      "why_it_matters": "일정 이동 시 기존 7월 장비의 타 지역 활용 가능 여부가 달라지며, 취소 시 해당 회차 예산 및 운영 계획 조정이 필요할 수 있음."
    }
  ]
}
