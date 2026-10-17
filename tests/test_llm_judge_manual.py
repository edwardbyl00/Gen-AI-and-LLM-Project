import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from llm_judge import judge_answer


evidence = [
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


cases = [
    {
        "name": "GOOD ANSWER",
        "question": "Can I use CPF savings to buy a home?",
        "answer": (
            "CPF Ordinary Account savings may be used "
            "for eligible housing purchases."
        ),
    },
    {
        "name": "UNSUPPORTED ANSWER",
        "question": "Can I use CPF savings to buy a home?",
        "answer": (
            "Yes. You can always use all of your CPF savings "
            "to buy any property with no restrictions."
        ),
    },
    {
        "name": "MADE-UP ANSWER",
        "question": "Can I use CPF savings to buy a home?",
        "answer": (
            "You can use up to $500,000 of CPF savings, "
            "and there are no eligibility conditions."
        ),
    },
    {
        "name": "CORRECT ABSTENTION",
        "question": "What is the maximum CPF amount I can use to buy this property?",
        "answer": (
            "The retrieved evidence does not provide enough information "
            "to determine the maximum CPF amount."
        ),
    },
]

total_cost = 0.0

for case in cases:
    print("\n" + "=" * 60)
    print(case["name"])
    print("=" * 60)

    result = judge_answer(
        question=case["question"],
        answer=case["answer"],
        evidence=evidence,
    )

    print("Judgement:")
    print(result["judgement"])

    print("Usage:")
    print(result["usage"])

    total_cost += result["usage"]["cost_usd"]

print("\n" + "=" * 60)
print("TOTAL COST")
print("=" * 60)
print(f"${total_cost:.6f}")