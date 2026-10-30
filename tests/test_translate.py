from gamelokal.translate import Echo, LibreTranslate, mask, translate_safe, unmask


def test_mask_unmask_roundtrip():
    text = "Hello {0}, <b>x</b> %s"
    masked, toks = mask(text)
    assert "{0}" not in masked and len(toks) == 4
    assert unmask(masked, toks) == (text, True)


def test_real_newline_is_protected():
    masked, toks = mask("Line1\nLine2")
    assert "\n" not in masked and unmask(masked, toks) == ("Line1\nLine2", True)


def test_unmask_tolerates_spacing_and_detects_loss():
    _, toks = mask("A {0} B <i>")
    assert unmask("A \u27e6 0 \u27e7 B \u27e61\u27e7", toks)[1] is True
    assert unmask("A B", toks)[1] is False


def test_translate_safe_with_echo():
    out = translate_safe(Echo(), ["Hi {0}", "Plain"], "en", "id")
    assert out == [("Hi {0}", True), ("Plain", True)]


def test_libre_uses_translated_text(monkeypatch):
    lt = LibreTranslate()
    monkeypatch.setattr(lt, "_post", lambda payload: {"translatedText": payload["q"].upper()})
    assert lt.translate(["abc", ""], "en", "id") == ["ABC", ""]


def test_unmask_rejects_duplicate_missing_and_foreign_tokens():
    _, toks = mask("A {0} B <i>")
    assert unmask("\u27e60\u27e7 \u27e60\u27e7 \u27e61\u27e7", toks)[1] is False   # ganda
    assert unmask("\u27e60\u27e7", toks)[1] is False                                  # hilang
    assert unmask("\u27e60\u27e7 \u27e61\u27e7 \u27e65\u27e7", toks)[1] is False      # asing


def test_text_with_only_tags_is_not_sent_to_provider():
    class Boom:
        def translate(self, *a):
            raise AssertionError("tidak boleh dipanggil")

    assert translate_safe(Boom(), ["{0}", "<b></b>"], "en", "id") == [("{0}", True), ("<b></b>", True)]
