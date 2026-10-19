from gamelokal.translate import Echo, LibreTranslate, mask, translate_safe, unmask


def test_mask_unmask_roundtrip():
    text = "Hello {0}, <b>x</b> %s"
    masked, toks = mask(text)
    assert "{0}" not in masked and len(toks) == 4
    assert unmask(masked, toks) == (text, True)


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
