"""Supported precious metals; add an entry here to offer another metal."""


from decimal import Decimal

from src.models.portfolio.precious_metal import PreciousMetal

GOLD = PreciousMetal("gold", "XAU", (("24K", Decimal(1)), ("22K", Decimal(22) / Decimal(24))))
PRECIOUS_METALS = {metal.name: metal for metal in (GOLD,)}
