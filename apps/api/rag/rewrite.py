"""Turn a vague question into a search query. Optional, off by default (QUERY_REWRITE=true)."""

import logging
import re

from rag.providers.base import ChatMessage, ChatModel, ProviderError

INSTRUCTIONS = (
    "You rewrite a user's question as a search query for a collection of official documents. "
    "Replace vague words with the specific terms, names and numbers the documents would use, "
    "and keep every concrete detail from the question. Do not answer the question. "
    "Reply with the query only, on one line."
)


def clean(reply: str, question: str) -> str:
    """First non-empty line of the reply without think tags or quotes; the question if nothing is left."""
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL)
    lines = [line.strip().strip("\"'`") for line in reply.splitlines() if line.strip()]
    return lines[0][:300] if lines else question


async def rewrite_query(model: ChatModel, question: str) -> str:
    """The rewritten query, or the question itself when the model fails: rewriting is never a reason to refuse."""
    messages = [ChatMessage("system", INSTRUCTIONS), ChatMessage("user", question)]
    try:
        reply = "".join([token async for token in model.stream(messages, temperature=0)])
    except ProviderError:
        logging.getLogger("rag").warning("Query rewrite failed; searching with the original question")
        return question
    return clean(reply, question)
