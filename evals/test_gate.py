from gate import check

CONFIG = {"top_k": 5, "mode": "hybrid", "rerank": "r", "candidates": 20, "kb": "default",
          "chat_model": "m", "judge": "j", "embedding_model": "e", "questions": 122}
BASE = {
    "config": CONFIG,
    "retrieval": {"doc_hit": 1.0, "mrr": 0.95},
    "abstention": {"correct_refusal_on_unanswerable": 1.0, "false_refusal_on_answerable": 0.0},
    "answer_correct": 0.91,
    "faithfulness": 0.98,
}


def run(**changes):
    return {**BASE, **changes}


def test_identical_run_passes():
    assert check(BASE, BASE) == []


def test_noise_within_tolerance_passes():
    assert check(BASE, run(faithfulness=0.96)) == []


def test_faithfulness_drop_fails():
    problems = check(BASE, run(faithfulness=0.90))
    assert len(problems) == 1 and problems[0].startswith("faithfulness")


def test_more_false_refusals_fails():
    abstention = {**BASE["abstention"], "false_refusal_on_answerable": 0.10}
    assert any("false_refusal" in p for p in check(BASE, run(abstention=abstention)))


def test_missing_metric_fails():
    current = {k: v for k, v in BASE.items() if k != "faithfulness"}
    assert any("missing" in p for p in check(BASE, current))


def test_different_config_is_not_compared():
    problems = check(BASE, run(config={**CONFIG, "judge": "other"}))
    assert "not comparable" in problems[0] and len(problems) == 2
