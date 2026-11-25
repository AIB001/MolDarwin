#!/usr/bin/env python3
"""MolCat MCP server — entry point.

Exposes MolCat's screening, auditing and reporting capabilities as MCP tools
an agent can call.  The tools, their grouping and the two properties that make
this surface safe to drive from a loop are documented in
:mod:`molcat.mcp`; read ``molcat://overview`` before the first call in a
session.

Usage::

    # Browser-based debug UI
    mcp dev src/molcat/mcp_server.py

    # Register with Claude Code (installed package)
    claude mcp add --transport stdio molcat -- python -m molcat.mcp_server

    # Register with Claude Code (editable checkout, explicit interpreter)
    claude mcp add --transport stdio molcat -- \\
        /path/to/env/bin/python -m molcat.mcp_server

Name the interpreter explicitly.  MolCat's backends live in the environment
it was installed into, and a bare ``python`` resolves to whatever is first on the
client's PATH -- which is how a server comes up reporting every backend
unavailable.

stdout belongs to JSON-RPC under this transport.  Every tool redirects library
output to stderr before calling anything, so progress and warnings remain visible
in the server log without corrupting the protocol.
"""

from __future__ import annotations


def main() -> None:
    from molcat.mcp import mcp

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
