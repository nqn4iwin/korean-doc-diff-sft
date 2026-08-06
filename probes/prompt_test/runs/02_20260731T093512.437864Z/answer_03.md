{
  "case_id": "R26BD00244326_R26BK01607991-001",
  "project_summary": "한국마케팅진흥원이 발주하는 2026년 소상공인 상생협업교육 장비 임차 및 AI 실습지원 용역으로, 5개 지역 7개 교육장에서 29개 기수 약 1,150명을 대상으로 노트북 임차, 라우터 구성, AI Tool 계정 구매 및 운영을 수행하는 사업이다.",
  "changes": [
    {
      "change_id": "C01",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0062", "prior_spec-B0068"],
      "bid_block_ids": ["bid_notice-B0062", "bid_notice-B0068"],
      "before": "7/9(목)",
      "after": "일정 8월 이후로 변경 예정",
      "changed_span": {
        "before": "7/9(목)",
        "after": "일정 8월 이후로 변경 예정"
      },
      "direct_impact": "1기 및 2기 교육 일정이 7월 9일에서 8월 이후로 변경되어 제안사는 해당 일정의 장비 임차 및 배송 계획을 8월 이후로 조정해야 하며, 일정 변경 가능성을 고려한 유연한 운영 계획을 제안서에 반영해야 한다.",
      "confidence": "high"
    },
    {
      "change_id": "C02",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0225", "prior_spec-B0231"],
      "bid_block_ids": ["bid_notice-B0225", "bid_notice-B0231"],
      "before": "7/7·7/14·7/21·8/18 (화)",
      "after": "7/14·7/21·8/18 (화)",
      "changed_span": {
        "before": "7/7·7/14·7/21·8/18 (화)",
        "after": "7/14·7/21·8/18 (화)"
      },
      "direct_impact": "뷰티/패션 1기 교육 일정에서 7/7 일정이 삭제되고 8월 일정 1회 추가 예정이 명시되어, 제안사는 3회차 운영 계획을 수립하고 추가 일정에 대한 대응 방안을 마련해야 한다.",
      "confidence": "high"
    },
    {
      "change_id": "C03",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0230"],
      "bid_block_ids": ["bid_notice-B0231"],
      "before": "7/8·7/15·7/22·8/19 (수)",
      "after": "7/15·7/22·8/19 (수)",
      "changed_span": {
        "before": "7/8·7/15·7/22·8/19 (수)",
        "after": "7/15·7/22·8/19 (수)"
      },
      "direct_impact": "식품 2기 교육 일정에서 7/8 일정이 삭제되고 8월 일정 1회 추가 예정이 명시되어, 제안사는 3회차 운영 계획을 수립하고 추가 일정에 대한 대응 방안을 마련해야 한다.",
      "confidence": "high"
    }
  ],
  "issuer_intent": [
    {
      "claim": "발주자는 교육 일정을 7월에서 8월 이후로 조정하여 여름 휴가 시즌 및 내부 사정을 고려한 일정 변경을 반영하고자 한다.",
      "basis_change_ids": ["C01"],
      "support_level": "supported",
      "reason": "사전규격의 1기, 2기 일정이 7/9(목)이었으나 입찰공고에서 '일정 8월 이후로 변경 예정'으로 명시되어 있어, 발주자가 교육 시작 시점을 8월 이후로 조정하려는 의도가 명확하다."
    },
    {
      "claim": "발주자는 교육일정②의 뷰티/패션 및 식품 과정에서 7월 초 일정을 삭제하고 8월에 추가 일정을 편성하여 교육 운영의 유연성을 확보하고자 한다.",
      "basis_change_ids": ["C02", "C03"],
      "support_level": "supported",
      "reason": "사전규격의 4회차 일정 중 7/7, 7/8이 삭제되고 '8월 일정 1회 추가 예정'이 명시되어 있어, 발주자가 초기 일정을 조정하고 추가 일정을 통해 교육 기회를 확대하려는 의도가 확인된다."
    }
  ],
  "uncertainties": [
    {
      "question": "교육일정① 1기, 2기의 정확한 8월 이후 일정이 언제인지, 그리고 교육일정②의 8월 추가 일정이 구체적으로 언제인지 문서만으로는 확인할 수 없다.",
      "why_it_matters": "제안사는 장비 임차, 배송, 설치, 회수 계획을 수립하기 위해 정확한 교육 일정을 알아야 하나, 현재 문서에서는 '8월 이후로 변경 예정' 및 '8월 일정 1회 추가 예정'으로만 표기되어 있어 구체적인 일정 확정 전까지는 운영 계획 수립에 불확실성이 존재한다."
    },
    {
      "question": "교육일정②의 뷰티/패션 1기 및 식품 2기에서 삭제된 7/7, 7/8 일정이 완전히 취소된 것인지, 아니면 8월 추가 일정으로 대체된 것인지 명확하지 않다.",
      "why_it_matters": "삭제된 일정이 완전히 취소된 경우 총 교육 횟수가 4회에서 3회로 감소할 수 있으나, 8월 추가 일정이 편성되면 4회를 유지할 수 있다. 이는 노트북 임차 수량, 배송 횟수, AI Tool 계정 운영 등 과업 범위와 비용에 직접적인 영향을 미치므로 명확한 확인이 필요하다."
    }
  ]
}
