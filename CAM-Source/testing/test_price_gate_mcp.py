"""Edge cases for the price-gate MCP write path (mcp-tools/price-gate/mcp_server.py).

The HTTP calls are replaced by a fake: these tests check the validation and the exact requests the tools make, not the services.
"""

import importlib.util
import pathlib

import pytest

SERVER = pathlib.Path(__file__).resolve().parents[1] / "mcp-tools" / "price-gate" / "mcp_server.py"


@pytest.fixture()
def gate(monkeypatch):
    spec = importlib.util.spec_from_file_location("price_gate_mcp_server", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sent = []

    class Resp:
        def __init__(self, status=200, body=None):
            self.status_code = status
            self._body = body if body is not None else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._body

    def fake_post(url, json=None, headers=None, timeout=None, **_):
        sent.append(("POST", url, json))
        if url.endswith("/auth/token"):
            return Resp(200, {"token": "t"})
        return fake.post_response

    def fake_get(url, params=None, headers=None, timeout=None, **_):
        sent.append(("GET", url, params))
        return Resp(200, {"items": [], "next_cursor": None})

    fake = type("Fake", (), {"post_response": Resp(200, {"ok": True})})
    monkeypatch.setattr(module.httpx, "post", fake_post)
    monkeypatch.setattr(module.httpx, "get", fake_get)
    module.sent = sent
    module.fake = fake
    module.Resp = Resp
    return module


@pytest.mark.parametrize("bad", ["", "RFQ 1", "RFQ;DROP", "../etc", "RFQ/1", None])
def test_rfq_id_must_be_plain_characters(gate, bad):
    with pytest.raises(ValueError):
        gate.resolve_price_conflicts(bad, [], "person@example.com")


def test_resolved_by_must_be_an_email(gate):
    for who in ["", "person", None]:
        with pytest.raises(ValueError, match="email"):
            gate.resolve_price_conflicts("RFQ-1", [], who)


@pytest.mark.parametrize("source", ["QuoteWin", "qw ", "", None, "ERP2"])
def test_unknown_source_is_refused_before_anything_is_written(gate, source):
    with pytest.raises(ValueError, match="resolved_source"):
        gate.resolve_price_conflicts("RFQ-1", [{"conflict_id": "a", "resolved_source": source}], "person@example.com")
    assert not any(method == "POST" and "final-selection" in url for method, url, _ in gate.sent)


def test_every_resolution_carries_the_signed_in_email_and_the_chosen_source(gate):
    gate.resolve_price_conflicts(
        "RFQ-1",
        [{"conflict_id": "a", "resolved_source": "qw"}, {"conflict_id": "b", "resolved_source": "costing"}],
        "person@example.com",
    )
    body = next(json for method, url, json in gate.sent if url.endswith("/final-selection"))
    assert body == {
        "resolutions": [
            {"conflict_id": "a", "resolved_source": "qw", "resolved_by": "person@example.com"},
            {"conflict_id": "b", "resolved_source": "costing", "resolved_by": "person@example.com"},
        ]
    }


def test_a_refused_write_reports_the_hitl_detail(gate):
    gate.fake.post_response = gate.Resp(409, {"detail": "conflict already resolved"})
    with pytest.raises(ValueError, match="conflict already resolved"):
        gate.resolve_price_conflicts("RFQ-1", [{"conflict_id": "a", "resolved_source": "qw"}], "person@example.com")


def test_list_page_size_is_clamped_and_cursor_is_passed_only_when_given(gate):
    gate.list_price_conflicts("RFQ-1", limit=10_000)
    gate.list_price_conflicts("RFQ-1", limit=0, cursor="c9")
    params = [p for method, url, p in gate.sent if url.endswith("/final-selection/pending")]
    assert params[0] == {"limit": 500}
    assert params[1] == {"limit": 1, "cursor": "c9"}
