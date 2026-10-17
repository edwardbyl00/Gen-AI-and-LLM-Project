import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from judge_rubric import build_judge_prompt, validate_judge_output


# Load API key from project-root .env
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise ValueError("OPENAI_API_KEY was not found in .env")

client = OpenAI(api_key=api_key)


MODEL = "gpt-5.4"

# Current GPT-5.4 pricing per 1M tokens
INPUT_PRICE = 2.50
OUTPUT_PRICE = 15.00


def judge_answer(question, answer, evidence):
    prompt = build_judge_prompt(
        question=question,
        answer=answer,
        evidence=evidence
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict evaluator. "
                    "Evaluate only from the supplied evidence. "
                    "Return JSON only."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=1000,
    )

    raw_output = response.choices[0].message.content

    result = validate_judge_output(raw_output)

    usage = response.usage

    cost = (
        usage.prompt_tokens / 1_000_000 * INPUT_PRICE
        + usage.completion_tokens / 1_000_000 * OUTPUT_PRICE
    )

    return {
        "judgement": result,
        "usage": {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "cost_usd": round(cost, 6),
        },
    }


if __name__ == "__main__":
    sample_evidence = [
        {
            "title": "Using CPF to Buy a Home",
            "source": "CPF",
            "effective_date": "2026-01-01",
            "text": (
                "CPF Ordinary Account savings may be used "
                "for eligible housing purchases."
            ),
        }
    ]

    result = judge_answer(
        question="Can I use CPF savings to buy a home?",
        answer=(
            "CPF Ordinary Account savings may be used "
            "for eligible housing purchases."
        ),
        evidence=sample_evidence,
    )

    print("\nJudgement:")
    print(result["judgement"])

    print("\nUsage:")
    print(result["usage"])