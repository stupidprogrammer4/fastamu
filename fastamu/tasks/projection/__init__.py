"""Taskiq execution adapters for application projections.

`broker` and `scheduler` are entry points: importing either builds a broker
from settings. Everything an application imports lives in `delivery` (turning
projection classes into tasks and publishing to them) and `repair` (the
optional recovery of recorded failures).
"""
