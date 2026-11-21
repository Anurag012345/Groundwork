"""Cost per 1,000 queries from a saved run: python evals/cost.py supersession [--in-price 0.10 --out-price 0.30 --gpu-hour 0.50]

Every model in the eval is local, so there is no bill. This prices the measured token volume and
GPU time at rates you supply. The defaults are assumptions, not quotes; replace them with real ones.
Chars per token were measured on the generator (Qwen3-4B) through Ollama: 4.02 on the corpus text
(12 windows) and 4.77 on its own answers (12 answers). Judge calls are eval-only and not counted.
"""

import argparse
import json
import statistics
from pathlib import Path

CONTEXT_CHARS_PER_TOKEN = 4.02
ANSWER_CHARS_PER_TOKEN = 4.77


def per_1k(rows, in_price, out_price, gpu_hour):
    """Dollars per 1,000 queries: hosted token pricing, and GPU time for the generation step."""
    in_tokens = statistics.mean(r["prompt_chars"] for r in rows) / CONTEXT_CHARS_PER_TOKEN
    out_tokens = statistics.mean(r["answer_chars"] for r in rows) / ANSWER_CHARS_PER_TOKEN
    gpu_seconds = statistics.mean(r["generation_s"] for r in rows)
    return {
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "gpu_seconds": gpu_seconds,
        "hosted": 1000 * (in_tokens * in_price + out_tokens * out_price) / 1e6,
        "self_hosted": 1000 * gpu_seconds / 3600 * gpu_hour,
    }


if __name__ == "__main__":
    demo = per_1k([{"prompt_chars": 4020, "answer_chars": 477, "generation_s": 3600}], 1, 2, 1)
    assert round(demo["hosted"], 6) == 1.2 and demo["self_hosted"] == 1000
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--in-price", type=float, default=0.10, help="$ per 1M input tokens (assumed)")
    parser.add_argument("--out-price", type=float, default=0.30, help="$ per 1M output tokens (assumed)")
    parser.add_argument("--gpu-hour", type=float, default=0.50, help="$ per GPU hour (assumed)")
    args = parser.parse_args()
    path = Path(__file__).parent / "results" / f"{args.tag}.json"
    rows = [r for r in json.loads(path.read_text(encoding="utf-8"))["results"] if r.get("generation_s")]
    result = per_1k(rows, args.in_price, args.out_price, args.gpu_hour)
    print(f"{len(rows)} queries: {result['input_tokens']:.0f} input + {result['output_tokens']:.0f} output tokens, "
          f"{result['gpu_seconds']:.1f} s generation each")
    print(f"hosted at ${args.in_price}/M in, ${args.out_price}/M out: ${result['hosted']:.3f} per 1,000 queries")
    print(f"self-hosted GPU at ${args.gpu_hour}/hour:       ${result['self_hosted']:.2f} per 1,000 queries")
    print(f"scale: ${1000 * result['input_tokens'] / 1e6:.2f} per $1/M input, "
          f"${1000 * result['output_tokens'] / 1e6:.2f} per $1/M output")
