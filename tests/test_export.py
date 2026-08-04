import csv
from io import StringIO

from customer_issue_agent.export import CSV_HEADERS, build_records_csv


def _product_record(
    *,
    store_name: str = "",
    sku: str = "",
    platform_product_id: str = "",
) -> dict:
    return {
        "id": "record-product",
        "created_at": "2026-08-04T00:00:00+00:00",
        "analysis": {
            "request": {
                "platform": "Amazon",
                "store_name": store_name,
                "sku": sku,
                "platform_product_id": platform_product_id,
            },
            "attribution": {
                "customer_problem": "连接失败",
                "issue_category": "function_use",
                "root_causes": ["unclear_instructions"],
                "primary_responsibility": "customer_service_training",
                "evidence_strength": "likely",
                "recommended_actions": ["补问设备型号"],
                "missing_information": ["设备型号"],
            },
        },
        "feedback": None,
    }


def test_build_records_csv_includes_bom_headers_and_feedback():
    records = [
        {
            "id": "record-1",
            "created_at": "2026-07-29T00:00:00+00:00",
            "analysis": {
                "request": {"platform": "Amazon"},
                "attribution": {
                    "customer_problem": "连接失败",
                    "issue_category": "function_use",
                    "root_causes": ["unclear_instructions", "customer_service_gap"],
                    "primary_responsibility": "customer_service_training",
                    "evidence_strength": "likely",
                    "recommended_actions": ["补问设备型号", "补问错误提示"],
                    "missing_information": ["设备型号"],
                },
            },
            "feedback": {
                "accepted": False,
                "corrected_issue_category": "product_fault",
                "corrected_responsibility": "supply_chain_quality",
                "note": "需要质量团队复核。",
            },
        }
    ]

    output = build_records_csv(records)

    assert output.startswith(b"\xef\xbb\xbf")
    text = output.decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(text)))
    assert CSV_HEADERS[:3] == ["记录 ID", "创建时间", "平台"]
    assert rows[0]["记录 ID"] == "record-1"
    assert rows[0]["平台"] == "Amazon"
    assert rows[0]["客户问题"] == "连接失败"
    assert rows[0]["业务原因"] == "unclear_instructions；customer_service_gap"
    assert rows[0]["是否认可"] == "否"
    assert rows[0]["修正责任方"] == "supply_chain_quality"
    assert rows[0]["人工备注"] == "需要质量团队复核。"


def test_build_records_csv_exports_header_when_empty():
    output = build_records_csv([])

    text = output.decode("utf-8-sig")
    rows = list(csv.reader(StringIO(text)))
    assert rows == [CSV_HEADERS]


def test_records_csv_exports_product_metadata_after_platform():
    record = _product_record(
        store_name="美国旗舰店",
        sku="SKU-01",
        platform_product_id="B0ABC",
    )

    decoded = build_records_csv([record]).decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(decoded)))

    platform_index = list(rows[0]).index("平台")
    assert list(rows[0])[platform_index : platform_index + 4] == [
        "平台",
        "店铺",
        "SKU",
        "平台商品 ID",
    ]
    assert rows[0]["店铺"] == "美国旗舰店"
    assert rows[0]["SKU"] == "SKU-01"
    assert rows[0]["平台商品 ID"] == "B0ABC"


def test_records_csv_leaves_legacy_product_fields_empty():
    decoded = build_records_csv([_product_record()]).decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(decoded)))

    assert rows[0]["店铺"] == ""
    assert rows[0]["SKU"] == ""
    assert rows[0]["平台商品 ID"] == ""
