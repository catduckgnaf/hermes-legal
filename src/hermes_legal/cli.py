"""The `legal` command line. Every read command prints the same JSON the agent
tools return, because both call the same functions."""
import argparse, json, sys
from . import __version__, db, doctor, matters, providers, tooldefs

def main(argv=None):
    ap = argparse.ArgumentParser(prog="legal", description="hermes-legal: local-first legal work")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("doctor", help="check every integration, offline")
    sub.add_parser("status", help="matters, documents, deadlines, tools")
    sub.add_parser("demo", help="build the synthetic demo matter")
    sub.add_parser("serve", help="serve the local dashboard").add_argument("--port", type=int, default=8770)
    m = sub.add_parser("matter"); m.add_subparsers(dest="sub").add_parser("list")
    c = sub.add_parser("cite-check"); c.add_argument("text")
    t = sub.add_parser("tools"); t.add_argument("--json", action="store_true")
    p = sub.add_parser("models"); p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "doctor":
        lines, missing = doctor.run()
        print("\n".join(lines)); return 1 if missing and False else 0
    if args.cmd == "tools":
        print(json.dumps([{"name": t.name, "write": t.write, "description": t.description} for t in tooldefs.TOOLS], indent=2)); return 0
    if args.cmd == "models":
        for name, size, hw, lic, role in providers.LOCAL_MODELS:
            print(f"{name:22} {size:10} {hw:42} {lic:24} {role}")
        return 0
    if args.cmd in ("status", "demo") or (args.cmd == "matter"):
        conn = db.connect()
        if args.cmd == "demo":
            import pathlib
            demo = pathlib.Path("demo_matter")
            if list(matters.list_matters(conn)) == [] and demo.is_dir():
                mid = matters.open_folder_as_matter(conn, demo, "Demo — Alvarez (fictional)")
                print(f"demo matter #{mid} created from {demo}")
        for row in matters.list_matters(conn):
            print(row)
        return 0
    if args.cmd == "serve":
        print("Dashboard is a v1 build item; the CLI, plugin and MCP surfaces work today.")
        print(f"Would bind 127.0.0.1:{args.port} only (local access mode).")
        return 0
    if args.cmd == "cite-check":
        from .citations import HISTORY_DISCLAIMER, extract_citations, format_citation, verify_all_gate
        found = extract_citations(args.text)
        gate = verify_all_gate(args.text)
        print(json.dumps({
            "citations": [
                {"raw": c.raw, "normalized": c.normalized, "formatted": format_citation(c),
                 "status": "unverified"}
                for c in found
            ],
            "status": "unverified",
            "note": "Extraction checks nothing: no resolver was run, so every citation above is unverified and nothing was asserted by a model.",
            "history": "history_unknown",
            "history_note": HISTORY_DISCLAIMER,
            "verify_all_gate": {"allowed": gate.allowed, "blocked": list(gate.blocked_citations)},
        }, indent=2)); return 0
    ap.print_help(); return 0

if __name__ == "__main__":
    sys.exit(main())
