[ ] Expand use case as a multiagent COMMUNCATION LAYER for autonomous teamwork tasks that requiremultiple agents. 
  - keeps a central communcation plane. 
  - "email" / "inboxes" for every agent involved. 
  - keeps ledger of tasks done and decisions made for every agent. 
  - 
[ ] use inception labs mercury 2 model for structured outputs usecases. 

[ ] Ingestion for conversation should probably be called when compaction happens

[ ] 1. Interactive style UI allowing for:
- think infinite canvas / 'obsidian clone' style. 
- examples to build off
    - tldraw : tldraw/tldraw
    - blocksuite edgeless :

- graph inspection
- has dedicated 'memory agent' - notebook LM style agent grounded in your memory sources. 
- for each thread you can create different agent by selecting your sources from the memory database (similar to notebook_LM notebooks)
- option to do isolated research tasks in each notebook/thread to injest to material (similar to notebook LM as well). 

[ ] notebook LM style clone with content generation options.

[ ] Free initial memory import/ingestion from other ai providers


[ ] 

[ ] 2. Browser extension for chatgpt / other web UI agents to offer passive memory ingestion to the users database. 
- note : must get explicit agreement from users when they install

[ ] 3. ACP protocol / proxy for CLI coding agents / cursor , 
- EXAMPLE: look at how zed integrates codex and claude code CLI , all chats exposed for the chat ui and debug mode. 

[ ] Healthcare experiments: after running the current `Exp 1` temporal baseline and `Exp 2` multi-hop baseline on `synthea-scale-mid-fhirfix`, add two new clinically useful longitudinal benchmarks:
- `Exp 3` pre-visit clinical focus / visit-prep tasks
- `Exp 4` time-sliced diagnostic suggestion tasks
- keep the current baseline suite first, then add these as separate experiments rather than replacing `Exp 1` / `Exp 2`

[ ] OpenClaw plugin follow-up: compare `agentic-memory` and `m26pipeline` recovery behavior after the Docker restart on April 20, 2026.
- Verify which `repo_id` values are actually valid / indexed for `m26pipeline`.
- Re-run the comparison with stronger repo-scoped queries once repo identity is unambiguous.
- Consider adding a repo discovery surface such as `list_repos` or explicit `resolved_repo_id` in tool responses so plugin-only testing is less guessy.
