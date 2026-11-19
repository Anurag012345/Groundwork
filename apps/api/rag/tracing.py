"""Optional Langfuse tracing. Off (and free) unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.

Needs the optional `langfuse` package (image build arg EXTRAS=trace). Every call is safe to make
with tracing off: `start` then returns an object whose methods do nothing.
"""

import logging
from functools import cache

from rag.config import settings


class _Off:
    """Stands in for a Langfuse observation: every method does nothing and returns itself."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@cache
def client():
    config = settings()
    if not (config.langfuse_public_key and config.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        logging.getLogger("rag").warning(
            "Langfuse keys are set but langfuse is not installed (EXTRAS=trace)"
        )
        return None
    return Langfuse(
        public_key=config.langfuse_public_key,
        secret_key=config.langfuse_secret_key.get_secret_value(),
        host=config.langfuse_host,
    )


def start(name: str, **fields):
    """Start a new trace; end it with `.end()`. Children come from `.start_observation(...)`."""
    langfuse = client()
    return langfuse.start_observation(name=name, **fields) if langfuse else _Off()


def shutdown() -> None:
    """Send whatever is still queued."""
    langfuse = client()
    if langfuse:
        langfuse.shutdown()
