"""An enum is a vocabulary two sides have to agree on. `FaStrEnum` keeps the
wire value and the label together so a client never ships its own copy."""

from fastamu.common.bases.schemas import EnumGroupOut, EnumOut
from fastamu.common.enums import FaStrEnum


class Status(FaStrEnum):
    PENDING = ("pending", "در انتظار")
    DONE = ("done", "انجام شد")


class Plain(FaStrEnum):
    SIMPLE = "simple"


def test_a_member_is_still_its_wire_value() -> None:
    assert Status.PENDING == "pending"
    assert str(Status.PENDING) == "pending"


def test_a_member_carries_the_label_beside_the_value() -> None:
    assert Status.PENDING.fa == "در انتظار"


def test_a_bare_member_is_its_own_label() -> None:
    assert Plain.SIMPLE.fa == "simple"


def test_an_enum_serialises_as_value_and_label_pairs() -> None:
    out = EnumOut.of(Status)

    assert [(row.value, row.label) for row in out] == [
        ("pending", "در انتظار"),
        ("done", "انجام شد"),
    ]


def test_several_enums_come_back_each_under_its_own_name() -> None:
    groups = EnumGroupOut.of([Status, Plain])

    assert [group.name for group in groups] == ["Status", "Plain"]
    assert len(groups[0].members) == 2
