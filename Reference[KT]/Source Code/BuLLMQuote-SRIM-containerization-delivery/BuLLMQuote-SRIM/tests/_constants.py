"""Shared test constants — importable by both conftest.py and test modules."""

SYNTHETIC_RFQ_ID = "TEST-RFQ-001"

# (bom_item_id, cpn, fg, assembly, is_assembly, commodity)
SYNTHETIC_PARTS = [
    ("aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa", "CPN-001", "TEST-FG-001", "TEST-FG-001", True,  "Assembly"),
    ("aaaaaaaa-0001-0001-0001-bbbbbbbbbbbb", "CPN-002", "TEST-FG-001", "TEST-FG-001", False, "Passive"),
    ("aaaaaaaa-0001-0001-0001-cccccccccccc", "CPN-003", "TEST-FG-001", "TEST-FG-001", False, "Passive"),
    ("aaaaaaaa-0001-0001-0001-dddddddddddd", "CPN-004", "TEST-FG-001", "TEST-FG-001", False, "Active"),
    ("aaaaaaaa-0001-0001-0001-eeeeeeeeeeee", "CPN-005", "TEST-FG-001", "TEST-FG-001", False, "PCB"),
    ("aaaaaaaa-0001-0001-0001-ffffffffffff", "CPN-006", "TEST-FG-001", "SUB-ASM-001", True,  "Electromechanical"),
    ("aaaaaaaa-0001-0001-0001-111111111111", "CPN-007", "TEST-FG-001", "SUB-ASM-001", False, "Passive"),
    ("aaaaaaaa-0001-0001-0001-222222222222", "CPN-008", "TEST-FG-001", "SUB-ASM-001", False, "Active"),
    ("aaaaaaaa-0001-0001-0001-333333333333", "CPN-009", "TEST-FG-001", "TEST-FG-001", False, "Electromechanical"),
    ("aaaaaaaa-0001-0001-0001-444444444444", "CPN-010", "TEST-FG-001", "TEST-FG-001", False, "Active"),
]
