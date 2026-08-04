import pytest
from pydantic import ValidationError

from customer_issue_agent.domain import (
    AnalysisRequest,
    EvidenceStrength,
    IssueCategory,
    Responsibility,
)


def test_analysis_request_product_fields_are_optional_and_trimmed():
    empty = AnalysisRequest(platform="Amazon", conversation_text="Customer: broken")
    populated = AnalysisRequest(
        platform="Amazon",
        conversation_text="Customer: broken",
        store_name="  US Store  ",
        sku="  SKU-01  ",
        platform_product_id="  B0ABC123  ",
    )

    assert empty.store_name == ""
    assert empty.sku == ""
    assert empty.platform_product_id == ""
    assert populated.store_name == "US Store"
    assert populated.sku == "SKU-01"
    assert populated.platform_product_id == "B0ABC123"


@pytest.mark.parametrize("field", ["store_name", "sku", "platform_product_id"])
def test_analysis_request_rejects_overlong_product_field(field):
    payload = {
        "platform": "Amazon",
        "conversation_text": "Customer: broken",
        field: "x" * 201,
    }

    with pytest.raises(ValidationError):
        AnalysisRequest(**payload)


@pytest.mark.parametrize("value", [True, [], {}])
def test_analysis_request_rejects_non_string_sku(value):
    with pytest.raises(ValidationError):
        AnalysisRequest(
            platform="Amazon",
            conversation_text="Customer: broken",
            sku=value,
        )


def test_analysis_request_trims_conversation_text():
    request = AnalysisRequest(
        platform="Shopee",
        conversation_text="  Customer: not working  ",
    )

    assert request.platform == "Shopee"
    assert request.conversation_text == "Customer: not working"


def test_domain_enums_keep_chinese_labels():
    assert IssueCategory.FUNCTION_USE.label == "功能不会用或设置失败"
    assert Responsibility.CUSTOMER_SERVICE_TRAINING.label == "客服培训"
    assert EvidenceStrength.INSUFFICIENT.label == "信息不足"
