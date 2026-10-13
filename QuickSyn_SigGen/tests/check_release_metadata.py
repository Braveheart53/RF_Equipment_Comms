# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Release metadata, licence and About-dialog checks.

Part of the QuickSyn SCPI controller package, version 0.0.9.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Run directly (``python tests/check_release_metadata.py``) or through
``tests/run_all.py``. Needs no instrument; Qt runs on the offscreen platform.

What it checks
--------------
1. The GUI, the export script and vszh5_writer.py carry the SPDX tags, the
   author / company / email / version / licence fields, a 0.0.9 history
   entry, no ``Project`` line and no leftover template placeholders; every
   other Python file in the package (tests, upstream check) carries the SPDX
   tags and the package version.
2. The version is valid Semantic Versioning 2.0.0 and is the same in the
   header, in ``__version__``, in the file name, in the README and in the
   environment file; the GUI runs the export script of the same version.
3. ``LICENSE`` is the unmodified GPL-3.0 text (SHA-256) and contains the three
   notice paragraphs that the program embeds, character for character.
4. ``--version`` prints the identity block for both scripts and exits 0.
5. Neither script calls ``os.process_cpu_count`` (Python 3.13 only), and both
   byte-compile on the running interpreter.
6. The GUI About dialog shows version, author, company, a mailto link for the
   email, the licence and the GPL notice, and Help > About opens it.

Exit status is 0 when every check passes, 1 otherwise.
"""
import ast
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
sys.dont_write_bytecode = True   # keep __pycache__ out of the package tree

# ---------------------------------------------------------------- expectations
VERSION = "0.0.9"
AUTHOR = "William W. Wallace"
COMPANY = "NRAO/GBO"
EMAIL = "wwallace@nrao.edu"
LICENCE_ID = "GPL-3.0-or-later"
GUI = PKG / "quicksyn_scpi_gui_v0_0_9.py"
EXPORT = PKG / "quicksyn_veusz_export_v0_0_9.py"
WRITER = PKG / "vszh5_writer.py"
# SHA-256 of the GPL-3.0 text as distributed by the FSF and packaged in
# /usr/share/common-licenses/GPL-3 (674 lines).
LICENSE_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
# Official regular expression from the Semantic Versioning 2.0.0 specification.
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
PLACEHOLDERS = ("<AUTHOR>", "<ORGANISATION>", "<PROJECT", "<LICENCE>")

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    """Record one check and print it immediately."""
    results.append((bool(ok), name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))


def squash(text: str) -> str:
    """Collapse all whitespace so line wrapping cannot hide a difference."""
    return " ".join(text.split())


# ------------------------------------------------------------ 1. file manifest
print("1. Package manifest")
for rel in (
    "quicksyn_scpi_gui_v0_0_9.py", "quicksyn_veusz_export_v0_0_9.py", "vszh5_writer.py",
    "environment_quicksyn.yml", "README_quicksyn_controller.md", "LICENSE",
    "tests/check_smoke.py", "tests/check_reduction.py", "tests/check_console.py",
    "tests/check_release_metadata.py", "tests/check_vszh5.py", "tests/run_all.py",
    "upstream/veusz-4.2.1-vszh5-load-quit-pdfdpi.patch",
    "upstream/VEUSZ_UPSTREAM_ISSUE.md", "upstream/check_veusz_patch.py",
    "tools/build_readme_pdf.py", "README_quicksyn_controller.pdf", "README_quicksyn_controller.tex",
):
    check((PKG / rel).is_file(), f"present: {rel}")
stale = sorted(p.name for p in PKG.glob("*_v0_0_*.py") if VERSION.replace(".", "_") not in p.name)
check(not stale, "no script of another version in the package", ", ".join(stale))

# --------------------------------------------------- 2. header and dunder checks
print("2. Header fields, SPDX tags and version consistency")
for path in (GUI, EXPORT, WRITER):
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    doc = ast.get_docstring(tree, clean=False) or ""
    tag = path.name

    check(lines[2].startswith("# SPDX-License-Identifier: " + LICENCE_ID),
          f"{tag}: SPDX licence tag", lines[2])
    check(f"{AUTHOR} <{EMAIL}>" in lines[3] and "SPDX-FileCopyrightText" in lines[3],
          f"{tag}: SPDX copyright tag", lines[3])

    def field(label: str) -> str:
        """Return the value of ' Label   : value' in the header block."""
        m = re.search(rf"^ {label}\s*:\s*(.+)$", doc, re.MULTILINE)
        return m.group(1).strip() if m else ""

    check(field("Author") == AUTHOR, f"{tag}: header Author", field("Author"))
    check(field("Company") == COMPANY, f"{tag}: header Company", field("Company"))
    check(field("Email") == EMAIL, f"{tag}: header Email", field("Email"))
    check(field("Licence").startswith(LICENCE_ID), f"{tag}: header Licence",
          field("Licence"))
    check(field("Version").startswith(VERSION), f"{tag}: header Version",
          field("Version"))
    check(field("Filename") == path.name, f"{tag}: header Filename matches file",
          field("Filename"))
    check(not re.search(r"^ Project\s*:", doc, re.MULTILINE),
          f"{tag}: no Project line (user: no associated project)")
    check(not any(p in src for p in PLACEHOLDERS),
          f"{tag}: no template placeholders left")
    check("GNU General Public License" in doc
          and "either version 3 of the License, or" in doc,
          f"{tag}: GPL notice in header")
    check(re.search(rf"^{re.escape(VERSION)}\s+\d{{4}}-\d{{2}}-\d{{2}}\s", doc, re.MULTILINE) is not None,
          f"{tag}: revision history has a {VERSION} entry")

    dunders = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id.startswith("__"):
                try:
                    dunders[t.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    check(dunders.get("__version__") == VERSION, f"{tag}: __version__",
          str(dunders.get("__version__")))
    check(bool(SEMVER_RE.match(str(dunders.get("__version__", "")))),
          f"{tag}: __version__ is valid SemVer 2.0.0")
    check(dunders.get("__author__") == AUTHOR, f"{tag}: __author__")
    check(dunders.get("__email__") == EMAIL, f"{tag}: __email__")
    check(dunders.get("__company__") == COMPANY, f"{tag}: __company__")
    check(dunders.get("__license__") == LICENCE_ID, f"{tag}: __license__")
    if path is not WRITER:   # an importable module keeps a fixed name
        check(VERSION.replace(".", "_") in path.name, f"{tag}: file name carries version")

check(EXPORT.name in GUI.read_text(encoding="utf-8"),
      "GUI header names the matching export script")
check(GUI.name in EXPORT.read_text(encoding="utf-8"),
      "export header names the matching GUI script")
gui_tree = ast.parse(GUI.read_text(encoding="utf-8"))
companion = next((ast.literal_eval(n.value) for n in gui_tree.body
                  if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "COMPANION_EXPORT_SCRIPT"),
                 None)
check(companion == EXPORT.name, "GUI runs the export script of the same version", str(companion))

# Every other Python file: SPDX tags and the package version in its docstring.
for path in sorted(list((PKG / "tests").glob("*.py")) + list((PKG / "upstream").glob("*.py"))
                   + list((PKG / "tools").glob("*.py"))):
    head = path.read_text(encoding="utf-8").splitlines()[:8]
    check(any(ln.startswith("# SPDX-License-Identifier: " + LICENCE_ID) for ln in head)
          and any("SPDX-FileCopyrightText" in ln and EMAIL in ln for ln in head),
          f"{path.parent.name}/{path.name}: SPDX tags")
    check(f"package, version {VERSION}." in path.read_text(encoding="utf-8"),
          f"{path.parent.name}/{path.name}: states package version {VERSION}")

readme = (PKG / "README_quicksyn_controller.md").read_text(encoding="utf-8")
envtxt = (PKG / "environment_quicksyn.yml").read_text(encoding="utf-8")
before_history = readme.split("## 11.")[0]
stale_names = sorted(set(re.findall(r"_v0_0_\d+\.py", before_history)) - {f"_v{VERSION.replace('.', '_')}.py"})
readme_pdf = PKG / "README_quicksyn_controller.pdf"
try:
    from pypdf import PdfReader
    _r = PdfReader(str(readme_pdf))
    check(len(_r.outline) > 10 and _r.page_mode == "/UseOutlines",
          "README PDF has a bookmark hierarchy and opens the outline pane",
          f"{len(_r.pages)} pages")
    check(readme_pdf.stat().st_mtime >= (PKG / "README_quicksyn_controller.md").stat().st_mtime - 1,
          "README PDF is not older than the README")
except ImportError:
    print("  [SKIP] README PDF bookmarks  - pypdf is not installed")
check(f"**Version {VERSION}**" in readme and not stale_names,
      f"README states {VERSION} and names no other version's scripts before the history",
      ", ".join(stale_names))
check(all(s in readme for s in (AUTHOR, COMPANY, EMAIL, LICENCE_ID)),
      "README carries author, company, email and licence")
check(VERSION in envtxt and EMAIL in envtxt, "environment file carries version and email")

# ------------------------------------------------------------ 3. LICENSE text
print("3. LICENSE")
lic_bytes = (PKG / "LICENSE").read_bytes()
lic = lic_bytes.decode("utf-8")
check(hashlib.sha256(lic_bytes).hexdigest() == LICENSE_SHA256,
      "LICENSE SHA-256 matches the reference GPL-3.0 text")
check("GNU GENERAL PUBLIC LICENSE" in lic and "Version 3, 29 June 2007" in lic,
      "LICENSE identifies GPL version 3")
import quicksyn_scpi_gui_v0_0_9 as app  # noqa: E402  (after sys.path setup)

flat_lic = squash(lic)
for i, para in enumerate(app.GPL_NOTICE_PARAGRAPHS, 1):
    check(squash(para) in flat_lic, f"embedded GPL notice paragraph {i} is verbatim in LICENSE")

# ----------------------------------------------------------- 4. --version flag
print("4. --version")
for path in (GUI, EXPORT):
    proc = subprocess.run(
        [sys.executable, "-I", "-B", str(path), "--version"],
        capture_output=True, text=True, timeout=60,
    )
    out = proc.stdout
    ok = (proc.returncode == 0 and VERSION in out and EMAIL in out
          and COMPANY in out and LICENCE_ID in out and AUTHOR in out)
    check(ok, f"{path.name} --version", f"exit {proc.returncode}; {len(out.splitlines())} lines")

# --------------------------------------------- 5. interpreter compatibility
print(f"5. Interpreter compatibility (running {sys.version.split()[0]})")
for path in (GUI, EXPORT, WRITER, *sorted((PKG / "tests").glob("*.py")),
             *sorted((PKG / "upstream").glob("*.py")), *sorted((PKG / "tools").glob("*.py"))):
    # The built-in compile() checks syntax for the running interpreter and,
    # unlike py_compile, writes nothing to disk (no __pycache__ in the package).
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        compiled = True
    except SyntaxError as exc:
        compiled = False
        print(exc)
    check(compiled, f"{path.name} byte-compiles")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and n.attr == "process_cpu_count"]
    check(not offenders, f"{path.name}: no os.process_cpu_count (3.13-only) use",
          f"lines {offenders}" if offenders else "")

# ------------------------------------------------------- 6. About dialog (Qt)
print("6. About dialog")
from Qt import QtCore, QtWidgets  # noqa: E402  (Qt.py abstraction layer)

qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
content = app.build_about_content()
check(set(content) == {"text", "notice", "runtime"}, "build_about_content keys")
for needle, label in (
    (app.APP_NAME, "program name"), (VERSION, "version"), (AUTHOR, "author"),
    (COMPANY, "company"), (LICENCE_ID, "licence id"),
    ("GNU General Public License v3.0 or later", "licence name"),
    (app.__copyright__, "copyright"),
    (f"mailto:{EMAIL}", "mailto link"),
):
    check(needle in content["text"], f"About text contains {label}")
# Paragraph breaks become spaces; inline tags (the licence <a> link) are
# removed without a replacement so that "<https://...>" is reconstructed
# exactly rather than gaining spaces around the URL.
plain_notice = re.sub(r"<br\s*/?>", " ", content["notice"])
plain_notice = re.sub(r"<[^>]+>", "", plain_notice)
plain_notice = squash(plain_notice.replace("&lt;", "<").replace("&gt;", ">"))
for i, para in enumerate(app.GPL_NOTICE_PARAGRAPHS, 1):
    check(squash(para) in plain_notice, f"About notice contains GPL paragraph {i}")
check("href='https://www.gnu.org/licenses/'" in content["notice"], "licence URL is a link")
check(sys.version.split()[0] in content["runtime"]
      and EMAIL in content["runtime"] and VERSION in content["runtime"],
      "details pane has Python version, email and release version")

theme = app.ThemeManager(qapp)
win = app.MainWindow(theme)
win.show(); qapp.processEvents()
box = win._build_about_box()
check(box.windowTitle() == f"About {app.APP_NAME}", "dialog title", box.windowTitle())
check(box.text() == content["text"] and box.informativeText() == content["notice"]
      and box.detailedText() == content["runtime"], "dialog widgets hold the content")
check(box.textFormat() == QtCore.Qt.TextFormat.RichText, "rich text enabled (links render)")

# Help > About must exist and must open this dialog. exec() is replaced with a
# recorder so the check never blocks on a modal event loop.
help_actions = [a for m in win.menuBar().findChildren(QtWidgets.QMenu)
                if m.title().replace("&", "") == "Help" for a in m.actions()]
about = [a for a in help_actions if a.text().replace("&", "") == "About"]
check(len(about) == 1, "Help > About menu entry exists")
seen_boxes = []
orig_exec = QtWidgets.QMessageBox.exec
QtWidgets.QMessageBox.exec = lambda self: seen_boxes.append(self.text()) or 0
try:
    about[0].trigger(); qapp.processEvents()
finally:
    QtWidgets.QMessageBox.exec = orig_exec
check(len(seen_boxes) == 1 and AUTHOR in seen_boxes[0] and EMAIL in seen_boxes[0],
      "triggering Help > About opens a dialog with author and email")

# Render the real dialog once to prove it lays out; keep the PNG for review.
box.show(); qapp.processEvents()
pix = box.grab()
png = Path(tempfile.gettempdir()) / "quicksyn_about_dialog.png"
check((not pix.isNull()) and pix.width() > 300 and pix.height() > 150 and pix.save(str(png)),
      "dialog renders", f"{pix.width()}x{pix.height()} px -> {png}")
box.close(); win.close(); qapp.processEvents()

# ------------------------------------------------------------------- summary
failed = [r for r in results if not r[0]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("FAILED:")
    for _, name, detail in failed:
        print(f"  - {name} {detail}")
    sys.exit(1)
print("ALL RELEASE CHECKS PASSED")
