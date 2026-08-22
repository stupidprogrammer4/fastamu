"""Fastamu's own suite runs on the harness it ships.

Everything — `pg`, `uow`, `clean_db`, `dishka_container`, `anonymous`, the
folder markers — comes from the `fastamu.testing.fixtures` plugin, which is
registered under `pytest11` and so loads by itself. This file exists to prove
that: if the plugin stops working for a project that depends on Fastamu, it
stops working here first.
"""
