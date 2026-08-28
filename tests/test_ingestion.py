from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook

from customer_issue_agent.ingestion import (
    ExtractedConversation,
    extract_batch_conversations,
    extract_conversation,
)


def _workbook_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_txt_conversation_has_empty_file_product_metadata():
    extracted = extract_conversation("conversation.txt", b"Customer: broken")

    assert extracted == ExtractedConversation(conversation_text="Customer: broken")


def test_batch_csv_extracts_fixed_priority_product_aliases():
    content = (
        "conversation,store,shop,sku,seller_sku,product_id,asin\n"
        "Customer: broken,Store A,Ignored Shop,SKU-01,Ignored SKU,P-01,B0IGNORED\n"
    ).encode("utf-8")

    extracted = extract_batch_conversations("batch.csv", content)

    assert extracted == [
        ExtractedConversation(
            conversation_text="Customer: broken",
            store_name="Store A",
            sku="SKU-01",
            platform_product_id="P-01",
        )
    ]


def test_single_csv_accepts_repeated_product_metadata():
    content = (
        "speaker,message,sku,asin\n"
        "Customer,It is broken,SKU-01,B0ABC\n"
        "Agent,Please restart,sku-01,b0abc\n"
    ).encode("utf-8")

    extracted = extract_conversation("conversation.csv", content)

    assert extracted.conversation_text == "Customer: It is broken\nAgent: Please restart"
    assert extracted.sku == "SKU-01"
    assert extracted.platform_product_id == "B0ABC"


def test_single_csv_rejects_conflicting_skus():
    content = (
        "speaker,message,sku\n"
        "Customer,First issue,SKU-01\n"
        "Agent,Second row,SKU-02\n"
    ).encode("utf-8")

    with pytest.raises(ValueError, match="多个 SKU"):
        extract_conversation("conversation.csv", content)


def test_batch_xlsx_converts_numeric_product_ids_without_dot_zero():
    content = _workbook_bytes(
        [
            ["conversation", "sku", "product_id"],
            ["Customer: broken", 1001, 12345.0],
        ]
    )

    extracted = extract_batch_conversations("batch.xlsx", content)

    assert extracted[0].sku == "1001"
    assert extracted[0].platform_product_id == "12345"


def test_batch_xlsx_without_conversation_column_preserves_row_fallback():
    content = _workbook_bytes(
        [
            ["channel", "details"],
            ["Amazon", "Customer: It will not connect"],
            ["Shopee", "Customer: Missing cable"],
        ]
    )

    extracted = extract_batch_conversations("batch.xlsx", content)

    assert [item.conversation_text for item in extracted] == [
        "Amazon Customer: It will not connect",
        "Shopee Customer: Missing cable",
    ]


@pytest.mark.parametrize("invalid", [True, date(2026, 8, 4)])
def test_batch_xlsx_rejects_boolean_and_date_product_ids(invalid):
    content = _workbook_bytes(
        [
            ["conversation", "sku"],
            ["Customer: broken", invalid],
        ]
    )

    with pytest.raises(ValueError, match="商品标识"):
        extract_batch_conversations("batch.xlsx", content)


def test_extract_plain_text_upload():
    result = extract_conversation(
        filename="chat.txt",
        content=b"Customer: It does not connect\nAgent: Please restart it",
    )

    assert result.conversation_text == "Customer: It does not connect\nAgent: Please restart it"


def test_extract_csv_upload_combines_rows():
    content = "speaker,message\nCustomer,It does not connect\nAgent,Please restart it\n".encode("utf-8")

    result = extract_conversation(filename="chat.csv", content=content)

    assert "Customer: It does not connect" in result.conversation_text
    assert "Agent: Please restart it" in result.conversation_text


def test_extract_rejects_empty_upload():
    try:
        extract_conversation(filename="chat.txt", content=b"   ")
    except ValueError as exc:
        assert "没有可分析内容" in str(exc)
    else:
        raise AssertionError("empty upload should fail")


def test_extract_batch_text_upload_splits_on_explicit_separator():
    content = (
        "Customer: It will not connect\nAgent: Please restart it\n"
        "\n---\n"
        "Customer: Missing cable\nAgent: We can send a replacement"
    ).encode("utf-8")

    result = extract_batch_conversations(filename="batch.txt", content=content)

    assert [item.conversation_text for item in result] == [
        "Customer: It will not connect\nAgent: Please restart it",
        "Customer: Missing cable\nAgent: We can send a replacement",
    ]


def test_extract_batch_csv_upload_uses_one_row_per_conversation():
    content = (
        "platform,conversation\n"
        "Amazon,\"Customer: It will not connect\"\n"
        "TikTok Shop,\"Customer: Missing cable\"\n"
    ).encode("utf-8")

    result = extract_batch_conversations(filename="batch.csv", content=content)

    assert [item.conversation_text for item in result] == [
        "Customer: It will not connect",
        "Customer: Missing cable",
    ]


def test_extract_batch_rejects_more_than_limit():
    conversations = "\n---\n".join(f"Customer: issue {index}" for index in range(51))

    try:
        extract_batch_conversations(filename="batch.txt", content=conversations.encode("utf-8"))
    except ValueError as exc:
        assert "单次最多分析 50 条" in str(exc)
    else:
        raise AssertionError("batch over limit should fail")
