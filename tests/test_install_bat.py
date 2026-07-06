"""Regression tests for the root Windows batch installer."""

from pathlib import Path


_INSTALL_BAT = Path(__file__).resolve().parents[1] / "install.bat"


def test_install_bat_downloads_use_basic_parsing_and_stop_on_errors():
    """Windows PowerShell 5.1 can prompt without -UseBasicParsing.

    That prompt blocks non-technical users during first-run setup and was
    reported in issue #27 while downloading the Tcl/Tk MSI.
    """
    source = _INSTALL_BAT.read_text(encoding="utf-8")
    download_lines = [
        line.strip()
        for line in source.splitlines()
        if "Invoke-WebRequest" in line and "-OutFile" in line
    ]

    assert download_lines, "expected install.bat to contain download commands"
    for line in download_lines:
        assert "-UseBasicParsing" in line, line
        assert "-ErrorAction Stop" in line, line
