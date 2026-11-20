from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app import ChatInput, Metadata

tags = TypeAdapter(Metadata)


def test_flat_scalars_are_accepted_and_keep_their_types():
    assert tags.validate_python({"month": "nov-2026", "year": 2026, "final": True}) == {
        "month": "nov-2026",
        "year": 2026,
        "final": True,
    }


@pytest.mark.parametrize(
    "bad", [{"nested": {"a": 1}}, {"list": [1]}, {"k" * 65: "v"}, {"k": "v" * 201}]
)
def test_nested_or_oversized_metadata_is_rejected(bad):
    with pytest.raises(ValidationError):
        tags.validate_python(bad)


def test_too_many_keys_are_rejected():
    with pytest.raises(ValidationError):
        tags.validate_python({f"k{i}": i for i in range(21)})


def test_chat_filters_default_to_none_and_are_validated():
    assert ChatInput(knowledge_base_id=uuid4(), question="q").filters == {}
    with pytest.raises(ValidationError):
        ChatInput(knowledge_base_id=uuid4(), question="q", filters={"a": ["b"]})
