"""JiuwenSwarm grounded prompt construction (PR-6 Slice 2).

The Slice 2 transport hands the helper a *plain-text* task file whose
contents are the entire prompt the gateway helper forwards to the
model. The prompt has two responsibilities:

- Embed the deterministic request envelope
  (:meth:`JiuwenSwarmGatewayRequest.to_json`) verbatim so the model
  receives every citation key the gateway must echo back (case
  identity, pack identity, evidence-ID whitelist, factor values,
  source references).
- Encode the Slice 2 prompt rules: no workspace or filesystem access,
  no external data, no unsupported facts, no unprovided indicators or
  levels, no trading advice. Unknown facts must be reported as
  ``"unknown"``. Every claim must cite one of the supplied
  ``evidence_ids``.

The rules are part of the public contract. PR-6 §4.3 requires the
prompt to suppress any output that would otherwise let the model cross
the evidence boundary — the rules are therefore baked into the prompt
text and the helper is responsible for surfacing them as a runtime
instruction; the orchestrator must never override them.

The module is a pure function over the request envelope: no IO, no
logging, no clock side-effects. The prompt text is byte-stable for a
given request so the helper can hash it deterministically.
"""

from __future__ import annotations

from invest_pipeline.adapters.jiuwenswarm.codec import JiuwenSwarmGatewayRequest

JIUWENSWARM_PROMPT_RULES = (
    "Rules you must follow for the entire response:\n"
    "1. Use ONLY the evidence provided in REQUEST_JSON. Do NOT read, "
    "open, list, search, or otherwise access the workspace, the "
    "filesystem, or any external system. Do NOT write to the "
    "workspace or the filesystem.\n"
    "2. Do NOT call external tools, APIs, web pages, or any network "
    "service. All reasoning must be derived from REQUEST_JSON alone.\n"
    "3. Do NOT invent facts, numbers, dates, events, or "
    "interpretations that are not present in REQUEST_JSON. If a piece "
    "of information is missing or unknown, say so explicitly using the "
    "word \"unknown\" instead of guessing.\n"
    "4. Do NOT introduce technical indicators, levels, thresholds, "
    "multiples, or rating scores that were not provided in REQUEST_JSON. "
    "Only reference the factors and source_refs the request explicitly "
    "lists.\n"
    "5. Do NOT produce trading advice, position sizing, entry/exit "
    "prices, target prices, stop-losses, or buy/sell/hold "
    "recommendations. The conclusion and risks sections must remain "
    "descriptive and grounded in the supplied evidence.\n"
    "6. Every claim in the report MUST cite one of the "
    "`evidence_ids` from REQUEST_JSON. If a claim cannot be cited, "
    "omit it.\n"
    "7. Respond with the JSON object described in the schema below; "
    "do not wrap it in prose, do not echo the rules back, and do not "
    "output anything outside that JSON object."
)

JIUWENSWARM_PROMPT_OUTPUT_SCHEMA = (
    "Output schema (single JSON object, no surrounding text):\n"
    "{\n"
    '  "schema_version": "<must equal request.schema_version>",\n'
    '  "playbook_key": "<must equal request.playbook_key>",\n'
    '  "playbook_version": "<must equal request.playbook_version>",\n'
    '  "adapter_version": "<must equal request.adapter_version>",\n'
    '  "model_key": "<your model identifier>",\n'
    '  "model_version": "<your model version>",\n'
    '  "conclusion": "<non-blank string grounded in REQUEST_JSON>",\n'
    '  "risks": ["<non-blank risk string>", "..."],\n'
    '  "evidence_ids": ["<evidence_id from REQUEST_JSON>", "..."],\n'
    '  "report_markdown": "<final report text written to result.md>",\n'
    '  "acceptance": "accepted" | "rejected" | "uncertain_timeout"\n'
    "}"
)


def build_prompt_text(request: JiuwenSwarmGatewayRequest) -> str:
    """Return the deterministic prompt text the helper forwards to the model.

    The function is pure: it never reads the filesystem, never logs,
    and never reads the clock. Two calls with the same request produce
    byte-identical text. ``request.to_json()`` is inlined verbatim so
    the model receives the canonical envelope the gateway needs the
    completion to round-trip.
    """

    if not isinstance(request, JiuwenSwarmGatewayRequest):
        raise TypeError(
            "build_prompt_text requires a JiuwenSwarmGatewayRequest; "
            f"got {type(request).__name__}"
        )
    request_json = request.to_json()
    return (
        "You are a research assistant. The structured request below is "
        "the ONLY source of evidence you may use. Treat it as "
        "authoritative.\n\n"
        f"{JIUWENSWARM_PROMPT_RULES}\n\n"
        f"{JIUWENSWARM_PROMPT_OUTPUT_SCHEMA}\n\n"
        "REQUEST_JSON:\n"
        f"{request_json}\n"
    )


__all__ = [
    "JIUWENSWARM_PROMPT_OUTPUT_SCHEMA",
    "JIUWENSWARM_PROMPT_RULES",
    "build_prompt_text",
]
