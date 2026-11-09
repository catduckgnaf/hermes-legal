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
    dc = sub.add_parser("doc-compare", help="deterministic paragraph-level DOCX compare")
    dc.add_argument("original"); dc.add_argument("revised"); dc.add_argument("--json", action="store_true")
    dr = sub.add_parser("doc-redline", help="build a DOCX redline with real w:ins / w:del track changes")
    dr.add_argument("original"); dr.add_argument("revised"); dr.add_argument("-o", "--output", required=True)
    bp = sub.add_parser("bates-plan", help="plan Bates labels for a page count (plan only; renders nothing)")
    bp.add_argument("--pages", type=int, required=True); bp.add_argument("--prefix", default="")
    bp.add_argument("--start", type=int, default=1); bp.add_argument("--digits", type=int, default=6)
    rv = sub.add_parser("redact-verify", help="verify phrases are absent from an extracted text file")
    rv.add_argument("text_file"); rv.add_argument("phrases", nargs="+")
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
    if args.cmd == "doc-compare":
        import pathlib
        from .docx_edit import compare_docx
        result = compare_docx(pathlib.Path(args.original).read_bytes(), pathlib.Path(args.revised).read_bytes())
        if args.json:
            print(json.dumps(result.as_dict(), indent=2))
        else:
            for change in result.changed:
                print(f"{change.kind}: {change.old_text!r} -> {change.new_text!r}")
            if result.is_identical:
                print("identical")
        return 0 if result.is_identical else 0
    if args.cmd == "doc-redline":
        import pathlib
        from .docx_edit import build_redline
        out = build_redline(pathlib.Path(args.original).read_bytes(), pathlib.Path(args.revised).read_bytes())
        pathlib.Path(args.output).write_bytes(out)
        print(f"redline written to {args.output} (track changes by hermes-legal (AI - unverified); a human must accept them)")
        return 0
    if args.cmd == "bates-plan":
        from .pdf_tools import BatesConfig, plan_bates_stamps
        stamps = plan_bates_stamps(args.pages, BatesConfig(prefix=args.prefix, start=args.start, digits=args.digits))
        print(json.dumps([s.as_dict() for s in stamps], indent=2))
        print("plan only: no PDF was stamped by this command")
        return 0
    if args.cmd == "redact-verify":
        import pathlib
        from .pdf_tools import DocumentText, verify_redaction
        doc = DocumentText.from_texts([pathlib.Path(args.text_file).read_text()])
        result = verify_redaction(doc, list(args.phrases))
        print(json.dumps(result.as_dict(), indent=2))
        return 0 if result.passed else 1
    if args.cmd == "cite-check":
        from .citations import extract_all
        found = extract_all(args.text)
        print(json.dumps({"citations": found, "status": "resolver lookup is a v1 build item; nothing was asserted by a model"}, indent=2)); return 0
    ap.print_help(); return 0

if __name__ == "__main__":
    sys.exit(main())
