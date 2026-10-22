import pytest

from shopnotify.templating import (MissingValueError, find_tags, render)

TEMPLATE = "Hi {{name}}, your order {{order_id}} is ready. Total: {{amount}}."
VALUES = {"name": "Sara", "order_id": "1042", "amount": "250000"}


def test_renders_all_tags():
    assert render(TEMPLATE, VALUES) == (
        "Hi Sara, your order 1042 is ready. Total: 250000.")


def test_tags_tolerate_whitespace_and_repeat():
    assert render("{{ name }} / {{name}}", {"name": "Sara"}) == "Sara / Sara"


def test_non_string_values_are_stringified():
    assert render("Total: {{amount}}", {"amount": 250000}) == "Total: 250000"


def test_unused_values_are_ignored():
    assert render("Hi {{name}}", {"name": "Sara", "extra": "x"}) == "Hi Sara"


def test_defaults_fill_optional_tags_but_values_win():
    template = "Hi {{name}} from {{shop}}"
    assert render(template, {"name": "Sara"},
                  defaults={"shop": "our shop"}) == "Hi Sara from our shop"
    assert render(template, {"name": "Sara", "shop": "HQ"},
                  defaults={"shop": "our shop"}) == "Hi Sara from HQ"


def test_missing_tag_raises_and_names_it():
    with pytest.raises(MissingValueError) as excinfo:
        render(TEMPLATE, {"name": "Sara", "order_id": "1042"})
    assert excinfo.value.missing == ["amount"]
    assert "amount" in str(excinfo.value)


def test_all_missing_tags_are_reported_sorted():
    with pytest.raises(MissingValueError) as excinfo:
        render(TEMPLATE, {})
    assert excinfo.value.missing == ["amount", "name", "order_id"]


def test_empty_string_counts_as_missing():
    with pytest.raises(MissingValueError):
        render("Hi {{name}}", {"name": "  ".strip()})


def test_find_tags_in_order_without_duplicates():
    assert find_tags(TEMPLATE) == ["name", "order_id", "amount"]
    assert find_tags("{{b}} {{a}} {{b}}") == ["b", "a"]
    assert find_tags("no tags here") == []
