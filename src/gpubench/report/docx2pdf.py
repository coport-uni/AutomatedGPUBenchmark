"""Convert ``report.docx`` to PDF with LibreOffice UNO (DevSpec 4.6.1).

``soffice --convert-to`` is not used: LibreOffice's DOCX import ignores
``w:autoSpaceDE`` and ``w:autoSpaceDN``, so Korean text gains a space
before digits (``0 건``). Opening the file over UNO lets this module
turn ``ParaIsCharacterDistance`` off on every paragraph style and
paragraph before the export (LearnedPatterns L1).

``uno`` comes from the distribution package ``python3-uno`` and is only
importable in the runtime image, whose venv sees the system packages.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from pypdf import PdfReader

soffice_names = ("soffice", "libreoffice")
connect_timeout_s = 60
exit_timeout_s = 30
connect_poll_s = 0.25
pdf_filter = "writer_pdf_Export"


class ConversionError(RuntimeError):
    """LibreOffice could not be started or could not export the PDF."""


def soffice_path() -> str | None:
    """Return the LibreOffice executable, or ``None`` when missing."""
    for name in soffice_names:
        found = shutil.which(name)
        if found:
            return found
    return None


def available() -> bool:
    """Return whether LibreOffice and the ``uno`` bridge are installed."""
    return (
        soffice_path() is not None
        and importlib.util.find_spec("uno") is not None
    )


def page_count(pdf: Path) -> int:
    """Return the number of pages of ``pdf``."""
    return len(PdfReader(str(pdf)).pages)


def prop(name: str, value: Any) -> Any:
    """Build a ``com.sun.star.beans.PropertyValue``."""
    from com.sun.star.beans import PropertyValue

    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def connect(pipe: str, process: subprocess.Popen) -> Any:
    """Wait for the office process and return its ``Desktop``."""
    import uno
    from com.sun.star.connection import NoConnectException

    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    deadline = time.monotonic() + connect_timeout_s
    while True:
        try:
            remote = resolver.resolve(
                f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext"
            )
            return remote.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", remote
            )
        except NoConnectException as exc:
            if process.poll() is not None:
                raise ConversionError(
                    f"soffice exited with {process.returncode}"
                ) from exc
            if time.monotonic() > deadline:
                raise ConversionError("soffice did not accept UNO") from exc
            time.sleep(connect_poll_s)


def disable_character_distance(text: Any) -> None:
    """Turn Asian autospace off for every paragraph under ``text``."""
    parts = text.createEnumeration()
    while parts.hasMoreElements():
        part = parts.nextElement()
        if part.supportsService("com.sun.star.text.TextTable"):
            for name in part.CellNames:
                disable_character_distance(part.getCellByName(name))
        elif part.supportsService("com.sun.star.text.Paragraph"):
            part.ParaIsCharacterDistance = False


def disable_autospace(document: Any) -> None:
    """Apply ``ParaIsCharacterDistance = False`` to styles and text."""
    styles = document.StyleFamilies.getByName("ParagraphStyles")
    for name in styles.ElementNames:
        styles.getByName(name).ParaIsCharacterDistance = False
    disable_character_distance(document.Text)
    pages = document.StyleFamilies.getByName("PageStyles")
    for name in pages.ElementNames:
        page = pages.getByName(name)
        if page.FooterIsOn:
            disable_character_distance(page.FooterText)


def convert(docx: Path, pdf: Path) -> Path:
    """Export ``docx`` to ``pdf`` through a private headless office.

    Args:
        docx: Source Word file.
        pdf: Target PDF file; replaced when it exists.

    Returns:
        ``pdf``.

    Raises:
        ConversionError: If LibreOffice is missing, fails to start, or
            fails to export.
    """
    executable = soffice_path()
    if executable is None:
        raise ConversionError("LibreOffice (soffice) is not installed")
    pipe = f"gpubench_{uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="gpubench-office-") as profile:
        process = subprocess.Popen(
            [
                executable,
                "--headless",
                "--invisible",
                "--nologo",
                "--norestore",
                "--nodefault",
                "--nolockcheck",
                f"-env:UserInstallation={Path(profile).as_uri()}",
                f"--accept=pipe,name={pipe};urp;StarOffice.ComponentContext",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            desktop = connect(pipe, process)
            document = desktop.loadComponentFromURL(
                docx.resolve().as_uri(), "_blank", 0, (prop("Hidden", True),)
            )
            if document is None:
                raise ConversionError(f"LibreOffice could not open {docx}")
            try:
                disable_autospace(document)
                document.TextFields.refresh()
                document.storeToURL(
                    pdf.resolve().as_uri(), (prop("FilterName", pdf_filter),)
                )
            finally:
                document.close(True)
            try:
                desktop.terminate()
            except Exception:
                # The bridge drops as soon as the office exits; the
                # process wait below is the real check.
                pass
            process.wait(timeout=exit_timeout_s)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    if not pdf.is_file():
        raise ConversionError(f"LibreOffice did not write {pdf}")
    return pdf
