"""Provider contract check (spec 110).

Sends the boundary values of every provider rule of `contract/*.json`.
"""

from __future__ import annotations

import pytest

from scripts.contract_pytest import Base, Case, Send, check_case, contract_cases


@pytest.mark.parametrize("case", contract_cases(), ids=str)
def test_contract(case: Case, contract_send: Send, contract_base: Base) -> None:
    check_case(case, contract_send, contract_base)
