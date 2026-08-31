"""The catalogue layer: parsing, sentinels, and the arithmetic on top.

These run offline against fixtures. The live endpoints are the demo's whole
point, but a test that needs the internet fails for reasons that have nothing
to do with the code.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
import _openrouter as o  # noqa: E402


def model(**kw) -> dict:
    base = {
        "id": "acme/thing-1",
        "name": "Acme: Thing 1",
        "context_length": 128_000,
        "pricing": {"prompt": "0.000001", "completion": "0.000004"},
        "created": 1_700_000_000,
    }
    base.update(kw)
    return base


class TestPricing:
    def test_per_token_becomes_per_million(self):
        assert o.price_per_million(model()) == pytest.approx(1.0)
        assert o.price_per_million(model(), "completion") == pytest.approx(4.0)

    def test_a_negative_price_is_a_sentinel_not_a_price(self):
        """OpenRouter marks its routers -1 because the cost is decided when
        they pick a model. Multiplying that by a million put
        -$1,000,000 per million in the dashboard, which is how it was found."""
        assert o.price_per_million(model(pricing={"prompt": "-1"})) is None

    def test_missing_or_unparseable_prices_are_unknown(self):
        for bad in ({}, {"prompt": ""}, {"prompt": None}, {"prompt": "free"}):
            assert o.price_per_million(model(pricing=bad)) is None

    def test_zero_is_a_real_price_not_a_missing_one(self):
        """21 models genuinely cost nothing. Treating 0 as absent would drop
        every one of them from the free list."""
        assert o.price_per_million(model(pricing={"prompt": "0"})) == 0
        assert o.is_free(model(pricing={"prompt": "0"})) is True


class TestRouters:
    def test_a_negative_price_marks_a_router(self):
        assert o.is_router(model(pricing={"prompt": "-1", "completion": "-1"})) is True

    def test_an_ordinary_model_is_not_a_router(self):
        assert o.is_router(model()) is False

    def test_unparseable_pricing_does_not_crash_the_check(self):
        assert o.is_router(model(pricing={"prompt": "n/a"})) is False


class TestFormatting:
    @pytest.mark.parametrize(
        "n,expected",
        [(None, "—"), (0, "—"), (512, "512"), (128_000, "128K"), (1_048_576, "1.0M")],
    )
    def test_context_reads_the_way_people_say_it(self, n, expected):
        assert o.fmt_context(n) == expected

    def test_prices_keep_enough_precision_to_be_useful(self):
        """Sub-cent pricing is common and rounding it to two places turns a
        real difference into $0.00 for both."""
        assert o.fmt_price(None) == "—"
        assert o.fmt_price(0) == "free"
        assert o.fmt_price(2.5) == "$2.50"
        assert o.fmt_price(0.0004) == "$0.0004"


class TestVendor:
    def test_vendor_is_the_half_before_the_slash(self):
        assert o.vendor(model(id="openai/gpt-5")) == "openai"

    def test_an_id_with_no_slash_still_yields_something(self):
        assert o.vendor(model(id="solo")) == "solo"
        assert o.vendor(model(id="")) == "unknown"
