# Retrieval evaluation report

- Generated: `2026-11-03 02:10:30Z`
- Tenant: `eval-corpus`
- Corpus PDFs: `/home/runner/work/norvia-rag/norvia-rag/backend/corpus/pdfs`
- Questions: 10
- Metric: **recall@5** (document-level) + marker check + MRR
- Embeddings: fake feature-hashing (dim=768)
- Retrieval: hybrid (vector 0.6 / text 0.4), top_k=5

## Summary

| Metric | Value |
|---|---|
| recall@5 (expected doc in top-5) | **1.000** |
| marker recall@5 (all markers in retrieved text) | **1.000** |
| MRR | **1.000** |

## Per-question

| ID | Hit | Markers | Rank | Expected | Retrieved | Question |
|---|---|---|---|---|---|---|
| q1 | yes | yes | 1 | home_flood_policy | home_flood_policy, claims_procedure_notice, auto_theft_policy, health_waiting_circular, liability_war_exclusion | What is the flood coverage limit under the home policy section A? |
| q2 | yes | yes | 1 | home_flood_policy | home_flood_policy, claims_procedure_notice, liability_war_exclusion, auto_theft_policy, health_waiting_circular | How soon must flood incidents be reported after discovery? |
| q3 | yes | yes | 1 | auto_theft_policy | auto_theft_policy, home_flood_policy, liability_war_exclusion, claims_procedure_notice, health_waiting_circular | What excess applies to vehicle theft indemnification? |
| q4 | yes | yes | 1 | auto_theft_policy | auto_theft_policy, claims_procedure_notice, home_flood_policy, liability_war_exclusion, health_waiting_circular | Within how many hours must vehicle theft be notified to police and Norvia? |
| q5 | yes | yes | 1 | health_waiting_circular | health_waiting_circular, home_flood_policy, liability_war_exclusion, auto_theft_policy, claims_procedure_notice | What waiting period applies to elective orthopaedic surgery? |
| q6 | yes | yes | 1 | health_waiting_circular | health_waiting_circular, claims_procedure_notice, auto_theft_policy, liability_war_exclusion, home_flood_policy | When do maternity benefits become available under the health plan? |
| q7 | yes | yes | 1 | liability_war_exclusion | liability_war_exclusion, home_flood_policy, health_waiting_circular, auto_theft_policy, claims_procedure_notice | Does public liability cover damage arising from war or hostilities? |
| q8 | yes | yes | 1 | liability_war_exclusion | liability_war_exclusion, claims_procedure_notice, auto_theft_policy, home_flood_policy, health_waiting_circular | How are cyber operations by a nation state treated under the liability rider? |
| q9 | yes | yes | 1 | claims_procedure_notice | claims_procedure_notice, auto_theft_policy, home_flood_policy, health_waiting_circular, liability_war_exclusion | How quickly does an assigned adjuster contact the insured after a complete claims notice? |
| q10 | yes | yes | 1 | claims_procedure_notice | claims_procedure_notice, home_flood_policy, liability_war_exclusion, auto_theft_policy, health_waiting_circular | When may property damage settlements under ten thousand EUR skip a site visit? |

## Notes

- Document-level hit: any retrieved chunk belongs to an expected `doc_id`.
- Marker hit: every `expected_markers` substring appears in the retrieved chunk text.
- This report is reproducible offline with the fake providers and Compose Postgres.
