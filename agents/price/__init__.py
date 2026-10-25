"""P1 price agent.

Entry point for the pipeline: run_price_agent(question, query_date), which
uses the approach set in config.yaml (price_agent.approach: "A" or "B").
  A = filter tool (agents/price/agent.py)
  B = text-to-SQL (agents/price/sql_agent.py)
"""

from agents.price.agent import price_agent
from agents.price.data import load_price_settings
from agents.price.sql_agent import price_agent_sql

APPROACHES = {"A": price_agent, "B": price_agent_sql}


def run_price_agent(question, query_date=None, **kwargs):
    """Answer with the approach chosen in config.yaml (default A)."""
    approach = str(load_price_settings().get("approach", "A")).upper()
    if approach not in APPROACHES:
        raise ValueError(f"Unknown price_agent.approach {approach!r}; use 'A' or 'B'.")
    return APPROACHES[approach](question, query_date, **kwargs)


__all__ = ["run_price_agent", "price_agent", "price_agent_sql"]
