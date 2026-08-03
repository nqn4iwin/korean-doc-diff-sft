{
  "case_id": "R26BD00244326_R26BK01607991-001",
  "project_summary": "한국마케팅진흥원이 2026년 소상공인 상생협업교육을 위해 5개 지역 7개 교육장에서 노트북 임차, 라우터 구성, AI Tool 계정 구매 및 운영을 지원하는 용역이다. 총 29개 기수, 약 1,150명 교육 인원을 대상으로 하며, 제한경쟁입찰 및 협상에 의한 계약으로 진행된다.",
  "changes": [
    {
      "change_id": "C01",
      "mapping": "1:1",
      "diff_types": ["lexical", "semantic"],
      "semantic_labels": ["deadline_changed"],
      "prior_block_ids": ["prior_spec-B00369"],
      "bid_block_ids": ["bid_notice-B00371"],
      "before": "ㅇ 입찰마감일시: 2026. 07. 02.(목) 11:00까지, 나라장터 * 마감일시는 나라장터 입찰공고에 명시된 일시 ㅇ 서류 제출: 2026. 07. 02.(목) 18:00까지, 우편접수 * 방문 접수 불가, 제출 시점까지 미접수된 경우 미제출 처리",
      "after": "ㅇ 입찰마감일시: 2026. 07. 10.(금) 14:00까지, 나라장터 * 마감일시는 나라장터 입찰공고에 명시된 일시 ㅇ 서류 제출: 2026. 07. 10.(금) 18:00까지, 우편접수 * 방문 접수 불가, 제출 시점까지 미접수된 경우 미제출 처리",
      "changed_span": {
        "before": "2026. 07. 02.(목) 11:00까지",
        "after": "2026. 07. 10.(금) 14:00까지"
      },
      "direct_impact": "입찰 참가자의 제안서 준비 및 제출 기한이 8일 연장되어 일정 여유가 생겼으나, 서류 제출 마감일도 동일하게 연장되어 전체 입찰 일정이 조정됨.",
      "confidence": "high"
    },
    {
      "change_id": "C02",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["wording_only"],
      "prior_block_ids": ["prior_spec-B0062", "prior_spec-B0063"],
      "bid_block_ids": ["bid_notice-B0062", "bid_notice-B0063"],
      "before": "7/9(목)",
      "after": "일정 8월 이후로 변경 예정",
      "changed_span": {
        "before": "7/9(목)",
        "after": "일정 8월 이후로 변경 예정"
      },
      "direct_impact": "1기 및 2기 교육의 구체적인 날짜가 삭제되고 8월 이후로 변경 예정이라는 안내로 대체되어, 해당 회차의 정확한 일정 파악이 불가능해짐.",
      "confidence": "high"
    },
    {
      "change_id": "C03",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0225"],
      "bid_block_ids": ["bid_notice-B0225", "bid_notice-B0226"],
      "before": "7/7·7/14·7/21·8/18 (화)",
      "after": "7/14·7/21·8/18 (화) ※ 8월 일정 1회 추가 예정",
      "changed_span": {
        "before": "7/7·7/14·7/21·8/18 (화)",
        "after": "7/14·7/21·8/18 (화) ※ 8월 일정 1회 추가 예정"
      },
      "direct_impact": "1기 교육의 첫 번째 회차(7/7)가 삭제되고, 8월에 1회 일정이 추가될 예정임이 명시됨. 총 4회차 운영 구조는 유지되나 첫 회차 일정이 변경됨.",
      "confidence": "high"
    },
    {
      "change_id": "C04",
      "mapping": "1:1",
      "diff_types": ["lexical"],
      "semantic_labels": ["ambiguity_resolved"],
      "prior_block_ids": ["prior_spec-B0230"],
      "bid_block_ids": ["bid_notice-B0231", "bid_notice-B0232"],
      "before": "7/8·7/15·7/22·8/19 (수)",
      "after": "7/15·7/22·8/19 (수) ※ 8월 일정 1회 추가 예정",
      "changed_span": {
        "before": "7/8·7/15·7/22·8/19 (수)",
        "after": "7/15·7/22·8/19 (수) ※ 8월 일정 1회 추가 예정"
      },
      "direct_impact": "2기 교육의 첫 번째 회차(7/8)가 삭제되고, 8월에 1회 일정이 추가될 예정임이 명시됨. 총 4회차 운영 구조는 유지되나 첫 회차 일정이 변경됨.",
      "confidence": "high"
    }
  ],
  "issuer_intent": [
    {
      "claim": "발주자는 1기 및 2기 교육의 초기 일정(7월 초)을 8월 이후로 연기하여 교육 운영 일정을 조정하고자 한다.",
      "basis_change_ids": ["C02", "C03", "C04"],
      "support_level": "supported",
      "reason": "사전규격의 7/7, 7/8 일정이 입찰공고에서 '8월 이후로 변경 예정'으로 대체되었고, 교육일정②의 1, 2기 첫 회차가 각각 7/14, 7/15로 변경되었으며 8월 일정 추가가 명시됨."
    },
    {
      "claim": "발주자는 입찰 마감일을 연장하여 참가 업체의 제안서 준비 기간을 충분히 확보하고자 한다.",
      "basis_change_ids": ["C01"],
      "support_level": "supported",
      "reason": "입찰마감일시가 7/2(목) 11:00에서 7/10(금) 14:00로, 서류 제출 기한이 7/2(목) 18:00에서 7/10(금) 18:00로 변경되어 8일의 추가 기간이 부여됨."
    }
  ],
  "uncertainties": [
    {
      "question": "1기 및 2기 교육의 8월 추가 일정 1회의 구체적인 날짜와 시간은 언제인가?",
      "why_it_matters": "교육일정②의 1, 2기는 각각 4회차로 구성되나, 첫 회차가 삭제되고 8월에 1회 추가 예정이므로 실제 운영 일수와 장비 임차 일정에 영향을 미침. 구체적인 날짜가 명시되지 않아 정확한 물류 및 인력 계획 수립이 어려움."
    },
    {
      "question": "1기 및 2기 교육의 변경된 첫 회차(7/14, 7/15) 이후 나머지 3회차의 일정은 기존과 동일한가?",
      "why_it_matters": "7/14, 7/15 이후의 일정(7/21, 8/18 등)이 기존과 동일한지, 아니면 전체 일정이 조정되었는지에 따라 장비 배송·회수 주기와 인력 투입 계획이 달라질 수 있음."
    }
  ]
}
