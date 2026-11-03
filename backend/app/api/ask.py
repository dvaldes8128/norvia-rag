"""POST /ask — tenant-scoped QA with verifiable citations (R4)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from opentelemetry import trace

from app.api.deps import CurrentTenant
from app.api.schemas import AskRequest, AskResponse, CitationOut
from app.core.logging import get_logger, redacted_text
from app.db.session import tenant_session
from app.providers.factory import get_llm_provider
from app.qa.prompt import build_prompt
from app.qa.service import AnswerPayload, answer_question, payload_from_answer
from app.retrieval.hybrid import retrieve

logger = get_logger(__name__)

router = APIRouter(tags=["qa"])


def _to_response(payload: AnswerPayload) -> AskResponse:
    return AskResponse(
        answer=payload.answer,
        citations=[CitationOut.model_validate(c.model_dump()) for c in payload.citations],
        confidence=payload.confidence,
    )


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, principal: CurrentTenant) -> AskResponse:
    trace.get_current_span().set_attribute("tenant_id", principal.tenant_id)
    # Redacted: never log the full user question (Q6.2) — length/hash/preview only.
    logger.info(
        "ask.received",
        tenant_id=principal.tenant_id,
        citation_top_n=body.citation_top_n,
        lexical_grounding=body.lexical_grounding,
        **redacted_text("question", body.question),
    )
    with tenant_session(principal.tenant_id) as session:
        payload = answer_question(
            session,
            question=body.question,
            tenant_id=principal.tenant_id,
            citation_top_n=body.citation_top_n,
            lexical_grounding=body.lexical_grounding,
        )
    logger.info(
        "ask.completed",
        tenant_id=principal.tenant_id,
        citation_count=len(payload.citations),
        confidence=payload.confidence,
    )
    return _to_response(payload)


@router.post("/ask/stream")
def ask_stream(body: AskRequest, principal: CurrentTenant) -> StreamingResponse:
    """Optional token streaming of the answer text (F4.4).

    Streams plain text tokens, then a final ``<!--NORVIA_META:{json}-->`` trailer with
    the validated citations/confidence so the UI can attach sources without a second call.
    """

    def _generate():
        with tenant_session(principal.tenant_id) as session:
            chunks = retrieve(session, question=body.question)
            prompt = build_prompt(body.question, chunks)
            llm = get_llm_provider()
            parts: list[str] = []
            for token in llm.stream(prompt):
                parts.append(token)
                yield token

            payload = payload_from_answer(
                "".join(parts),
                chunks,
                citation_top_n=body.citation_top_n,
                lexical_grounding=body.lexical_grounding,
            )
            meta = _to_response(payload)
            yield "\n\n<!--NORVIA_META:"
            yield meta.model_dump_json()
            yield "-->"

    return StreamingResponse(_generate(), media_type="text/plain; charset=utf-8")
