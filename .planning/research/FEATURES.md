# Feature Landscape

**Domain:** Knowledge Graph & Agent Memory Systems (Web Research + Conversation Memory)
**Researched:** 2026-03-20
**Confidence:** MEDIUM (training data from 2025, unable to verify with current sources)

## Table Stakes

Features users expect. Missing = product feels incomplete.

### Web Research Memory Module

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| URL ingestion | Core capability - users need to add web pages to memory | Low | Single page extraction, synchronous processing |
| PDF document parsing | Research inherently involves papers, reports, docs | Medium | Need text extraction, handle scanned PDFs (OCR optional) |
| Semantic search across content | Must find relevant info across all ingested material | Medium | Requires embeddings, vector search infrastructure |
| Web page crawling | Following links is fundamental to research workflows | Medium | Respect robots.txt, handle pagination, avoid infinite loops |
| Metadata extraction | Users expect title, author, date, source URL tracked | Low | Standard HTML/PDF metadata parsing |
| Content deduplication | Same URL/content shouldn't create duplicate entries | Medium | Hash-based detection, update vs create logic |
| Batch ingestion | Research involves processing multiple sources at once | Low | Queue mechanism, progress tracking |
| Search result integration | Automated research starts with search queries | Medium | API integration (Brave, Google, etc.), result ranking |
| Content filtering | Users need to exclude ads, navigation, boilerplate | Medium | Article extraction (readability algorithms) |
| Basic scheduling | "Check this daily" is minimum for automation | Medium | Cron-like mechanism, variation tracking |

### Agent Conversation Memory Module

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Conversation persistence | Core capability - save chat history permanently | Low | Structured storage of messages, timestamps |
| Semantic search | Find relevant past conversations/exchanges | Medium | Embedding-based retrieval, not just keyword |
| Session/conversation boundaries | Users need to distinguish separate conversations | Low | Conversation ID, start/end markers |
| User/agent attribution | "Who said what" tracking is fundamental | Low | Role tagging (user/assistant/system) |
| Incremental updates | Add new messages without re-indexing everything | Medium | Append-only operations, efficient updates |
| Context retrieval | Get relevant history for current conversation | High | Ranking/relevance, recency bias, context window management |
| Manual import | Users have historical chat logs to ingest | Low | JSON/CSV/text format parsing |
| Basic search filters | Filter by date, participant, conversation | Low | Query DSL or structured filters |
| Message threading | Follow conversation flow, reply chains | Medium | Parent-child message relationships |
| Export capability | Users expect to extract their conversation data | Low | JSON/CSV export, data portability |

### Shared Infrastructure

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| CLI interface | Developer tools need CLI-first approach | Low | Standard commands: init, ingest, search, serve |
| Configuration management | Users need to customize behavior | Low | Config files, env vars, sensible defaults |
| MCP server integration | AI agents access memory via tools | Medium | Tool definitions, routing, authentication |
| Multi-database support | Isolation for different content types | Medium | Connection management, routing logic |
| Error handling & logging | Production systems need observability | Low | Structured logs, error recovery |
| Documentation | Users can't use undocumented features | Low | Setup guides, API references, examples |

## Differentiators

Features that set product apart. Not expected, but valued.

### Web Research Memory Module

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Automated research schedules | "Daily deep dives" - build knowledge over time | High | Query variation generation, duplicate detection, trend tracking |
| Multi-modal content (images, videos) | Research isn't just text anymore | High | Multimodal embeddings, image/video metadata extraction |
| Citation tracking | Academic/professional users need provenance | Medium | Backlink graphs, reference chains |
| Dynamic content handling | Many sites require JS rendering | High | Browser automation (Playwright/agent-browser) |
| Research question evolution | Queries refine based on findings | High | Query generation based on gaps, feedback loops |
| Cross-source synthesis | Connect findings across multiple sources | High | Entity resolution, relationship inference |
| Conflict detection | Flag contradictory information | High | Claim extraction, contradiction detection |
| Source credibility scoring | Help users assess information quality | Medium | Domain reputation, author tracking, consensus |
| Research templates | Pre-configured workflows for common tasks | Medium | Template library, customization |
| Insight extraction | Surface key findings automatically | High | Summarization, claim extraction, trend detection |
| Web archive integration | Access historical versions of pages | Medium | Wayback Machine API, version tracking |

### Agent Conversation Memory Module

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Auto-capture mode | Zero-friction memory - conversations auto-saved | Medium | Integration hooks, real-time ingestion |
| Smart summarization | Long conversations → concise context | High | Multi-turn summarization, key point extraction |
| Topic clustering | Auto-organize conversations by themes | High | Unsupervised clustering, topic modeling |
| Follow-up suggestions | "You discussed X last week, want to continue?" | High | Relevance matching, temporal context |
| Cross-conversation linking | Connect related discussions across time | Medium | Entity/topic matching across sessions |
| Personal knowledge extraction | Build user profile from conversations | High | Entity extraction, preference learning, privacy concerns |
| Sentiment tracking | Understand tone/emotion in history | Medium | Sentiment analysis, mood tracking |
| Conversation analytics | Usage patterns, topic distribution, engagement | Medium | Aggregation, visualization data |
| Multi-participant tracking | Group conversations, distinguish speakers | Medium | Speaker diarization, attribution |
| Conversation branching | Track alternative conversation paths | High | Tree structure, explore "what-if" scenarios |
| Context injection | Auto-add relevant history to prompts | High | Ranking, context window optimization, injection strategy |

### Shared Infrastructure

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Unified graph query | Query across code + web + conversations | High | Cross-module relationships, unified schema |
| Embedding model flexibility | Support OpenAI, Gemini, local models | Medium | Model abstraction layer, migration tools |
| Real-time sync | Changes immediately available | Medium | Event streaming, cache invalidation |
| Plugin architecture | Extend with custom ingestors/tools | High | Extension API, sandboxing, discovery |
| GraphRAG capabilities | Structured retrieval over naive vector search | High | Graph traversal + embeddings, multi-hop reasoning |
| Telemetry & analytics | Track usage for optimization | Medium | Event collection, privacy-preserving aggregation |
| Version control for knowledge | Track how knowledge graph evolves | High | Graph versioning, temporal queries |
| Collaborative features | Share knowledge graphs across teams | High | Permissions, sync, conflict resolution |

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|----------------------|
| Full-text search only (no semantic) | Insufficient for modern AI workflows, users expect meaning-based retrieval | Always include vector embeddings + semantic search |
| Real-time collaboration (v1) | Complex, niche need, distracts from core single-user value | Document single-user export/import, defer collaboration |
| Built-in LLM inference | Outside core competency, users have preferred models | Integrate via MCP, let users choose LLMs |
| Web UI dashboard (v1) | Nice-to-have but delays core functionality | CLI + MCP first, UI later after proven |
| Video/audio transcription | Commodity service, not differentiating | Accept transcripts from external tools (Whisper, etc.) |
| Advanced analytics (v1) | Premature - need usage data first | Basic telemetry, build analytics post-validation |
| Social features (sharing, comments) | Scope creep, not core to memory | Focus on personal knowledge, not social network |
| Custom embedding training | Extremely complex, marginal gains | Use proven off-the-shelf models (OpenAI, Gemini) |
| Blockchain/distributed storage | Unnecessary complexity, no user demand | Standard databases (Neo4j, PostgreSQL) |
| Mobile apps (v1) | Limited use case for mobile-first memory | Web/desktop first, mobile if validated need |
| Manual graph editing UI | Error-prone, users want automation | Automated ingestion, not manual graph construction |
| Query language for end users | Too technical for most users | Natural language search via MCP tools |
| Multi-tenancy (v1) | Adds complexity, single-user focus sufficient | One graph per user/project, multi-tenancy post-v1 |

## Feature Dependencies

```
Web Research Memory:
URL ingestion → Content filtering → Metadata extraction
PDF parsing → Text extraction → Semantic search
Search integration → Web crawling → Deduplication
Semantic search → Embeddings → Vector database
Automated schedules → Query variation → Result tracking

Conversation Memory:
Persistence → Message storage → Session boundaries
Semantic search → Embeddings → Vector database
Context retrieval → Relevance ranking → Recency weighting
Auto-capture → Real-time ingestion → Incremental updates
Smart summarization → Multi-turn context → Key point extraction

Shared:
MCP integration → Tool definitions → Graph query capabilities
Multi-database → Connection routing → Config management
GraphRAG → Graph structure → Vector embeddings
```

## MVP Recommendation

### Prioritize (Web Research Memory):
1. **URL ingestion** - Core capability, enables everything else
2. **PDF parsing** - Essential for research workflows
3. **Semantic search** - Table stakes for modern memory systems
4. **Web crawling** - Differentiates from simple bookmark systems
5. **Search integration** - Automated research starts here
6. **Automated schedules** - Key differentiator, enables "daily research" use case

### Prioritize (Conversation Memory):
1. **Conversation persistence** - Core capability
2. **Semantic search** - Must find relevant history
3. **Session boundaries** - Organize conversations
4. **Incremental updates** - Performance requirement
5. **Context retrieval** - Key value prop, enables smart agents
6. **Manual import** - Users have historical data

### Prioritize (Shared):
1. **CLI interface** - Primary user interaction
2. **MCP server** - AI agent integration
3. **Multi-database support** - Isolation, embedding model flexibility
4. **Configuration management** - Customization, multi-environment

### Defer:
- **Automated research question evolution** - Complex, build simpler scheduling first
- **Topic clustering** - Requires usage data to validate value
- **Cross-conversation linking** - Nice-to-have, not blocking
- **Unified graph query** - Valuable but complex, prove modules independently first
- **Source credibility scoring** - Sophisticated, add after core retrieval works
- **Conversation analytics** - Need usage data first
- **Plugin architecture** - Premature generalization, focus on core modules

## Complexity Assessment

### Low Complexity (1-2 weeks per feature):
- URL ingestion, metadata extraction, message persistence, session tracking, CLI commands, config management, export, basic filtering

### Medium Complexity (2-4 weeks per feature):
- PDF parsing, web crawling, deduplication, semantic search, MCP integration, multi-database routing, auto-capture, incremental updates, source credibility

### High Complexity (4-8+ weeks per feature):
- Automated scheduling with variation, dynamic content (browser automation), context retrieval with ranking, GraphRAG, smart summarization, cross-source synthesis, conflict detection, research question evolution, conversation branching

## Competitive Landscape Context

**Training data context (2025):**
- MemGPT: Strong conversation memory, hierarchical summarization
- mem0: Simple API, focus on developer experience
- Zep: Session management, auto-summarization, fact extraction
- LangChain Memory: Flexible but low-level, requires assembly
- LlamaIndex: Document-focused, strong RAG capabilities

**Key gaps in ecosystem:**
- Web research automation (most focus on static docs)
- Unified multi-modal memory (code + web + conversations)
- MCP-native integration (most built pre-MCP era)
- Modular independence (often monolithic)

## Sources

**Note:** Unable to access verification sources. Analysis based on training data knowledge of MemGPT, mem0, Zep, LangChain Memory, LlamaIndex, and knowledge graph best practices through 2025.

**Confidence level:** MEDIUM - comprehensive analysis but unverified against 2026 state-of-the-art
