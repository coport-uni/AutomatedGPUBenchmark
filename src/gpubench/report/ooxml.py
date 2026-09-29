"""Validate a .docx package against the ECMA-376 Transitional schemas.

The schemas are the XML Schema files of ECMA-376 5th edition Part 4
(Transitional) plus the W3C ``xml.xsd``; the runtime image downloads
them at build time (see Dockerfile). Content that Markup Compatibility
(ECMA-376 Part 3) lets a consumer ignore, such as the Word 2010
extensions python-docx's template declares in ``mc:Ignorable``, is
removed before validation, because it is outside the schemas by design.
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from lxml import etree

schema_dir_env = "GPUBENCH_OOXML_SCHEMAS"
default_schema_dir = Path("/opt/ooxml-schemas")
mc_ns = "http://schemas.openxmlformats.org/markup-compatibility/2006"
xml_ns = "http://www.w3.org/XML/1998/namespace"
wml_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
# Parts of a WordprocessingML package whose root is in the wml schema.
validated_prefix = "word/"
skipped_parts = ("word/theme/",)


@dataclass(frozen=True)
class Problem:
    """One schema violation."""

    part: str
    line: int
    message: str

    def __str__(self) -> str:
        """Return ``part:line: message``."""
        return f"{self.part}:{self.line}: {self.message}"


def schema_dir() -> Path:
    """Return the directory holding ``wml.xsd`` and ``xml.xsd``."""
    return Path(os.environ.get(schema_dir_env, default_schema_dir))


def schemas_available() -> bool:
    """Return whether the schema files are installed."""
    directory = schema_dir()
    return (directory / "wml.xsd").is_file() and (
        directory / "xml.xsd"
    ).is_file()


@cache
def load_schema(directory: Path) -> etree.XMLSchema:
    """Compile the wml schema with the xml namespace loaded first.

    The ECMA files import the xml namespace without a location, so a
    small driver schema imports ``xml.xsd`` before ``wml.xsd``.
    """
    directory = directory.resolve()
    driver = (
        '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        f'<xsd:import namespace="{xml_ns}" '
        f'schemaLocation="{(directory / "xml.xsd").as_uri()}"/>'
        f'<xsd:import namespace="{wml_ns}" '
        f'schemaLocation="{(directory / "wml.xsd").as_uri()}"/>'
        "</xsd:schema>"
    )
    root = etree.fromstring(driver.encode(), base_url=directory.as_uri() + "/")
    return etree.XMLSchema(root)


def strip_ignorable(root: etree._Element) -> etree._Element:
    """Remove markup a consumer may ignore under Markup Compatibility.

    ``mc:AlternateContent`` is replaced by its ``mc:Fallback`` children,
    elements and attributes in namespaces listed by ``mc:Ignorable`` are
    removed, and so are the ``mc`` attributes themselves.
    """
    ignorable = set()
    for element in root.iter():
        listed = element.get(f"{{{mc_ns}}}Ignorable")
        if listed:
            for prefix in listed.split():
                if prefix in element.nsmap:
                    ignorable.add(element.nsmap[prefix])
    for alternate in list(root.iter(f"{{{mc_ns}}}AlternateContent")):
        parent = alternate.getparent()
        position = parent.index(alternate)
        fallback = alternate.find(f"{{{mc_ns}}}Fallback")
        replacement = list(fallback) if fallback is not None else []
        parent.remove(alternate)
        for offset, child in enumerate(replacement):
            parent.insert(position + offset, child)
    for element in list(root.iter()):
        if not isinstance(element.tag, str):
            continue
        namespace = etree.QName(element).namespace
        if namespace in ignorable and element.getparent() is not None:
            element.getparent().remove(element)
            continue
        for name in list(element.attrib):
            attr_ns = etree.QName(name).namespace
            if attr_ns == mc_ns or attr_ns in ignorable:
                del element.attrib[name]
    return root


def validate_docx(path: Path, directory: Path | None = None) -> list[Problem]:
    """Validate every WordprocessingML part of the package at ``path``.

    Returns:
        The violations found; an empty list means the package is valid.
    """
    schema = load_schema(directory or schema_dir())
    problems: list[Problem] = []
    with zipfile.ZipFile(path) as package:
        for part in sorted(package.namelist()):
            if not part.startswith(validated_prefix):
                continue
            if not part.endswith(".xml") or part.startswith(skipped_parts):
                continue
            root = strip_ignorable(etree.fromstring(package.read(part)))
            if etree.QName(root).namespace != wml_ns:
                continue
            if not schema.validate(root):
                problems.extend(
                    Problem(part, error.line, error.message)
                    for error in schema.error_log
                )
    return problems
