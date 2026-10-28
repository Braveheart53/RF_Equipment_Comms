#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Start the SHR Converter: GUI by default, command line with --cli.

===============================================================================
 Title          : SHR Converter - launcher
 Filename       : shr_converter.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Modified       : 2026-10-28
 Language       : Python 3.12 (3.10 or later)
 Requires       : shr_converter_core.py, shr_converter_gui.py, vszh5_writer.py
                  (same folder) and their requirements (environment.yml)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
===============================================================================

USAGE
-----
    python shr_converter.py [files or folders ...]          GUI
    python shr_converter.py --cli [options] files ...       command line
    python shr_converter.py --cli --help                    every option
    python shr_converter.py --selftest [--gui-smoke]        checks

WHY A LAUNCHER
--------------
The conversion runs in worker processes started with the "spawn" method,
which re-runs the TOP LEVEL of the main script in every worker. This file
imports nothing heavy at its top level, so the workers never load Qt (about
50 MB and a second each); the GUI module is imported only in main().

REVISION HISTORY
----------------
0.0.1  2026-10-28  First internal draft.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS (light on purpose - see WHY A LAUNCHER)
# =============================================================================
import sys
from pathlib import Path

__version__ = "0.0.1"

_FOLDER = Path(globals().get("__file__", Path.cwd() / "_")).resolve().parent
if str(_FOLDER) not in sys.path:
    sys.path.insert(0, str(_FOLDER))


# %% ===========================================================================
#    ENTRY POINT
# =============================================================================
def main(argv=None) -> int:
    """Dispatch to the command line, the self-tests or the GUI."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--cli" in args:
        args.remove("--cli")
        import shr_converter_core
        return shr_converter_core.main(args)
    if "--selftest" in args or "--gui-smoke" in args:
        import shr_converter_core
        ok = True
        if "--selftest" in args:
            ok &= shr_converter_core.self_test(workers=2)
        if "--gui-smoke" in args:
            import shr_converter_gui
            ok &= shr_converter_gui.gui_smoke_test(workers=2)
        print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
        return 0 if ok else 1
    import shr_converter_gui
    return shr_converter_gui.launch_gui(args)


if __name__ == "__main__":
    sys.exit(main())
