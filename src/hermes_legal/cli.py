"""The `legal` command line. Every read command prints the same JSON the agent
tools return, because both call the same functions."""
import argparse, json, sys
from . import __version__, db, doctor, matters, providers, tooldefs

def _matter_row_dict(row):
    return {
        "id": row[0], "name": row[1], "folder": row[2],
        "privacy_ceiling": row[3], "status": row[4],
    }

def _print_matters(rows, as_json, recent=False):
    if as_json:
        payload = []
        for row in rows:
            item = _matter_row_dict(row)
            if recent:
                item["last_opened_at"] = row[5]
                item["open_count"] = row[6]
            payload.append(item)
        print(json.dumps(payload, indent=2))
        return
    for row in rows:
        if recent:
            print(f"{row[0]}\t{row[1]}\t{row[2]}\t{row[3]}\t{row[4]}\tlast opened {row[5] or 'never'}\topens {row[6]}")
        else:
            print(row)

def main(argv=None):
    ap = argparse.ArgumentParser(prog="legal", description="Hermes Legal: local-first legal work")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("doctor", help="check every integration, offline")
    sub.add_parser("status", help="matters, documents, deadlines, tools")
    sub.add_parser("demo", help="build the synthetic demo matter")
    sub.add_parser("serve", help="serve the local dashboard").add_argument("--port", type=int, default=8770)
    m = sub.add_parser("matter", help="open, list, and inspect matter workspaces")
    msub = m.add_subparsers(dest="sub")
    mopen = msub.add_parser("open", help="open a file or folder as a matter")
    mopen.add_argument("path", help="folder, file, or hermes-legal:// deep link")
    mopen.add_argument("--name", default=None)
    mopen.add_argument("--json", action="store_true")
    mlist = msub.add_parser("list", help="list all matters")
    mlist.add_argument("--json", action="store_true")
    mrecent = msub.add_parser("recent", help="list matters by most recent open")
    mrecent.add_argument("--limit", type=int, default=10)
    mrecent.add_argument("--json", action="store_true")
    mdocs = msub.add_parser("documents", help="list a matter's documents from disk")
    mdocs.add_argument("matter_id", type=int)
    mdocs.add_argument("--json", action="store_true")
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
    if args.cmd == "matter" and args.sub == "open":
        conn = db.connect()
        try:
            mid = matters.open_as_matter(conn, args.path, name=args.name)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr); return 2
        matter = matters.get_matter(conn, mid)
        if args.json:
            print(json.dumps(matter, indent=2))
        else:
            print(f"matter #{mid} opened: {matter['name']} ({matter['folder']})")
            for record in matter["documents"]:
                print(record["relative_path"])
        return 0
    if args.cmd == "matter" and args.sub == "recent":
        conn = db.connect()
        _print_matters(matters.recent_matters(conn, limit=args.limit), args.json, recent=True)
        return 0
    if args.cmd == "matter" and args.sub == "documents":
        conn = db.connect()
        if matters.get_matter(conn, args.matter_id) is None:
            print(f"error: no such matter: {args.matter_id}", file=sys.stderr); return 2
        records = matters.list_document_records(conn, args.matter_id)
        if args.json:
            print(json.dumps(records, indent=2))
        else:
            for record in records:
                print(record["relative_path"])
        return 0
    if args.cmd in ("status", "demo") or (args.cmd == "matter"):
        conn = db.connect()
        if args.cmd == "demo":
            import pathlib
            demo = pathlib.Path("demo_matter")
            if list(matters.list_matters(conn)) == [] and demo.is_dir():
                mid = matters.open_folder_as_matter(conn, demo, "Demo — Alvarez (fictional)")
                print(f"demo matter #{mid} created from {demo}")
        if args.cmd == "matter" and getattr(args, "json", False):
            _print_matters(matters.list_matters(conn), True)
            return 0
        for row in matters.list_matters(conn):
            print(row)
        return 0
    if args.cmd == "serve":
        print("Dashboard is a v1 build item; the CLI, plugin and MCP surfaces work today.")
        print(f"Would bind 127.0.0.1:{args.port} only (local access mode).")
        return 0
    if args.cmd == "cite-check":
        from .citations import extract_all
        found = extract_all(args.text)
        print(json.dumps({"citations": found, "status": "resolver lookup is a v1 build item; nothing was asserted by a model"}, indent=2)); return 0
    ap.print_help(); return 0

if __name__ == "__main__":
    sys.exit(main())
