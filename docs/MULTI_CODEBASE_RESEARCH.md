# Multi-Codebase Research Notes for CodeMemory

Prepared: 2026-04-03  
Scope: current CodeMemory behavior, multi-codebase design options, and relevant production patterns from vector/graph systems.

---

## 1. Executive Summary

- CodeMemory is still effectively a single-codebase system for both the main code graph and the new memory graph.
- The main blockers are identity and retrieval:
  - identities such as `File.path` and `Memory.name` are currently global
  - code and memory search do not currently scope by repository
- There is already an internal precedent for repo scoping:
  - the git graph uses `repo_id`
  - it already uses composite uniqueness constraints such as `(repo_id, sha)`
- There are two serious architecture directions:
  - separate Neo4j database per repo
  - one shared Neo4j database with `repo_id` partitioning everywhere
- If the product goal is hard isolation first, separate databases are the cleanest model.
- If the product goal is one Aura instance plus future cross-repo intelligence, shared database plus `repo_id` is the better long-term model.
- If CodeMemory stays shared-database, retrieval should not stop at plain vector search. The graph adds most value when retrieval is:
  - seed retrieval
  - repo scoping
  - local graph expansion
  - reranking

---

## 2. Current State in This Repo

### 2.1 Code Graph

- Main implementation lives in:
  - `D:\code\codememory\src\codememory\ingestion\graph.py`
  - `D:\code\codememory\src\codememory\server\app.py`
  - `D:\code\codememory\src\codememory\server\tools.py`
- Current code search index:
  - vector index `code_embeddings`
- Current code search behavior in `KnowledgeGraphBuilder.semantic_search()`:
  1. embed query
  2. vector search `db.index.vector.queryNodes('code_embeddings', ...)`
  3. hop from `Chunk` to described entity via `[:DESCRIBES]`
  4. return `name`, `sig`, `text`
- Important limitation:
  - the default code search path does not return `CALLS`, `IMPORTS`, or broader graph neighborhoods in the same result set
  - graph relationships are exposed through separate tools like dependency and impact analysis

### 2.2 Memory Graph

- Current memory support is in the same Neo4j database under label `Memory`.
- Current memory schema setup in `KnowledgeGraphBuilder.setup_memory_schema()` creates:
  - uniqueness constraint on `Memory.name`
  - vector index `memory_embeddings`
  - fulltext index `memory_search`
- Current memory write behavior:
  - `create_memory_entities()` creates or updates `(:Memory {name, type, entity_type, observations, observation_text, metadata_json})`
  - a normalized secondary label is applied from the entity type
  - `create_memory_relations()` creates real typed relationships such as `CONTAINS` or `BUILDS_ON`
  - `add_memory_observations()` and `delete_memory_observations()` refresh the node embedding when OpenAI is configured
  - `backfill_memory_embeddings()` exists for historical nodes
- Current memory search behavior in `KnowledgeGraphBuilder.search_memory_nodes()`:
  - without OpenAI: fulltext only
  - with OpenAI: vector search on `memory_embeddings` unioned with fulltext search
  - after candidate selection, outgoing `(:Memory)-[r]->(:Memory)` relationships are returned as `outgoing_relations`
- Important limitation:
  - memory relationships are returned after the node search
  - relationship embeddings are not indexed today

### 2.3 Identity and Multi-Repo Gaps

- Main code graph currently has no usable repo partition field.
- `repo_id` does not appear on `File`, `Function`, `Class`, `Chunk`, or `Memory`.
- Current single-repo assumptions:
  - `File.path` is globally unique
  - `Function.signature` is globally unique
  - `Memory.name` is globally unique
- Result:
  - two repos with the same relative path would collide
  - two repos with the same memory node name would collide
  - search results are not repo-scoped today

### 2.4 Existing Internal Precedent: Git Graph

- Git graph implementation lives in:
  - `D:\code\codememory\src\codememory\ingestion\git_graph.py`
- It already uses:
  - `repo_id = str(repo_root)`
  - `GitRepo {repo_id}`
  - composite constraints like:
    - `(repo_id, sha)` on `GitCommit`
    - `(repo_id, email_norm)` on `GitAuthor`
    - `(repo_id, sha, path)` on `GitFileVersion`
- This matters because it proves CodeMemory already has one working repo-scoped design inside the same Neo4j instance.

---

## 3. Live Aura Snapshot

Observed on 2026-04-03 via read-only inspection against the configured Aura instance:

- Databases currently online:
  - `neo4j`
  - `system`
- Neo4j component report:
  - `Neo4j Kernel 5.27-aura`
  - `edition: enterprise`
- Important interpretation:
  - multiple standard databases are supported in Neo4j Enterprise in principle
  - this specific Aura deployment currently exposes only one standard database: `neo4j`
  - that is a deployment fact, not a general Neo4j limitation
- Existing live memory shape already aligned with:
  - base label `Memory`
  - `name`, `type`, `observations`
  - typed relationships between memory nodes

---

## 4. Key Concepts

### 4.1 Composite Uniqueness and Key Constraints

- A single-property uniqueness constraint says:
  - "`path` must be unique everywhere"
- A composite uniqueness constraint says:
  - "the pair `(repo_id, path)` must be unique"
- That is the right model when identity is repo-scoped instead of global.
- Examples that fit CodeMemory:
  - `File(repo_id, path)`
  - `Function(repo_id, signature)`
  - `Chunk(repo_id, chunk_id)` or another repo-scoped chunk identity
  - `Memory(repo_id, name)`
- Use uniqueness constraints when existence of all fields is not guaranteed.
- Use key constraints when the properties must both:
  - always exist
  - be unique as a combination

Why this matters:

- without repo in the identity, multiple repos will overwrite or collide
- with repo in the identity, identical paths or memory names can safely exist in different repos

### 4.2 Vector Index Scope

- Historically, Neo4j vector indexes are schema objects over a label/type and a property.
- Current Neo4j docs say:
  - a vector index can index nodes or relationships
  - as of Neo4j 2026.01, vector indexes can also be multi-label, multi-relationship-type, or include additional properties for filtering
- Current CodeMemory code still uses the older procedural query style:
  - `db.index.vector.queryNodes(...)`
- Practical implication:
  - today, CodeMemory should still be thought of as using shared node-type indexes
  - repo-aware filtering is not implemented in the current code path
  - newer Neo4j filtering features may improve the shared-database design later, but they should be treated as version-sensitive and unverified for this deployment

### 4.3 Query-Time Filtering

- Query-time filtering does not mean traversing the whole graph before the search.
- The usual shape is:
  1. vector search finds candidate nodes
  2. candidates are filtered or reranked for the active repo
  3. graph expansion happens only around the surviving candidates if needed
- The real performance risk is not graph traversal first.
- The real performance risk is:
  - a shared index may return too many wrong-repo candidates in the top `k`
  - after filtering, too few useful results remain
- Common fix:
  - over-fetch candidates
  - then rerank after repo scoping

### 4.4 Graph-Aware Retrieval

- If retrieval stops at plain ANN top-k, the graph is underused.
- A more graph-native retrieval pipeline looks like:
  1. retrieve semantic seed nodes
  2. scope to the active repo
  3. expand nearby graph structure
  4. rerank using semantic and structural signals
  5. return graph-aware context to the model
- For CodeMemory, structural signals could include:
  - same file
  - same class
  - direct `CALLS`
  - direct `IMPORTS`
  - memory relation overlap
  - git co-change or provenance links later

---

## 5. Architecture Options

### Option A: Separate Neo4j Database Per Repo

### Summary

- One repo gets one standard Neo4j database.
- Code graph and memory graph for that repo live together inside that database.

### Strengths

- strongest isolation boundary
- simplest correctness story
- no cross-repo collisions by construction
- each repo gets its own constraints and indexes
- retrieval never needs repo filtering

### Weaknesses

- operationally heavier
- requires database lifecycle management
  - create
  - delete
  - backup
  - connect to the right database
- harder to support cross-repo search later
- migration and tooling become more DB-aware

### Best Fit

- enterprise or regulated environments
- few to moderate number of repos
- strong tenant isolation requirement
- little or no need for cross-repo queries

### Relevance to Current Aura

- Neo4j Enterprise supports multiple standard databases in principle.
- This specific Aura instance currently shows only one standard database online.
- Before choosing this path, verify whether the plan and permissions actually allow creating additional databases in this deployment.

---

### Option B: Shared Neo4j Database With `repo_id` Partitioning

### Summary

- Keep one database, typically `neo4j`
- Put all repos into that graph
- Add `repo_id` to all code and memory nodes
- Make identities composite instead of global

### Required Schema Changes

- Add `repo_id` to:
  - `File`
  - `Function`
  - `Class`
  - `Chunk`
  - `Memory`
- Add or reuse a repository anchor node such as:
  - `(:Repository {repo_id, name, root_path})`
- Update constraints to repo-scoped forms such as:
  - `FOR (f:File) REQUIRE (f.repo_id, f.path) IS UNIQUE`
  - `FOR (m:Memory) REQUIRE (m.repo_id, m.name) IS UNIQUE`

### Strengths

- one Aura instance
- one MCP server
- easier future cross-repo search
- operationally simpler than many databases
- matches the repo-scoped git graph precedent already in the codebase

### Weaknesses

- retrieval becomes more subtle
- every write and read path must carry repo context
- migrations are more invasive
- naive top-k vector search plus blind filtering is not enough

### Best Fit

- many repos
- one shared platform
- desire for optional future cross-repo intelligence
- willingness to implement repo-aware retrieval properly

### Recommended Retrieval Shape If This Option Is Chosen

1. Retrieve more candidates than final output requires.
2. Scope or filter to the active repo.
3. Expand local graph structure.
4. Rerank using semantic plus structural features.
5. Return only active-repo results by default.

---

### Option C: Shared Database With One Vector Index Per Repo

### Summary

- Keep one database
- create repo-specific vector indexes such as:
  - `code_embeddings_repo_a`
  - `code_embeddings_repo_b`
  - `memory_embeddings_repo_a`

### Why This Is Usually Not The Right Default

- every new repo creates new index lifecycle work
- index count scales with repo count
- index build time and storage overhead scale with repo count
- code has to route every query to the correct dynamic index
- cross-repo search becomes a fan-out problem
- Neo4j does not give CodeMemory a namespace-first multitenancy abstraction similar to Pinecone namespaces or Weaviate tenants

### When It Might Be Justified

- very small number of repos
- extremely strict performance targets on shared indexes
- no expectation that repo count will grow much

### Overall Assessment

- possible
- not impossible
- but usually a poor default for a growing multi-repo system inside one Neo4j database

---

### Option D: Hybrid Promotion Model

### Summary

- Start small repos in a shared database
- promote very large or high-isolation repos to dedicated databases later

### Why It Is Interesting

- matches real-world tenant skew
- avoids overcommitting early
- lets the platform support both:
  - cheap shared mode
  - premium isolated mode

### Tradeoff

- most flexible
- most operationally complex

### Real-World Analogy

- Qdrant’s tiered multitenancy is conceptually similar:
  - small tenants share infrastructure
  - large tenants can be promoted into more isolated placement

---

## 6. Real-World Patterns and Implementations

| System | Common tenant model | What they recommend | Why it matters for CodeMemory |
|---|---|---|---|
| Pinecone | One index per workload, one namespace per tenant | Writes and queries always target a namespace | Strong argument that namespace-style partitioning is the normal vector-native pattern, not one ANN index per tenant |
| Qdrant | Usually one collection per embedding model, tenant partitioning inside it | Prefer payload-based partitioning for most cases; add dedicated shards for large tenants | Strong precedent for shared infrastructure first, then promotion when size skews |
| Weaviate | Multi-tenancy inside a collection | Separate tenant shards with lower overhead than separate collections | Strong precedent for shared schema plus tenant-aware partitions |
| Milvus | Multiple levels: database, collection, partition, partition key | Partition-key-based multitenancy for scale; DB-level for strongest isolation | Useful comparison because it explicitly documents several tradeoff tiers |
| Neo4j | Multiple standard databases in Enterprise; vector indexes on node/relationship schemas | Good for graph-native workloads, but multitenancy needs explicit schema or DB design | Most relevant for CodeMemory because we need graph structure plus embeddings, not embeddings alone |

### 6.1 Pinecone

- Official pattern:
  - one namespace per tenant inside an index
  - all data plane operations target one namespace
- Pinecone frames this as:
  - tenant isolation
  - faster queries
  - simpler offboarding
- Important takeaway for CodeMemory:
  - vector-native systems usually provide a first-class tenant boundary inside the index
  - Neo4j does not currently give CodeMemory that same ergonomic abstraction in the current code path

### 6.2 Qdrant

- Official guidance says:
  - do not create huge numbers of collections by default
  - in most cases, use a single collection per embedding model with tenant partitioning
- Qdrant also documents tiered multitenancy:
  - shared fallback shard for small tenants
  - dedicated shards for large tenants
  - tenant promotion as they grow
- Important takeaway for CodeMemory:
  - this is a strong precedent for a hybrid future if repo sizes become highly uneven

### 6.3 Weaviate

- Official guidance says:
  - multi-tenancy isolates data for different tenants within a single Weaviate instance
  - each tenant is stored on a separate shard
  - multi-tenancy has lower overhead than one collection per tenant
- Important takeaway for CodeMemory:
  - shared schema plus tenant-scoped physical placement is a proven pattern
  - this is closer to shared DB plus `repo_id` than to dynamic index-per-repo

### 6.4 Milvus

- Milvus explicitly documents several multi-tenancy levels:
  - database
  - collection
  - partition
  - partition key
- Milvus recommends partition key when scale matters because it narrows the search scope and avoids scanning irrelevant partitions.
- Important takeaway for CodeMemory:
  - the product decision is really about placement level
  - stronger isolation and better scaling are traded off against flexibility and operational complexity

### 6.5 Neo4j-Specific Takeaway

- Neo4j can support multiple standard databases in Enterprise.
- Neo4j vector indexes now also support more advanced schema options in the latest docs.
- However, CodeMemory today is not using Neo4j like a tenant-native vector store.
- CodeMemory today is a graph system with vector-assisted retrieval.
- That means the important product decision is not only index placement.
- It is also:
  - identity model
  - repo context propagation
  - graph-aware retrieval behavior

---

## 7. What This Means for CodeMemory

### If The Goal Is Hard Isolation First

- Choose separate database per repo.
- Keep code and memory together inside each repo database.
- Simplify retrieval because repo scoping becomes implicit.

### If The Goal Is One Aura Instance Plus Future Cross-Repo Intelligence

- Choose shared database plus `repo_id`.
- Migrate code graph and memory graph to repo-scoped identities.
- Rework retrieval so it is repo-aware and graph-aware.

### What Should Not Ship

- shared database with global uniqueness on `File.path`
- shared database with global uniqueness on `Memory.name`
- shared database with no repo context in MCP tools
- naive vector top-k followed by blind filtering and no reranking
- dynamic per-repo index creation as the default scaling model

---

## 8. Concrete Shared-Database Design Sketch

### 8.1 Identity

- Add `repo_id` everywhere.
- Add a repository node:
  - `(:Repository {repo_id, root_path, remote_url, default_branch})`

### 8.2 Constraints

- `FOR (f:File) REQUIRE (f.repo_id, f.path) IS UNIQUE`
- `FOR (fn:Function) REQUIRE (fn.repo_id, fn.signature) IS UNIQUE`
- `FOR (c:Class) REQUIRE (c.repo_id, c.name, c.file_path) IS UNIQUE` or another stable repo-scoped class identity
- `FOR (m:Memory) REQUIRE (m.repo_id, m.name) IS UNIQUE`

### 8.3 Query Model

- MCP tools receive repo context explicitly or derive it from configured repo root.
- Search defaults to active repo only.
- Cross-repo search must be opt-in.

### 8.4 Retrieval Model

1. vector retrieve seed candidates
2. keep active repo candidates
3. expand local graph neighborhood
4. rerank
5. return final context

### 8.5 Migration Shape

1. define stable repo identity
2. add `repo_id` to all newly written nodes
3. backfill historical nodes
4. create repo-scoped constraints
5. update search and write tools
6. remove legacy global assumptions

---

## 9. Open Questions Worth Researching Next

- Does the current Aura plan permit creating and managing multiple standard databases?
- How many repos should one Aura deployment realistically support?
- Do users need cross-repo search, or only strict per-repo isolation?
- Should repo context be implicit from `CODEMEMORY_REPO`, explicit in every MCP tool, or both?
- Do we need a concept of global/shared memory in addition to repo-scoped memory?
- Should memory retrieval stay node-level, or do some memory entries need chunking later?
- Should reranking happen in Neo4j, in application code, or via a separate reranker model?
- Are Neo4j’s latest vector filtering features available on this exact Aura deployment and query path?

---

## 10. Provisional Recommendation

- Short term:
  - choose between hard-isolation and shared-platform goals first
  - do not make index-level decisions before that product choice
- If forced to choose today for CodeMemory specifically:
  - pick shared database plus `repo_id`
  - because the repo already has a `repo_id` precedent in the git graph
  - and because this preserves future cross-repo capabilities
- But only choose shared database if retrieval is upgraded beyond naive vector top-k.

---

## 11. Sources

### Official Neo4j

- Neo4j database administration:
  - [https://neo4j.com/docs/operations-manual/current/database-administration/](https://neo4j.com/docs/operations-manual/current/database-administration/)
- Neo4j vector indexes:
  - [https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/)
- Neo4j constraints overview:
  - [https://neo4j.com/docs/cypher-manual/current/schema/constraints/](https://neo4j.com/docs/cypher-manual/current/schema/constraints/)
- Neo4j create constraints:
  - [https://neo4j.com/docs/cypher-manual/current/schema/constraints/create-constraints/](https://neo4j.com/docs/cypher-manual/current/schema/constraints/create-constraints/)

### Pinecone

- Pinecone multitenancy:
  - [https://docs.pinecone.io/guides/index-data/implement-multitenancy](https://docs.pinecone.io/guides/index-data/implement-multitenancy)
- Pinecone namespaces:
  - [https://docs.pinecone.io/guides/indexes/use-namespaces](https://docs.pinecone.io/guides/indexes/use-namespaces)

### Qdrant

- Qdrant multitenancy:
  - [https://qdrant.tech/documentation/manage-data/multitenancy/](https://qdrant.tech/documentation/manage-data/multitenancy/)
- Qdrant multitenancy with LlamaIndex:
  - [https://qdrant.tech/documentation/examples/llama-index-multitenancy/](https://qdrant.tech/documentation/examples/llama-index-multitenancy/)

### Weaviate

- Weaviate multi-tenancy operations:
  - [https://docs.weaviate.io/weaviate/manage-collections/multi-tenancy](https://docs.weaviate.io/weaviate/manage-collections/multi-tenancy)
- Weaviate collection definition and multi-tenancy config:
  - [https://docs.weaviate.io/weaviate/config-refs/schema](https://docs.weaviate.io/weaviate/config-refs/schema)
- Weaviate data concepts:
  - [https://docs.weaviate.io/weaviate/concepts/data](https://docs.weaviate.io/weaviate/concepts/data)
- Weaviate best practices:
  - [https://docs.weaviate.io/weaviate/best-practices](https://docs.weaviate.io/weaviate/best-practices)

### Milvus

- Milvus partition key:
  - [https://milvus.io/docs/v2.4.x/use-partition-key.md](https://milvus.io/docs/v2.4.x/use-partition-key.md)
- Milvus multi-tenancy strategies:
  - [https://milvus.io/docs/v2.2.x/multi_tenancy.md](https://milvus.io/docs/v2.2.x/multi_tenancy.md)

---

## 12. Repo Evidence

- Main code graph and memory graph:
  - `D:\code\codememory\src\codememory\ingestion\graph.py`
- MCP layer:
  - `D:\code\codememory\src\codememory\server\app.py`
  - `D:\code\codememory\src\codememory\server\tools.py`
- Existing repo-scoped precedent:
  - `D:\code\codememory\src\codememory\ingestion\git_graph.py`
