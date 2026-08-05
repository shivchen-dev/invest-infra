# Architecture Governance Convergence Plan

## Objective

收敛 `Core / Analytics / Research / AI` 的职责，确保 Evidence Pack 是研究任务的证据集合，而不是第二套数据仓库。

## Scope

本轮只处理：

1. Domain ownership、data ownership 和 Repository 准入规则；
2. Evidence Contract 及现有 `ResearchEvidencePack`、`ResearchContextPack`、`FieldEvidence` 的职责归属；
3. 将因子计算归入 Analytics，Research 只消费计算结果；
4. Provider 治理文档与现有 Catalog/Factory/Router 的一致性记录。

本轮明确不建设：

- AI Agent、Playbook、Thesis、Research Result 持久化；
- 新闻系统、机构数据库、Factor Store、Feature Store、回测平台；
- 新 Provider 和新的策略通道；
- API Application 层的大规模重构。

## Frozen ownership

| Area | Owns | Must not own |
|---|---|---|
| Core | Instrument, DailyBar, ETF Profile | factors, ranking, investment opinion, AI result |
| Analytics | factor calculation, risk metrics, market state, candidate ranking | research question, evidence orchestration, thesis |
| Research | Research Case, Evidence Item/Pack, context projection | re-computing market data or factor formulas |
| AI | Agent execution, playbook, thesis, confidence, report | mutating source evidence or canonical data |

## Evidence contract

```text
Raw Provider Evidence
        ↓
Canonical Core / Analytics Observation
        ↓
EvidenceItem
        ↓
EvidencePack (one research case)
        ↓
ResearchContext (derived read projection)
        ↓
AI Research
```

Rules:

- `EvidenceItem` must retain source, provenance, quality and confidence;
- `EvidencePack` is scoped to one Research Case and has immutable content hash;
- `ResearchContextPack` is a derived, replaceable read projection, not a second source of truth;
- `EtfProfileField` remains canonical-field evidence and must not become a generic research evidence store;
- external news and opinions remain raw/JSON evidence until a stable query and lifecycle require a Repository.

## Execution slices

### GOV-01 — boundary and ownership documentation

- Add authoritative governance document.
- Record current implementation mapping and intentional deviations.
- Add repository admission rules.

### GOV-02 — evidence governance

- Add Evidence lifecycle and provenance rules.
- Define the relationship between field evidence, evidence packs and context projections.
- Add contract-level tests or assertions where the existing implementation can enforce them without migration.

### GOV-03 — analytics/research seam

- Move factor calculation implementation behind an Analytics-owned interface.
- Keep compatibility imports only if required by existing callers.
- Change Research construction to consume calculated observations.
- Run focused domain and pipeline tests after each increment.

### GOV-04 — provider governance audit

- Make Catalog the declaration authority.
- Document Factory and Dataset Registry as adapters/readers of that authority.
- Record missing `experimental` and reliability-score fields without inventing runtime behavior.

## Definition of Done

- [ ] Domain ownership is documented and mapped to actual modules.
- [ ] Evidence lifecycle and provenance rules are explicit.
- [ ] Research does not calculate market factors.
- [ ] No new parallel evidence persistence model is introduced.
- [ ] Existing focused tests pass.
- [ ] Full relevant test suites pass or known blockers are recorded with evidence.
- [ ] Worktree contains no accidental generated artifacts from this work.
