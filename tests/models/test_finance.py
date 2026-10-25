from decimal import Decimal
from src.models.finance import convert, net_worth, apply_signed_events

def test_convert():
    assert convert("100","60.5") == Decimal("6050.0")

def test_net_worth():
    assert net_worth("100000","15000") == Decimal("85000")

def test_signed_events():
    assert apply_signed_events("1000",["500","-120"]) == Decimal("1380")
