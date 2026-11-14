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

def _confirm_approval(action):
    """Approval needs a person at a terminal. An agent with a shell has no TTY."""
    if not sys.stdin.isatty():
        print("error: approving needs an interactive terminal", file=sys.stderr)
        return False
    print(f"About to run: {action['summary']}")
    return input(f"Type {action['id']} to approve: ").strip() == str(action["id"])

def _run_tool(args):
    from . import dispatch as runtime
    try:
        call_args = json.loads(args.args)
    except ValueError as exc:
        print(f"error: --args is not JSON: {exc}", file=sys.stderr); return 2
    ctx = runtime.Context(conn=db.connect(), write_conn=None)
    ctx.write_conn = ctx.conn
    try:
        outcome = runtime.dispatch(args.name, call_args, ctx)
    finally:
        ctx.close()
    print(json.dumps(outcome, indent=2))
    return 0 if outcome["ok"] else 1

def _run_actions(args):
    from . import dispatch as runtime
    conn = db.connect()
    try:
        if args.actions_cmd == "list":
            print(json.dumps(runtime.list_actions(conn, include_decided=args.all), indent=2)); return 0
        if args.actions_cmd == "show":
            print(json.dumps(runtime.get_action(conn, args.id), indent=2)); return 0
        if args.actions_cmd == "reject":
            print(json.dumps(runtime.reject(conn, args.id, args.by), indent=2)); return 0
        if not _confirm_approval(runtime.get_action(conn, args.id)):
            print("not approved; nothing changed", file=sys.stderr); return 2
        outcome = runtime.approve(conn, args.id, args.by)
        print(json.dumps(outcome, indent=2))
        return 0 if outcome["status"] == "executed" else 1
    except runtime.ToolError as exc:
        print(f"error: {exc.message}", file=sys.stderr); return 2
    finally:
        conn.close()

def _run_ask(args):
    from . import local_model
    conn = db.connect()
    try:
        outcome = local_model.ask_matter(conn, args.matter_id, args.question, model=args.model)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2
    finally:
        conn.close()
    print(json.dumps(outcome, indent=2))
    return 0

def _default_cite_resolver():
    """The resolver `legal cite-check` runs by default: a CourtListener
    client when a token is configured in the environment, else None, in
    which case cite-check stays fully offline and reports every citation
    as unverified."""
    from .citations import CourtListenerClient
    client = CourtListenerClient()
    return client if client.has_token else None

def main(argv=None, *, cite_resolver=None):
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
    dc = sub.add_parser("doc-compare", help="deterministic paragraph-level DOCX compare")
    dc.add_argument("original"); dc.add_argument("revised"); dc.add_argument("--json", action="store_true")
    dr = sub.add_parser("doc-redline", help="build a DOCX redline with real w:ins / w:del track changes")
    dr.add_argument("original"); dr.add_argument("revised"); dr.add_argument("-o", "--output", required=True)
    bp = sub.add_parser("bates-plan", help="plan Bates labels for a page count (plan only; renders nothing)")
    bp.add_argument("--pages", type=int, required=True); bp.add_argument("--prefix", default="")
    bp.add_argument("--start", type=int, default=1); bp.add_argument("--digits", type=int, default=6)
    bs = sub.add_parser("bates-stamp", help="stamp Bates labels onto every page of a real PDF and write a stamped PDF")
    bs.add_argument("input"); bs.add_argument("-o", "--output", required=True)
    bs.add_argument("--prefix", default=""); bs.add_argument("--start", type=int, default=1)
    bs.add_argument("--digits", type=int, default=6)
    rd = sub.add_parser("redact", help="true redaction: rebuild a PDF from its redacted text layer only, with metadata cleared, and verify the rebuilt bytes")
    rd.add_argument("input"); rd.add_argument("phrases", nargs="+"); rd.add_argument("-o", "--output", required=True)
    rv = sub.add_parser("redact-verify", help="verify phrases are absent from a PDF's re-extracted text layer, or from a plain text file (a text file check is not a PDF check)")
    rv.add_argument("text_file", help="a PDF file, or a plain extracted-text file"); rv.add_argument("phrases", nargs="+")
    t = sub.add_parser("tools"); t.add_argument("--json", action="store_true")
    tool = sub.add_parser("tool", help="call one legal_* tool, exactly as an agent would")
    tool.add_argument("name"); tool.add_argument("--args", default="{}", help="JSON object of arguments")
    actions = sub.add_parser("actions", help="review pending actions; the only way a proposed write runs")
    asub = actions.add_subparsers(dest="actions_cmd", required=True)
    alist = asub.add_parser("list"); alist.add_argument("--all", action="store_true")
    asub.add_parser("show").add_argument("id", type=int)
    for verb in ("approve", "reject"):
        decide = asub.add_parser(verb); decide.add_argument("id", type=int); decide.add_argument("--by", required=True)
    mcp = sub.add_parser("mcp", help="run the MCP server, or control whether it may propose writes")
    mcpsub = mcp.add_subparsers(dest="mcp_cmd", required=True)
    mcpsub.add_parser("serve")
    mcpsub.add_parser("allow-writes").add_argument("state", choices=["on", "off"])
    ask = sub.add_parser("ask", help="ask about a matter using only a model on this computer")
    ask.add_argument("matter_id", type=int); ask.add_argument("question"); ask.add_argument("--model", default=None)
    p = sub.add_parser("models", help="privacy tiers, provider catalog, and local models")
    p.add_argument("--json", action="store_true")
    p.add_argument("--ceiling", choices=["LOCAL_ONLY", "ZERO_RETENTION", "STANDARD"], default=None,
                   help="only show providers this matter ceiling allows")
    args = ap.parse_args(argv)
    if args.cmd == "doctor":
        lines, missing = doctor.run()
        print("\n".join(lines)); return 1 if missing else 0
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
                     "endpoint": providers.provider_endpoint(p),
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
                endpoint = providers.provider_endpoint(p)
                if endpoint:
                    print(f"      endpoint: {endpoint}")
                if p.notes:
                    print(f"      {p.notes}")
        print("\nLocal models:")
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
        print("Dashboard is a v1 build item; the CLI, plugin and MCP tools work today.")
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
        try:
            with pathlib.Path(args.output).open("xb") as handle:
                handle.write(out)
        except FileExistsError:
            print(f"error: {args.output} already exists; a redline never overwrites a file", file=sys.stderr)
            return 2
        print(f"redline written to {args.output} (track changes by hermes-legal (AI - unverified); a human must accept them)")
        return 0
    if args.cmd == "bates-plan":
        from .pdf_tools import BatesConfig, plan_bates_stamps
        stamps = plan_bates_stamps(args.pages, BatesConfig(prefix=args.prefix, start=args.start, digits=args.digits))
        print(json.dumps([s.as_dict() for s in stamps], indent=2))
        print("plan only: no PDF was stamped by this command")
        return 0
    if args.cmd == "bates-stamp":
        import pathlib
        from . import pdf_tools
        from .pdf_tools import BatesConfig, plan_bates_stamps, stamp_pdf
        data = pathlib.Path(args.input).read_bytes()
        if not pdf_tools.is_pdf_bytes(data):
            print("error: no PDF was stamped: the input is not a PDF", file=sys.stderr); return 2
        config = BatesConfig(prefix=args.prefix, start=args.start, digits=args.digits)
        try:
            stamped = stamp_pdf(data, config)
        except RuntimeError as exc:
            print(f"error: no PDF was stamped: {exc}", file=sys.stderr); return 2
        plan = plan_bates_stamps(pdf_tools.extract_text_layer(data).page_count, config)
        try:
            with pathlib.Path(args.output).open("xb") as handle:
                handle.write(stamped)
        except FileExistsError:
            print(f"error: {args.output} already exists; stamping never overwrites a file", file=sys.stderr)
            return 2
        print(f"stamped PDF written to {args.output}: {len(plan)} pages, "
              f"labels {plan[0].label} to {plan[-1].label}" if plan else
              f"stamped PDF written to {args.output}: 0 pages")
        return 0
    if args.cmd == "redact":
        import pathlib
        from . import pdf_tools
        data = pathlib.Path(args.input).read_bytes()
        if not pdf_tools.is_pdf_bytes(data):
            print("error: no PDF was redacted: the input is not a PDF", file=sys.stderr); return 2
        try:
            result = pdf_tools.redact_pdf(data, list(args.phrases))
        except RuntimeError as exc:
            print(f"error: no PDF was redacted: {exc}", file=sys.stderr); return 2
        for line in pdf_tools.REDACTION_COVERAGE:
            print(line)
        if not result.verification.passed:
            print("error: redaction verification failed on the rebuilt PDF; no output file was written",
                  file=sys.stderr)
            print(json.dumps(result.as_dict(), indent=2))
            return 1
        try:
            with pathlib.Path(args.output).open("xb") as handle:
                handle.write(result.output_bytes)
        except FileExistsError:
            print(f"error: {args.output} already exists; redaction never overwrites a file", file=sys.stderr)
            return 2
        print(f"redacted PDF written to {args.output}: {result.plan.as_dict()['hit_count']} occurrence(s) "
              f"removed from pages {result.plan.pages_affected}; verification passed on the rebuilt bytes")
        return 0
    if args.cmd == "redact-verify":
        import pathlib
        from . import pdf_tools
        from .pdf_tools import DocumentText, verify_redaction
        data = pathlib.Path(args.text_file).read_bytes()
        if pdf_tools.is_pdf_bytes(data):
            try:
                doc = pdf_tools.extract_text_layer(data)
            except RuntimeError as exc:
                print(f"no PDF was checked: {exc}", file=sys.stderr)
                return 2
            result = verify_redaction(doc, list(args.phrases))
            print("checked the text layer re-extracted from the PDF file itself")
            print(json.dumps(result.as_dict(), indent=2))
            return 0 if result.passed else 1
        doc = DocumentText.from_texts([data.decode("utf-8")])
        result = verify_redaction(doc, list(args.phrases))
        print("no PDF was checked: the input is not a PDF, so only this plain text was checked; "
              "a text file passing proves nothing about any PDF")
        print(json.dumps(result.as_dict(), indent=2))
        return 0 if result.passed else 1
    if args.cmd == "cite-check":
        from .citations import BLOCKING_STATUSES, HISTORY_DISCLAIMER, extract_citations, format_citation, verify_all_gate
        resolver = cite_resolver if cite_resolver is not None else _default_cite_resolver()
        found = extract_citations(args.text, include_unrecognized=True)
        gate = verify_all_gate(args.text, resolver=resolver)
        results = {r.citation: r for r in gate.results}
        entries = []
        for c in found:
            result = results.get(c.normalized)
            entries.append({
                "raw": c.raw, "normalized": c.normalized, "formatted": format_citation(c),
                "status": result.status if result else "unverified",
                "source": result.source if result else "",
                "detail": result.detail if result else "",
            })
        statuses = [e["status"] for e in entries]
        if gate.allowed and statuses:
            overall = statuses[0] if len(set(statuses)) == 1 else "exists"
        elif statuses:
            overall = next((s for s in statuses if s in BLOCKING_STATUSES), statuses[0])
        else:
            overall = "unverified"
        if resolver is None:
            note = "Extraction checks nothing: no resolver was run, so every citation above is unverified and nothing was asserted by a model."
        else:
            note = (f"Citation statuses are from the {getattr(resolver, 'name', 'resolver')} resolver; "
                    "a failed, not found, or ambiguous lookup is never reported as a match.")
        print(json.dumps({
            "citations": entries,
            "status": overall,
            "resolver": getattr(resolver, "name", None) if resolver is not None else None,
            "note": note,
            "history": "history_unknown",
            "history_note": HISTORY_DISCLAIMER,
            "verify_all_gate": {"allowed": gate.allowed, "blocked": list(gate.blocked_citations)},
        }, indent=2)); return 0
    if args.cmd == "tool":
        return _run_tool(args)
    if args.cmd == "actions":
        return _run_actions(args)
    if args.cmd == "mcp":
        from . import mcp_server
        if args.mcp_cmd == "serve":
            return mcp_server.serve()
        mcp_server.set_writes_allowed(db.connect(), args.state == "on")
        print(f"MCP write proposals are {args.state}. Every proposal still needs a person to approve it.")
        return 0
    if args.cmd == "ask":
        return _run_ask(args)
    ap.print_help(); return 0

if __name__ == "__main__":
    sys.exit(main())
