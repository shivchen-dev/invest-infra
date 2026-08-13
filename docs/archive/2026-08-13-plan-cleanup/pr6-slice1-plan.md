# PR-6 Slice 1: JiuwenSwarm Adapter Boundary

Scope: introduce the `invest_pipeline.adapters.jiuwenswarm` package and wire
the domain `ResearchRunner` port to a deterministic request mapper, a
versioned transport `Protocol`, and a validated completion mapper. No real
WebSocket / network transport is delivered in this slice.

## Public seams (frozen)

- Domain `ResearchRunner` port in `invest_domain.research.runner.ResearchRunner`
  plus `ResearchRunnerDraft`, `ResearchPlaybook`, lifecycle helpers. The
  adapter must satisfy `runtime_checkable` protocol surface and reuse
  `_validate_case_pack_alignment` (already binds case/run/pack UUIDs).
- `JiuwenSwarmGatewayTransport` `Protocol` defined in this slice:
  synchronous `submit(request) -> transport_result`; the implementation is
  injected. A fake transport is supplied in tests; the real WebSocket
  transport lands in Slice 2.
- Codec request/result DTOs:
  - `JiuwenSwarmGatewayRequest` — versioned (schema version
    `1.0.0`), carries evidence IDs (not values), `case_id`,
    `evidence_pack_id`, `run_id`, `playbook`, adapter context.
  - `JiuwenSwarmCompletion` — validated gateway completion: conclusion /
    risks / evidence_ids / report_markdown / model_key / model_version /
    playbook_version / acceptance `enum`.

## Slice 1 deliverables

1. `apps/pipeline/src/invest_pipeline/adapters/jiuwenswarm/__init__.py`
   re-exports public symbols.
2. `apps/pipeline/src/invest_pipeline/adapters/jiuwenswarm/codec.py`
   exposes request / completion dataclasses, `JiuwenSwarmSchemaError`,
   `JiuwenSwarmAcceptance`, `JiuwenSwarmGatewayRequest` and
   `JiuwenSwarmCompletion`.
3. `apps/pipeline/src/invest_pipeline/adapters/jiuwenswarm/transport.py`
   exposes the `JiuwenSwarmGatewayTransport` `Protocol`, the
   `JiuwenSwarmTransportResult` carrier (preserves request / session IDs
   but does not persist them), and a no-network `InMemoryGatewayTransport`
   only used in tests.
4. `apps/pipeline/src/invest_pipeline/adapters/jiuwenswarm/mapping.py`
   exposes:
   - `build_request(case, run, evidence_pack, playbook, *, adapter_version)`
     — deterministic mapper: extracts exact evidence IDs (no values), no
     workspace path / credentials / runtime metadata. The mapper is a
     pure function (no IO) and rejects case/run/pack trio whose binding
     does not match.
   - `build_draft(completion, playbook, *, adapter_version, now)` —
     deterministic mapper from a validated completion to a
     `ResearchRunnerDraft` ready for domain completion.
5. `apps/pipeline/src/invest_pipeline/adapters/jiuwenswarm/errors.py`
   exposes adapter-specific errors:
   - `JiuwenSwarmTransportError` (transport raised),
   - `JiuwenSwarmTimeoutUncertainError` (accepted but locally timed out),
   - `JiuwenSwarmRemoteFailureError` (gateway rejected),
   - `JiuwenSwarmMalformedResultError` (schema invalid).
6. `apps/pipeline/src/invest_pipeline/adapters/jiuwenswarm/runner.py`
   exposes `JiuwenSwarmResearchRunner` — implements `ResearchRunner`,
   enforces runner / playbook / pack binding, validates adapter /
   playbook versions, delegates to injected transport, maps the
   transport result into `ResearchRunnerDraft` or raises typed errors.
7. Tests under `apps/pipeline/tests/unit/test_jiuwenswarm_*.py`
   covering: protocol satisfaction, deterministic request mapping, no
   local / runtime metadata leakage, valid draft mapping, invalid
   schema rejection, remote failure, uncertain timeout classification,
   transport called exactly once.

## Boundaries / non-goals

- No dependency additions; no `httpx` / `websockets` imports.
- No real Gateway (Slice 2 will add WebSocket transport).
- No storage / UoW changes; `external_request_id` /
  `external_session_id` are *preserved* on `JiuwenSwarmTransportResult`
  for later orchestration but never written here.
- No API endpoints (PR-7).
- No documentation beyond this plan.

## Verification

- Focused tests: `uv run --no-env-file pytest
  apps/pipeline/tests/unit/test_jiuwenswarm_*.py -q`
- Full pipeline: `uv run ruff check src tests` +
  `uv run --no-env-file pytest -q`
- Architecture boundary check: `python3 scripts/check_architecture.py`
- `git diff --check`

## Three untracked files preserved

`coding_memory/`, `docs/archive/2026-08-06-plan-cleanup/README.md`,
`packages/domain/uv.lock`, `packages/storage/uv.lock`,
`prompt_attachment/` — not touched by this slice.