from decimal import Decimal
import pytest
from cost_budget import BudgetError, price_record, estimated_cost, check_budget, usage_from_response

def test_decimal_costs():
    price = price_record("example-model", "1.25", "10", "2026-11-13")
    assert estimated_cost(1_000_000, 100_000, price) == 2.25

def test_limit_rejects_expensive_call():
    price = price_record("example-model", "1", "10", "2026-11-13")
    with pytest.raises(BudgetError, match="Restbudget"):
        check_budget("1", "0.95", price, 10_000, 10_000)

def test_limit_accepts_bounded_call():
    price = price_record("example-model", "1", "10", "2026-11-13")
    assert check_budget("5", "1", price, 10_000, 10_000) == Decimal('0.11')

def test_missing_price_date_rejected():
    with pytest.raises(BudgetError):
        price_record("example-model", "1", "2", "")

def test_usage_normalization():
    assert usage_from_response("OpenAI", {"usage": {"input_tokens": 120, "output_tokens": 30}}) == {"input_tokens": 120, "output_tokens": 30}
    assert usage_from_response("OpenAI", {"usage": {}}) is None
    assert usage_from_response("LM Studio (lokal)", {"usage": {"prompt_tokens": 10, "completion_tokens": 20}}) == {"input_tokens": 10, "output_tokens": 20}

def test_negative_budget_rejected():
    with pytest.raises(BudgetError):
        check_budget("-1", "0", price_record("x", "1", "1", "today"), 10, 10)
