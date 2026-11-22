import pytest

from analyst.data import build_database
from analyst.graph import build_graph
from analyst.guardrails import GuardrailViolation, validate_sql
from analyst.llm import MockProvider


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return str(build_database(tmp_path_factory.mktemp("d") / "demo.db", n_customers=300))


def test_guardrail_blocks_writes():
    with pytest.raises(GuardrailViolation):
        validate_sql("DELETE FROM customers")
    with pytest.raises(GuardrailViolation):
        validate_sql("SELECT * FROM customers; DROP TABLE customers")


def test_guardrail_adds_limit_and_blocks_unknown_tables():
    assert validate_sql("SELECT * FROM customers").endswith("LIMIT 200")
    with pytest.raises(GuardrailViolation):
        validate_sql("SELECT * FROM sqlite_master")


def test_end_to_end_churn_question(db):
    result = build_graph(db, llm=MockProvider()).invoke({"question": "Which segment has the highest churn rate?"})
    assert result["route"] == "sql"
    assert "churn_rate_pct" in result["data"][0]
    agents = [step["agent"] for step in result["trace"]]
    assert agents == ["planner", "sql_agent", "guardrail", "executor", "analyst", "reporter"]


class BadSQLProvider(MockProvider):
    def complete(self, system, prompt, **kw):
        resp = super().complete(system, prompt, **kw)
        if "sql agent" in system.lower():
            resp.text = "DROP TABLE customers"
        return resp


def test_unsafe_sql_is_retried_then_refused(db):
    result = build_graph(db, llm=BadSQLProvider()).invoke({"question": "What is the churn rate?"})
    assert result["attempts"] == 2
    assert "could not answer safely" in result["report"]
