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
    p = sub.add_parser("models", help="privacy tiers, provider catalog, and local models")
    p.add_argument("--json", action="store_true")
    p.add_argument("--ceiling", choices=["LOCAL_ONLY", "ZERO_RETENTION", "STANDARD"], default=None,
                   help="only show providers this matter ceiling allows")
    args = ap.parse_args(argv)
    if args.cmd == "doctor":
        lines, missing = doctor.run()
        print("\n".join(lines)); return 1 if missing and False else 0
    if args.cmd == "tools":
        print(json.dumps([{"name": t.name, "write": t.write, "description": t.description} for t in tooldefs.TOOLS], indent=2)); return 0
    if args.cmd == "models":
        catalog = providers.PROVIDERS
        if args.ceiling:
            catalog = providers.allowed_providers(args.ceiling)
        if args.json:
            print(json.dumps({
                "tiers": list(providers.TIERS),
                "ceiling": args.ceiling,
                "providers": [
                    {"name": p.name, "tier": p.tier, "trains_on_data": p.trains_on_data,
                     "retention": p.retention, "terms_checked": p.terms_checked,
                     "notes": p.notes,
                     "allowed_at_ceiling": (providers.allowed(p, args.ceiling) if args.ceiling else None)}
                    for p in catalog
                ],
                "local_models": [
                    {"name": n, "size": s, "hardware": h, "license": lic, "role": r}
                    for n, s, h, lic, r in providers.LOCAL_MODELS
                ],
            }, indent=2)); return 0
        heading = "Providers by privacy tier"
        if args.ceiling:
            heading += f" (allowed at ceiling {args.ceiling})"
        print(heading + ":")
        for tier in providers.TIERS:
            group = [p for p in catalog if p.tier == tier]
            if not group:
                continue
            print(f"\n{tier}:")
            for p in group:
                print(f"  {providers.tier_badge(p)}")
                print(f"      retention: {p.retention} | terms checked: {p.terms_checked}"
                      f" | trains on data: {'yes' if p.trains_on_data else 'no'}")
                if p.notes:
                    print(f"      {p.notes}")
        print("\nLocal models:")
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
        from .citations import extract_all
        found = extract_all(args.text)
        print(json.dumps({"citations": found, "status": "resolver lookup is a v1 build item; nothing was asserted by a model"}, indent=2)); return 0
    ap.print_help(); return 0

if __name__ == "__main__":
    sys.exit(main())
