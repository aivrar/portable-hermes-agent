"""Fonts must be DPI-scaled exactly once (gui/theme.py).

Tk converts font point sizes to pixels with ``tk scaling``; in a DPI-aware
process that already includes the display DPI.  These tests fake the Tk root
and the Win32 DPI calls, so they need neither a display nor the Hermes core.
"""
from types import SimpleNamespace

import pytest

from gui import theme

TK_SCALING_96DPI = 96.0 / 72.0  # 1.3333 px/pt
TK_SCALING_175 = 2.3316121629374638  # measured on a 175% (168 dpi) display


class FakeRoot:
    def __init__(self, tk_scaling, fpixels_inch=None):
        self._tk_scaling = tk_scaling
        self._fpixels_inch = (
            fpixels_inch if fpixels_inch is not None
            else (tk_scaling if not isinstance(tk_scaling, Exception) else TK_SCALING_96DPI) * 72.0
        )
        self.tk = SimpleNamespace(call=self._call)

    def _call(self, *args):
        assert args == ("tk", "scaling")
        if isinstance(self._tk_scaling, Exception):
            raise self._tk_scaling
        return self._tk_scaling

    def winfo_id(self):
        return 1234

    def winfo_fpixels(self, value):
        assert value == "1i"
        return self._fpixels_inch


def _fake_ctypes(window_dpi):
    user32 = SimpleNamespace(
        GetParent=lambda hwnd: hwnd + 1,
        GetDpiForWindow=lambda hwnd: window_dpi,
    )
    return SimpleNamespace(windll=SimpleNamespace(user32=user32))


@pytest.fixture(autouse=True)
def _restore_theme_state(monkeypatch):
    monkeypatch.setattr(theme, "_DPI_SCALE", theme._DPI_SCALE)
    monkeypatch.setattr(theme, "_TK_FONT_SCALE",
                        getattr(theme, "_TK_FONT_SCALE", 1.0), raising=False)
    saved_fonts = dict(theme.FONTS)
    yield
    theme.FONTS.clear()
    theme.FONTS.update(saved_fonts)


def test_dpi_aware_tk_at_175_percent_keeps_point_sizes(monkeypatch):
    """Owner's display: Tk already scales points, so 10pt must stay 10pt."""
    monkeypatch.setattr(theme, "ctypes", _fake_ctypes(168))

    theme.init_dpi_scaling(FakeRoot(TK_SCALING_175))

    assert theme._DPI_SCALE == pytest.approx(1.75)
    assert theme.F(10) == 10
    assert theme.F(24) == 24
    assert theme.SF("Segoe UI", 8, "underline") == ("Segoe UI", 8, "underline")
    assert theme.FONTS["body"] == ("Segoe UI", 10)
    assert theme.FONTS["logo"] == ("Segoe UI", 24, "bold")
    # Pixel geometry is still scaled by the DPI factor.
    assert theme.S(100) == 175


def test_withdrawn_root_fallback_uses_tk_inch_and_keeps_point_sizes(monkeypatch):
    """GetDpiForWindow returns 0 for a withdrawn root; fallback is 1i in pixels."""
    monkeypatch.setattr(theme, "ctypes", _fake_ctypes(0))

    theme.init_dpi_scaling(FakeRoot(TK_SCALING_175))

    assert theme._DPI_SCALE == pytest.approx(167.876 / 96.0, rel=1e-4)
    assert theme.S(100) == 174
    assert theme.F(9) == 9
    assert theme.F(10) == 10
    assert theme.FONTS["heading"] == ("Segoe UI", 13, "bold")


def test_tk_at_96_dpi_on_150_percent_display_scales_fonts(monkeypatch):
    """If Tk does not scale for DPI itself, F() must still enlarge points."""
    monkeypatch.setattr(theme, "ctypes", _fake_ctypes(144))

    theme.init_dpi_scaling(FakeRoot(TK_SCALING_96DPI))

    assert theme._DPI_SCALE == pytest.approx(1.5)
    assert theme.F(10) == 15
    assert theme.SF("Segoe UI", 10, "bold") == ("Segoe UI", 15, "bold")
    assert theme.FONTS["body"] == ("Segoe UI", 15)


def test_unreadable_tk_scaling_falls_back_to_dpi_scale(monkeypatch):
    monkeypatch.setattr(theme, "ctypes", _fake_ctypes(144))

    theme.init_dpi_scaling(FakeRoot(RuntimeError("no tk scaling")))

    assert theme._TK_FONT_SCALE == 1.0
    assert theme.F(10) == 15


def test_plain_96_dpi_display_is_unchanged(monkeypatch):
    monkeypatch.setattr(theme, "ctypes", _fake_ctypes(96))

    theme.init_dpi_scaling(FakeRoot(TK_SCALING_96DPI))

    assert theme.F(10) == 10
    assert theme.S(100) == 100
    assert theme.FONTS["small"] == ("Segoe UI", 9)
