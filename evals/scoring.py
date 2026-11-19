"""Decide whether a generated answer is a refusal. No dependencies, so it runs anywhere.

A refusal says so in its first sentence ("You could not find enough information..."). A real
answer can mention "does not specify" later on, after giving the answer, so only the first
sentence counts. The previous rule searched the whole answer and misclassified both ways.

Self-check: python evals/scoring.py
"""

import re

REFUSAL = re.compile(
    r"(couldn'?t|could not|cannot|can'?t|unable to) find|not (enough|sufficient) information"
    r"|(does not|do not|doesn'?t|don'?t) (contain|provide|mention|specify|address|include|state|define)"
    r"|no (relevant )?information|(is|are|was|were) not (mentioned|specified|addressed|covered)",
    re.I,
)


def first_sentence(answer: str) -> str:
    return re.split(r"(?<=[.!?])\s", answer.strip(), maxsplit=1)[0]


def abstained(answer: str) -> bool:
    return bool(REFUSAL.search(first_sentence(answer)))


if __name__ == "__main__":
    refusals = [
        "I couldn't find enough information in this knowledge base to answer that.",
        "You could not find enough information.",
        # q120: a refusal that cites sources and runs long, which the old rule counted as an answer
        "You could not find enough information to determine how many folios have been locked. "
        "The provided sources discuss the facility but do not specify the number. [1], [2], [4]",
        "The provided sources do not specify the CAS timings when it was first introduced.",
    ]
    answers = [
        # q072: a correct answer the old rule counted as a refusal ("without any specific instruction")
        "Under the revised framework, the pay-out of unpaid securities is made to the client's demat "
        "account. Following this, an auto-pledge is created without any specific instruction from the "
        "client, with the reason unpaid.",
        # q072 as actually generated: "not covered" here describes trades, it is not a refusal
        "Under the revised framework, for trades not covered under the margin trading facility (MTF), "
        "the pay-out of unpaid securities is directly made to the client's demat account.",
        "Intraday borrowing applies from September 1, 2026. The circular does not specify a penalty.",
        "The limit is 20% of net assets [1].",
    ]
    assert all(abstained(text) for text in refusals), [t for t in refusals if not abstained(t)]
    assert not any(abstained(text) for text in answers), [t for t in answers if abstained(t)]
    print("scoring.py self-check passed")
