{
  "case_id": "R26BD00244326_R26BK01607991-001",
  "project_summary": "한국마케팅진흥원이 5개 지역(서울, 경기, 대전, 부산, 제주)에서 진행하는 소상공인 상생협업 교육을 위해 노트북 임차, 라우터 구성, AI Tool 계정 구매 및 운영을 지원하는 용역이다.",
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
      "direct_impact": "서울 1기, 2기 교육 일정이 7월 9일에서 8월 이후로 변경되어 해당 기간의 장비 임차 및 인력 배치 계획 수정이 필요함.",
      "confidence": "high"
    },
    {
      "change_id": "C02",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0225", "prior_spec-B0226"],
      "bid_block_ids": ["bid_notice-B0225", "bid_notice-B0226"],
      "before": "7/7·7/14·7/21·8/18 (화)",
      "after": "7/14·7/21·8/18 (화) ※ 8월 일정 1회 추가 예정",
      "changed_span": {
        "before": "7/7·7/14·7/21·8/18 (화)",
        "after": "7/14·7/21·8/18 (화) ※ 8월 일정 1회 추가 예정"
      },
      "direct_impact": "뷰티/패션 1기 교육 일정에서 7/7 일정이 삭제되고 8월 일정 1회 추가가 예고되어 총 4회차 운영 계획은 유지되나 구체적인 날짜 조정이 필요함.",
      "confidence": "high"
    },
    {
      "change_id": "C03",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0230", "prior_spec-B0231"],
      "bid_block_ids": ["bid_notice-B0230", "bid_notice-B0231"],
      "before": "7/8·7/15·7/22·8/19 (수)",
      "after": "7/15·7/22·8/19 (수) ※ 8월 일정 1회 추가 예정",
      "changed_span": {
        "before": "7/8·7/15·7/22·8/19 (수)",
        "after": "7/15·7/22·8/19 (수) ※ 8월 일정 1회 추가 예정"
      },
      "direct_impact": "식품 2기 교육 일정에서 7/8 일정이 삭제되고 8월 일정 1회 추가가 예고되어 총 4회차 운영 계획은 유지되나 구체적인 날짜 조정이 필요함.",
      "confidence": "high"
    }
  ],
  "issuer_intent": [
    {
      "claim": "발주자는 상반기(7월) 교육 일정을 하반기로 미루고, 8월 일정을 추가하여 교육 운영 시기를 조정하려 한다.",
      "basis_change_ids": ["C01", "C02", "C03"],
      "support_level": "supported",
      "reason": "사전규격의 7월 초 일정이 입찰공고에서 '8월 이후로 변경 예정' 또는 '8월 일정 1회 추가 예정'으로 명시되어, 교육 운영 시기를 하반기로 집중하려는 의도가 확인됨."
    }
  ],
  "uncertainties": [
    {
      "question": "8월에 추가될 1회 일정의 정확한 날짜와 교육장소는 무엇인가?",
      "why_it_matters": "장비 임차 수량 및 배송 일정, 인력 배치 계획을 구체적으로 수립하기 위해 필요함."
    },
    {
      "question": "서울 1기, 2기의 최종 교육 일정은 언제 확정되는가?",
      "why_it_matters": "해당 기수의 장비 임차 및 회수 일정을 확정하여 물류 운영 계획을 수립해야 함."
    }
  ]
}
