from shopnotify.customers import (dedupe_customers, load_customers,
                                  normalise_phone)
from shopnotify.models import Customer

HEADER = "name,phone,telegram_chat_id,channel,order_id,amount,item\n"


def write_csv(tmp_path, body: str):
    path = tmp_path / "customers.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_normalise_phone_variants():
    assert normalise_phone("+98 912 345 6789") == "+989123456789"
    assert normalise_phone("0098-912-345-6789") == "+989123456789"
    assert normalise_phone("(0912) 555 0134", "98") == "+989125550134"
    assert normalise_phone("0912 555 0134") == "09125550134"
    assert normalise_phone("") == ""


def test_load_customers_normalises_and_keeps_extra_columns(tmp_path):
    path = write_csv(tmp_path,
                     "Sara Ahmadi,+98 912 345 6789,512345678,Telegram,"
                     "1042,250000,Running shoes\n")
    (customer,) = load_customers(path)
    assert customer.name == "Sara Ahmadi"
    assert customer.phone == "+989123456789"
    assert customer.telegram_chat_id == "512345678"
    assert customer.channel == "telegram"  # case-insensitive in the CSV
    assert customer.order_id == "1042"
    assert customer.fields["item"] == "Running shoes"
    assert customer.destination == "512345678"


def test_channel_defaults_from_what_is_present(tmp_path):
    path = write_csv(
        tmp_path,
        "Omid Rahimi,0912 555 0134,,,1043,189000,Backpack\n"
        "Neda Karimi,,998877665,,1046,320000,Headphones\n")
    omid, neda = load_customers(path)
    assert omid.channel == "whatsapp"  # has a phone, no telegram id
    assert omid.destination == "09125550134"
    assert neda.channel == "telegram"  # has a telegram id, no phone
    assert neda.destination == "998877665"


def test_country_code_applied_while_loading(tmp_path):
    path = write_csv(tmp_path,
                     "Omid Rahimi,0912 555 0134,,whatsapp,1043,189000,X\n")
    (customer,) = load_customers(path, default_country_code="98")
    assert customer.phone == "+989125550134"


def make_customer(channel: str, destination: str, name: str = "X"):
    customer = Customer(name=name, channel=channel)
    if channel == "telegram":
        customer.telegram_chat_id = destination
    else:
        customer.phone = destination
    return customer


def test_dedupe_keeps_first_and_reports_rest():
    rows = [make_customer("telegram", "111", "First"),
            make_customer("telegram", "111", "Second"),
            make_customer("whatsapp", "+100", "Other")]
    unique, duplicates = dedupe_customers(rows)
    assert [c.name for c in unique] == ["First", "Other"]
    assert [c.name for c in duplicates] == ["Second"]


def test_dedupe_is_per_channel_not_global():
    rows = [make_customer("telegram", "111"), make_customer("whatsapp", "111")]
    unique, duplicates = dedupe_customers(rows)
    assert len(unique) == 2 and duplicates == []


def test_dedupe_never_merges_undeliverable_rows():
    rows = [make_customer("telegram", ""), make_customer("telegram", "")]
    unique, duplicates = dedupe_customers(rows)
    assert len(unique) == 2 and duplicates == []
