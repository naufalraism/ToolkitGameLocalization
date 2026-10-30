from gamelokal.core.glossary import Term
from gamelokal.qa.checks import check_consistency, check_entry


def codes(issues):
    return {i.code for i in issues}


def test_placeholder_ok_and_broken():
    src = "Hello {0}, <color=#fff>x</color>"
    assert check_entry("1", src, "Halo {0}, <color=#fff>x</color>") == []
    bad = check_entry("1", src, "Halo, <color=#fff>x")
    assert {"placeholder", "urutan_tag"} <= codes(bad) and all(i.severity == "error" for i in bad)


def test_leftover_mask_token_is_error():
    assert "sisa_penanda" in codes(check_entry("1", "Hi {0}", "Halo {0} \u27e61\u27e7"))


def test_tag_order_wrong():
    assert "urutan_tag" in codes(check_entry("1", "<b>x</b>", "</b>x<b>"))


def test_empty_target_is_skipped():
    assert check_entry("1", "Hello {0}", "") == []


def test_glossary_warning():
    gl = [Term("Echo", "Echo")]
    assert "glosarium" in codes(check_entry("1", "Use an Echo", "Pakai gema", gl))
    assert check_entry("1", "Use an Echo", "Pakai Echo", gl) == []


def test_identical_to_source_and_length():
    assert "sama_dengan_sumber" in codes(check_entry("1", "Hello there", "Hello there"))
    assert "panjang" in codes(check_entry("1", "Hi", "x" * 60))


def test_consistency():
    rows = [("1", "Hello", "Halo"), ("2", "Hello", "Halo"), ("3", "Hello", "Hai")]
    assert [(i.id, i.code) for i in check_consistency(rows)] == [("3", "tidak_konsisten")]
