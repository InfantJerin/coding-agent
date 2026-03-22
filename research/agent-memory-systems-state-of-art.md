# State of the Art: Agent Memory Systems (March 2026)

Research compilation on memory architectures for AI agents, with focus on context-scoped memory patterns relevant to deal-scoped agent systems.

---

## 1. Mem0 (mem0.ai) — Universal Memory Layer for AI Agents

### Architecture

Mem0 is a dual-store memory system combining **vector-based semantic search** with an optional **graph memory** layer:

- **Base Mem0**: Stores memories as dense text representations using vector embeddings. Averages ~7k tokens per conversation. An LLM-based extraction function identifies salient facts from message pairs, combining conversation summary, recent message history, and the current exchange.
- **Mem0^g (Graph-Enhanced)**: Extends base with a directed labeled graph where nodes represent entities and edges represent relationships. Averages ~14k tokens per conversation. Uses a two-stage pipeline: entity extraction with semantic types, then relationship triplet derivation.

### Memory Extraction Pipeline

Operates on message pairs (m_{t-1}, m_t) combining:
1. Conversation summary S retrieved from the database
2. Recent message history (configurable window, default m=10)
3. Current message exchange

The extraction function identifies salient facts, then an LLM-driven consolidation phase classifies each fact into four operations:
- **ADD**: New memory when no semantically equivalent exists
- **UPDATE**: Augments existing memory with complementary info
- **DELETE**: Removes memories contradicted by new information
- **NOOP**: No modification needed

For graph memory, conflict detection marks relationships as invalid rather than physically deleting, enabling temporal reasoning.

### Scoping Model

Three identifiers organize context:
- **user_id**: Ties memories to individual users
- **agent_id**: Separates specialized agent contexts (e.g., food-assistant vs. health-assistant)
- **run_id** (session): Segments session-specific memories

Agents share or isolate context within the same user profile. This maps directly to deal-scoped systems: `user_id` = counterparty, `agent_id` = deal agent, `run_id` = specific session/negotiation round.

### Storage Backends

- **Vector**: Any embedding store (OpenAI embeddings, text-embedding-3-small)
- **Graph**: Neo4j, Memgraph, Neptune, Kuzu, Apache AGE
- Configurable confidence threshold for graph edges (default 0.75)
- Per-request toggles: `enable_graph=False` reverts to vector-only

### Query Patterns

- Vector search narrows candidates by semantic similarity
- Graph returns related context in a `relations` array alongside vector results
- Entity-centric retrieval: identifies key entities, locates graph nodes, explores relationships
- Semantic triplet retrieval: encodes queries as embeddings, matches against relationship triplets

### Performance

- 26% relative improvement over OpenAI in LLM-as-a-Judge metric
- Search latency: p50 0.148s, p95 0.200s
- 91% lower p95 latency than full-context baselines (1.44s vs 17.1s)
- Memory consumes 1,764 tokens vs 26,031 for full conversation history

### Relevance to Deal-Scoped Systems

Strong fit. The three-level scoping (user/agent/session) maps naturally to counterparty/deal/session. Graph memory captures entity relationships (parties, terms, obligations) that persist across sessions. The ADD/UPDATE/DELETE/NOOP consolidation prevents memory bloat over long-running deals.

---

## 2. Zep — Temporal Knowledge Graph for Agent Memory

### Architecture

Zep implements **Graphiti**, a temporally-aware knowledge graph engine with three hierarchical subgraphs:

**G = (N, E, phi)** where:

1. **Episode Subgraph (G_e)**: Records episodic memory as raw events/messages annotated with timestamps. Non-lossy data store from which semantic entities are extracted.

2. **Semantic Entity Subgraph (G_s)**: Entities and facts emerge through semantic extraction. Entities embedded in 1024-dimensional space (BGE-m3 models) for fine-grained semantic similarity.

3. **Community Subgraph (G_c)**: Clusters of strongly connected entities with summarizations enabling global domain understanding. Uses label propagation for dynamic extension.

### Bitemporal Tracking Model

Dual-timestamp model tracking both event time and ingestion time:
- **Timeline T**: Chronological ordering of actual events
- **Timeline T'**: Transactional order of data ingestion

Four timestamps per fact:
- **t'_created, t'_expired** in T': System transaction times
- **t_valid, t_invalid** in T: When facts held true in reality

Edge invalidation: when temporally overlapping contradictions are found, the system sets `t_invalid` to the `t_valid` of the invalidating edge, preserving conflicting information within temporal bounds.

### Entity Extraction Pipeline

1. **Initial Extraction**: Process current message + last 4 messages for context. Speaker automatically becomes an entity. Reflection technique minimizes hallucinations.
2. **Embedding & Retrieval**: Entity names embedded in 1024D vectors. Cosine similarity + full-text search on existing nodes.
3. **Resolution**: LLM compares candidate duplicates with episode context. Duplicates consolidated.
4. **Graph Integration**: Predefined Cypher queries (not LLM-generated) ensure consistent schema and reduce hallucinations.

### Search Mechanisms

Three-phase retrieval:

**Search (phi)** — three parallel methods:
- phi_cos: Cosine semantic similarity on embeddings
- phi_bm25: Okapi BM25 full-text search (Neo4j/Lucene)
- phi_bfs: Breadth-first search for contextual similarity (graph proximity)

**Reranking (rho)** — multiple strategies:
- Reciprocal Rank Fusion (RRF)
- Maximal Marginal Relevance (MMR)
- Episode-mention frequency
- Node distance from centroids
- Cross-encoder LLM reranking

**Constructor (chi)**: Formats nodes/edges into context strings with temporal validity ranges.

### Storage Backend

Built on **Neo4j** with Cypher queries. Embeddings via **BGE-m3** models.

### Performance

- Up to 18.5% accuracy improvement over baselines on LongMemEval
- 90% reduction in response latency compared to baselines
- Outperforms MemGPT on Deep Memory Retrieval benchmark

### Relevance to Deal-Scoped Systems

Excellent fit for deal tracking. Bitemporal tracking is critical for financial deals where "what was the term sheet on date X?" is a first-class query. Entity subgraph naturally captures parties, obligations, and evolving relationships. Community detection groups related entities (e.g., all parties to a deal). Temporal invalidation handles amendment/supersession of terms.

---

## 3. LangGraph Memory / Checkpointing

### Architecture: Two Memory Systems

**Short-Term Memory (Checkpointer)**: Saves graph state as checkpoints at every execution step, organized by threads.

**Long-Term Memory (Store)**: Cross-thread persistent data accessible from any thread via namespaced keys.

### Checkpointer Architecture

Implements `BaseCheckpointSaver` interface with methods:
- `.put` — Store checkpoint with config and metadata
- `.put_writes` — Store intermediate writes from successful nodes
- `.get_tuple` — Fetch checkpoint for a given thread
- `.list` — List checkpoints matching filter criteria

**Checkpoint Data Model (StateSnapshot)**:
| Field | Purpose |
|-------|---------|
| values | State channel values at this moment |
| next | Node names to execute next |
| config | Thread ID, checkpoint namespace, checkpoint ID |
| metadata | Execution source, node writes, super-step counter |
| created_at | ISO 8601 timestamp |
| parent_config | Previous checkpoint config |
| tasks | Pending tasks with IDs and interrupt info |

**Checkpoint Namespacing**:
- `""` (empty) = parent/root graph
- `"node_name:uuid"` = subgraph invocation
- Nested subgraphs join with `|` separators

### Backend Implementations

| Backend | Class | Use Case |
|---------|-------|----------|
| In-Memory | InMemorySaver | Dev/test only |
| SQLite | SqliteSaver / AsyncSqliteSaver | Local/experimentation |
| PostgreSQL | PostgresSaver / AsyncPostgresSaver | Production (used by LangSmith) |
| CosmosDB | CosmosDBSaver | Azure production |

Postgres optimizes writes: each channel value stored separately and versioned so new checkpoints only store changed values.

### Store Interface (Cross-Thread Memory)

Tuple-based namespaces for organizing memories:
```
namespace = (user_id, "memories")
store.put(namespace, memory_id, memory_dict)
store.search(namespace)
store.asearch(namespace, query=..., limit=3)  # semantic search
```

Each stored `Item` has: `value`, `key`, `namespace`, `created_at`, `updated_at`.

Semantic search via configurable embeddings (e.g., `openai:text-embedding-3-small`, 1536 dims). The `fields` parameter controls which attributes get embedded.

### Production Patterns

- Compile graph with both: `builder.compile(checkpointer=checkpointer, store=store)`
- Thread_id scopes conversation session; user_id scopes long-term identity
- One user may have many threads
- AES encryption available via `EncryptedSerializer`
- Pending writes: failed nodes re-execute on resume, successful nodes skip
- Time travel: replay from any prior checkpoint

### Relevance to Deal-Scoped Systems

Good foundation. Thread = deal session, Store namespace = deal-level persistent memory. Namespace tuples can encode `(deal_id, "terms")`, `(deal_id, "parties")`, `(counterparty_id, "preferences")`. Cross-thread Store enables sharing counterparty info across deals. However, LangGraph provides primitives, not opinions — you must design the scoping model yourself.

---

## 4. Letta (formerly MemGPT) — Self-Managing Agent Memory

### Architecture: Tiered Memory System

Inspired by OS virtual memory, MemGPT creates an illusion of unlimited memory within fixed context limits:

1. **Core Memory**: Always visible to the agent. Embedded inside system instructions (in-context). Size-limited but configurable. Contains memory blocks (e.g., `human` block for user info, `persona` block for agent identity). The agent's "RAM."

2. **Recall Memory**: Complete history of all interactions. Searchable but not in active context. Raw conversation history preserved. The agent's "conversation log."

3. **Archival Memory**: Explicitly formulated knowledge stored in external databases. Processed and indexed (unlike raw recall). Can use vector databases or graph databases. The agent's "disk storage."

### Self-Managing Memory via Tool Calls

The key innovation: agents decide what to remember by calling memory functions during their reasoning loop:

- `core_memory_append` — Add to a core memory block
- `core_memory_replace` — Update existing core memory
- `archival_memory_insert` — Store in long-term archival
- `archival_memory_search` — Retrieve from archival
- `conversation_search` — Search recall memory

Memory blocks can be attached/detached from agents and shared across multiple agents simultaneously.

### Context Window Management

- Core memory blocks are pinned to the system prompt (always in-context)
- When context window fills, older messages auto-archive to recall memory
- Agent periodically consolidates memories by summarizing and prioritizing
- All state (memories, messages, reasoning, tool calls) persisted in database — never lost even when evicted from context

### Storage Backend

PostgreSQL with pgvector for the vector database backend. All state is persisted.

### Relevance to Deal-Scoped Systems

Strong conceptual fit. Core memory = active deal terms and key facts always visible to the agent. Archival memory = full deal history, document corpus, historical negotiations. Recall = conversation transcript. The self-managing aspect is powerful: the agent decides what deal facts are important enough for core memory vs. archival. Shared memory blocks could represent shared counterparty knowledge across deals.

---

## 5. Vector Stores as Memory Backends

### Pinecone

**Multi-tenancy via Namespaces** (recommended approach):
- One namespace per tenant provides **physical isolation**
- Queries scan only the target namespace (cost: 1 RU per 1 GB)
- No noisy-neighbor effects
- Namespace deletion for clean offboarding
- Scale: up to 100,000 namespaces (standard), millions with support
- Serverless architecture treats namespaces as fundamental isolation unit

**Alternative: Metadata Filtering**:
- Single namespace with tenant ID in metadata
- Higher cost: queries scan entire namespace regardless of filters
- `$in`/`$nin` operators capped at 10,000 values
- Use only for cross-tenant queries or non-strict isolation

**Deal-scoped pattern**: One namespace per deal. Counterparty vectors in a separate namespace accessible across deals.

### Weaviate

**Native Multi-Tenancy**:
- One shard per tenant with complete data isolation
- Each tenant has dedicated, high-performance vector index
- 50,000+ active tenants per node
- Three tenant states: Active, Inactive, Offloaded
- Inactive tenants moved to cheaper storage; offloaded tenants fully removed from memory
- GDPR-compliant isolation

**Deal-scoped pattern**: Create tenant per deal. Use tenant state management for deal lifecycle (active deals hot, closed deals offloaded).

### ChromaDB

- Lightweight, embeddable vector store
- Collections as primary namespace mechanism
- 2025 Rust rewrite: 4x faster writes/queries vs Python
- Persistent storage via `PersistentClient`
- Best for development/prototyping; less enterprise multi-tenancy support

**Deal-scoped pattern**: One collection per deal. Simpler but less isolation than Pinecone/Weaviate.

### Common Query Patterns for Agent Memory

All three support:
- Semantic similarity search (cosine, dot product, L2)
- Metadata filtering alongside vector search
- Upsert/update semantics for memory evolution
- Batch operations for bulk memory import

---

## 6. Microsoft AutoGen Memory

### Memory Protocol

AutoGen provides a `Memory` protocol interface:

- **`add`**: Add new entries to memory store
- **`query`**: Retrieve relevant information
- **`update_context`**: Mutate agent's internal model_context with retrieved info
- **`clear`**: Clear all entries
- **`close`**: Clean up resources

### Implementations

| Type | Backend | Features |
|------|---------|----------|
| ListMemory | In-memory list | Chronological, appends to context |
| ChromaDBVectorMemory | ChromaDB | Semantic search, configurable k and threshold |
| RedisMemory | Redis | Vector search, persistent |

### Scoping

Memory instances passed to individual agents via `memory` parameter as a list. Each agent maintains its own memory reference. Shared memory across agents is supported by passing the same memory instance.

### Microsoft Agent Framework Evolution (2025-2026)

Combines AutoGen's abstractions with Semantic Kernel's enterprise features:
- Session-based state management
- Graph-based workflows for multi-agent orchestration
- Pluggable memory modules: Redis, Pinecone, Qdrant, Weaviate, Elasticsearch, Postgres
- Foundry Agent Service adds persistent long-term memory layer

### Relevance to Deal-Scoped Systems

The pluggable memory protocol is useful — you can implement a custom `Memory` class that scopes to deal_id. However, AutoGen's memory system is less opinionated than Mem0 or Zep. The Microsoft Agent Framework's enterprise features (session management, telemetry, graph workflows) are more relevant for production financial services deployments.

---

## 7. Context-Scoped Memory Patterns

### Hierarchical Memory Scoping

Production systems implement multi-level scoping:

| Level | Scope | Lifetime | Example |
|-------|-------|----------|---------|
| Session | Single conversation | Minutes-hours | One negotiation call |
| Entity/Deal | Specific case/deal | Weeks-months | Credit agreement lifecycle |
| User/Counterparty | Specific party | Months-years | Relationship history |
| Organization | Tenant-wide | Permanent | Firm policies, templates |
| Global | All tenants | Permanent | Market data, regulations |

### Memory Isolation Patterns

1. **Per-deal namespacing**: All memories tagged with deal_id. Queries restricted to deal scope by default.
2. **Per-user isolation**: Queries search only within authenticated user's memory scope.
3. **Role-based access control**: Read/write/delete operations gated by role on memory stores.
4. **Namespace hierarchies**: `(org_id, team_id, deal_id, session_id)` for granular scoping.

### Cross-Context Memory Sharing

For the same counterparty across deals:
- **Counterparty-level memory namespace**: `(counterparty_id, "preferences")` accessible from any deal
- **Explicit promotion**: Agent promotes deal-specific insight to counterparty-level memory
- **Read-only cross-references**: Deal agents can read (not write) counterparty-level memory
- **Memory-as-a-Service (MaaS)**: Emerging paradigm where memory modules are shared across agents with controlled access

### Memory Decay and Archival

For long-running contexts (weeks/months):
- **Exponential decay**: Older memories weighted down by recency function (e.g., half-life of 30 days)
- **Importance scoring**: Combines recency weight, frequency score, user engagement metrics
- **TTL indexes**: MongoDB/Redis TTL for automatic removal of stale data
- **Tiered storage**: Working memory -> long-term storage -> cold archives
- **Active forgetting**: Memories actively removed based on relevance and recency
- **Privilege levels**: System Core (immutable) > Verified Admin (policies) > Learned preferences > Ephemeral session (24hr TTL)

### Private vs. Global Memory

| Type | Access | Examples |
|------|--------|---------|
| Deal-private | Only agents on that deal | Draft terms, internal notes, negotiation strategy |
| Counterparty-shared | All deals with that counterparty | Communication preferences, historical positions |
| Team-shared | All team members' agents | Playbooks, precedent terms |
| Global | All agents | Market data, regulatory rules, templates |

---

## 8. Graph-Based Memory

### Neo4j Agent Memory (neo4j-labs/agent-memory)

**Three Memory Types**:
1. **Short-Term**: Conversation history with semantic search and metadata filtering. Session-scoped.
2. **Long-Term**: Facts, preferences, entities using **POLE+O data model** (Person, Object, Location, Event, Organization). Temporal relationship tracking.
3. **Reasoning Memory**: Decision traces, tool calls, outcomes. Enables learning from past reasoning patterns.

**Entity Extraction Pipeline**:
- Multi-stage: spaCy + GLiNER2 + LLM-based extraction
- Entity resolution: exact matching, fuzzy matching, semantic similarity (type-aware)
- Provenance tracking: which extractors produced which entities
- Automatic deduplication on ingest with configurable auto-merge

**Advanced Features**:
- Vector + Graph search combining semantic similarity with graph traversal
- Geospatial queries on Location entities
- Relationship extraction via GLiREL (no LLM needed)
- Background entity enrichment via Wikipedia and Diffbot
- Streaming trace recording for real-time reasoning capture

### Graphiti (by Zep) on Neo4j

- Real-time, temporally-aware knowledge graph engine
- Incrementally processes incoming data without batch recomputation
- Episodic memory (specific events) + Semantic memory (generalized knowledge)
- Temporal awareness: tracks when information was captured and updated
- Community detection for entity clustering

### Knowledge Graphs for Financial Deal Tracking

**Context Graphs as "Systems of Agents"**:
- Enterprise value shifting from "systems of record" to "systems of agents"
- Context graph = living record of decision traces across entities and time
- Precedent becomes searchable
- KYC investigations: customers, accounts, transactions, devices as nodes with relationship edges

**Deal Tracking Data Model**:
```
(Deal)-[HAS_PARTY]->(Counterparty)
(Deal)-[GOVERNED_BY]->(Agreement)
(Agreement)-[CONTAINS]->(Term)
(Term)-[AMENDED_BY {date}]->(Amendment)
(Counterparty)-[REPRESENTED_BY]->(Counsel)
(Deal)-[HAS_CONDITION]->(ConditionPrecedent)
(ConditionPrecedent)-[STATUS {satisfied|waived|pending}]->()
```

---

## 9. Temporal / Event-Sourced Memory

### Event Sourcing as Agent Memory Pattern

**Core Architecture**:
- Every state change stored as a distinct event in an **append-only log**
- Event store is the single source of truth
- Current state derived by replaying events
- Events are immutable once written

**Mapping to Agent Memory**:

| Event Sourcing Concept | Agent Memory Equivalent |
|----------------------|------------------------|
| Event Store | Memory log (all observations, decisions, actions) |
| Aggregate | Deal/Case entity |
| Command | Agent action/decision |
| Event | Memory entry (fact learned, decision made, state changed) |
| Projection/Materialized View | Current deal summary, active terms, status dashboard |
| Snapshot | Periodic deal state snapshot for fast reconstruction |

**CQRS for Agent Memory**:
- **Write side (Command)**: Agent adds memories, records decisions, updates state. Optimized for throughput.
- **Read side (Query)**: Agent retrieves current state, searches history, generates summaries. Multiple read models from same event stream.
- Natural separation: write model captures everything, read models tailored for specific queries.

### Financial Services Application

**Instant Payments / Deal Lifecycle**:
- Efficient non-blocking writes (no contention from in-place updates)
- Built-in audit trail from immutable events
- Self-healing: replay events to recover state
- Temporal queries: reconstruct state at any point in time ("what were the terms on date X?")
- Multiple materialized views: compliance view, risk view, deal summary view

**Architecture**:
```
Agent Decision -> Command -> Event Store (append-only)
                                |
                    +-----------+-----------+
                    |           |           |
              Compliance    Deal Status   Audit Trail
              Projection    Projection    Projection
```

### Trade-offs

- Natural lag between writes and reads (eventual consistency)
- Event schema evolution requires careful versioning
- Storage grows unbounded (need snapshot + compaction strategy)
- Learning curve from traditional CRUD patterns

---

## 10. Production Patterns for Financial Services

### Deal-Level State Tracking

**Harvey.ai's Matter-Centric Isolation**:
- Each client matter is the atomic security unit
- All agents, documents, conversations, and work product scoped to specific matters
- Mirrors how firms organize work through matter numbers/billing codes
- **Fail-closed design**: agents skip documents they cannot confirm fall within matter boundaries
- Every document retrieval, context window, and agent session logged to specific matter

### Audit Trails for Agent Decisions

**Requirements**:
- Structured logs preserving decision lineage (not just application logs)
- Every autonomous decision logged promptly (missing traces = books-and-records violation)
- Discoverable evidence of compliance
- Contextual summaries with full provenance chain

**Implementation Pattern**:
1. Log every tool call, retrieval, and reasoning step
2. Tag each log entry with deal_id, agent_id, timestamp, user_id
3. Store in append-only audit log (event sourcing pattern)
4. Materialized views for compliance dashboards
5. Immutable once written, tamper-proof storage

### Regulatory Compliance Frameworks

| Regulation | AI Agent Impact |
|-----------|----------------|
| EU AI Act | High-risk classification for underwriting, trading, KYC. Requires documentation, monitoring, external auditability |
| SOX | Tamper-proof records, strict internal controls for AI agents in financial reporting |
| GDPR | Lawful processing, minimized data, transparent automated decisions, contestability |
| GLBA | Protects non-public consumer info at every AI data touchpoint |
| CCPA | Consumer rights: knowledge, access, deletion, opt-out for AI-processed data |
| FINRA/SEC/OCC | Auditability, operational resilience, human oversight of AI agents |
| PCI DSS | Payment data processing security for AI agents |

### Data Isolation / Information Barriers (Chinese Walls)

**Traditional Requirements**:
- Physical or logical separation between departments handling different deals
- Investment banking separated from research and trading
- Legal requirement to prevent conflicts of interest and insider trading

**AI Agent Implementation Challenges**:
1. **Data Access Independence**: Agents make autonomous retrieval decisions. An agent might access 50 documents, some falling behind ethical walls.
2. **Context Contamination Across Time**: Long-horizon agents maintain state across sessions — information from Deal A could influence Deal B.
3. **Monitoring at Scale**: Supervising humans cannot audit hundreds of documents an agent processes in minutes.

**Architecture Patterns**:
- **Matter/Deal-Centric Isolation**: All agent state scoped to deal_id. No cross-deal access without explicit authorization.
- **Integration with Existing Systems**: AI walls propagate from existing conflicts-checking platforms (e.g., Intapp).
- **Fail-Closed Design**: Agents must skip documents they cannot confirm fall within deal boundaries.
- **Separate Identity Domains**: Agents isolated in separate identity domains, applying least privilege by default.
- **Private VPC / On-Premises**: For regulated banks, metadata stays within customer perimeter.

**Microsoft's Agent Governance Framework**:
- Unique identity per agent (Microsoft Entra Agent Identity)
- Agent inventory to prevent shadow deployments
- Centralized logging to Azure Log Analytics
- Data Loss Prevention (DLP) policies and sensitivity labels
- Isolated environments: "corp" management group for internal, "online" for public
- Agents inherit user permissions; pass user identity/token for session integrity

### Key Design Principles for Deal-Scoped Agent Systems

1. **Deal as Aggregate Root**: All memory, decisions, and artifacts anchored to a deal entity
2. **Explicit Memory Promotion**: Facts move from session -> deal -> counterparty -> global only through deliberate agent or human action
3. **Temporal Awareness**: Every memory entry has valid_from/valid_to timestamps for deal evolution
4. **Append-Only Audit**: All agent actions logged immutably for regulatory compliance
5. **Fail-Closed Access**: When in doubt, deny cross-deal access and flag for human review
6. **Decay by Design**: Session memory TTL = hours; deal memory archived on close; counterparty memory reviewed annually
7. **Separation of Read/Write Models**: CQRS pattern for different stakeholder views of same deal

---

## Comparative Summary

| System | Memory Model | Scoping | Temporal | Graph | Storage | Best For |
|--------|-------------|---------|----------|-------|---------|----------|
| **Mem0** | Vector + optional graph | user/agent/session | Basic timestamps | Optional (Neo4j, etc.) | Vector DB + Graph DB | General agent memory with entity relationships |
| **Zep/Graphiti** | Temporal knowledge graph | Entity-level, episode-level | Bitemporal (4 timestamps) | Core architecture (Neo4j) | Neo4j | Long-running agents needing temporal reasoning |
| **LangGraph** | Checkpoints + Store | Thread + namespaced Store | Checkpoint timestamps | No | SQLite/Postgres/CosmosDB | Workflow orchestration with persistence |
| **Letta/MemGPT** | Core/Recall/Archival tiers | Agent-level blocks | Implicit via recall | Optional for archival | PostgreSQL + pgvector | Agents that self-manage their own memory |
| **Pinecone** | Vector embeddings | Namespaces (physical isolation) | Metadata only | No | Managed cloud | High-scale production with strict isolation |
| **Weaviate** | Vector embeddings | Multi-tenant shards | Metadata only | No | Self-hosted or cloud | Multi-tenant with tenant lifecycle |
| **AutoGen** | Pluggable Memory protocol | Per-agent instances | No | No | ChromaDB/Redis/custom | Multi-agent orchestration |
| **Neo4j Agent Memory** | POLE+O knowledge graph | Session/entity scoping | Temporal relationships | Core architecture | Neo4j | Entity-rich domains (financial, legal) |

---

## Recommended Architecture for Deal-Scoped Agent System

Based on this research, a deal-scoped agent system for financial services would combine:

1. **Memory Layer**: Mem0 or Zep/Graphiti for intelligent memory extraction with entity relationships and temporal tracking
2. **Orchestration**: LangGraph for workflow persistence with its Store providing cross-deal memory sharing via namespaces
3. **Vector Backend**: Pinecone (namespaces per deal) or Weaviate (tenant per deal) for strict isolation
4. **Knowledge Graph**: Neo4j for deal entity relationships, party tracking, and temporal term evolution
5. **Audit Layer**: Event sourcing pattern with append-only log, materialized views for compliance/risk/status
6. **Access Control**: Fail-closed design with deal-centric isolation, integrated with existing conflicts-checking systems
7. **Memory Lifecycle**: TTL-based decay for session memory, explicit archival for closed deals, annual review for counterparty memory

---

## Sources

### Mem0
- [Mem0 GitHub Repository](https://github.com/mem0ai/mem0)
- [Mem0 Research Paper (arXiv 2504.19413)](https://arxiv.org/abs/2504.19413)
- [Mem0 Graph Memory Documentation](https://docs.mem0.ai/open-source/features/graph-memory)
- [Graph Memory for AI Agents (January 2026)](https://mem0.ai/blog/graph-memory-solutions-ai-agents)
- [Mem0 Research — 26% Accuracy Boost](https://mem0.ai/research)

### Zep
- [Zep Temporal Knowledge Graph Paper (arXiv 2501.13956)](https://arxiv.org/abs/2501.13956)
- [Graphiti GitHub Repository](https://github.com/getzep/graphiti)
- [Zep State of the Art in Agent Memory](https://blog.getzep.com/state-of-the-art-agent-memory/)
- [Zep Platform](https://www.getzep.com/)

### LangGraph
- [LangGraph Persistence Documentation](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph v0.2 Checkpointer Libraries](https://blog.langchain.com/langgraph-v0-2/)
- [LangGraph Long-Term Memory Support](https://changelog.langchain.com/announcements/langgraph-long-term-memory-support)
- [Persistence in LangGraph — Deep Guide (Jan 2026)](https://pub.towardsai.net/persistence-in-langgraph-deep-practical-guide-36dc4c452c3b)
- [LangGraph + MongoDB Long-Term Memory](https://www.mongodb.com/company/blog/product-release-announcements/powering-long-term-memory-for-agents-langgraph)

### Letta/MemGPT
- [Letta Documentation — Intro to MemGPT](https://docs.letta.com/concepts/memgpt/)
- [Letta — Agent Memory Guide](https://www.letta.com/blog/agent-memory)
- [Adding Memory to LLMs with Letta (Feb 2025)](https://tersesystems.com/blog/2025/02/14/adding-memory-to-llms-with-letta/)
- [5 AI Agent Memory Systems Compared (2026)](https://dev.to/varun_pratapbhardwaj_b13/5-ai-agent-memory-systems-compared-mem0-zep-letta-supermemory-superlocalmemory-2026-benchmark-59p3)

### Vector Stores
- [Pinecone Multi-Tenancy Guide](https://docs.pinecone.io/guides/index-data/implement-multitenancy)
- [Pinecone Multi-Tenancy Concepts](https://www.pinecone.io/learn/series/vector-databases-in-production-for-busy-engineers/vector-database-multi-tenancy/)
- [Weaviate Multi-Tenancy Architecture](https://weaviate.io/blog/weaviate-multi-tenancy-architecture-explained)
- [Weaviate Tenant States](https://docs.weaviate.io/weaviate/manage-collections/tenant-states)

### Microsoft AutoGen
- [AutoGen Memory Documentation](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/memory.html)
- [Microsoft Agent Framework Overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [AutoGen — Microsoft Research](https://www.microsoft.com/en-us/research/project/autogen/)
- [Azure AI Agent Governance & Security](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization)

### Neo4j / Knowledge Graphs
- [Neo4j Agent Memory GitHub](https://github.com/neo4j-labs/agent-memory)
- [Graphiti on Neo4j Blog](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)
- [Context Graphs and Neo4j](https://medium.com/neo4j/hands-on-with-context-graphs-and-neo4j-8b4b8fdc16dd)
- [GraphRAG for KYC Investigations](https://neo4j.com/blog/developer/graphrag-in-action-know-your-customer/)

### Context-Scoped Memory
- [Memory for AI Agents: Context Engineering Paradigm](https://thenewstack.io/memory-for-ai-agents-a-new-paradigm-of-context-engineering/)
- [Memory as a Service (MaaS) Paper](https://arxiv.org/html/2506.22815v1)
- [AI Memory Security Best Practices](https://mem0.ai/blog/ai-memory-security-best-practices)
- [6 Best AI Agent Memory Frameworks (2026)](https://machinelearningmastery.com/the-6-best-ai-agent-memory-frameworks-you-should-try-in-2026/)
- [AWS AgentCore Long-Term Memory](https://aws.amazon.com/blogs/machine-learning/building-smarter-ai-agents-agentcore-long-term-memory-deep-dive/)

### Event Sourcing
- [Event Sourcing Pattern — Azure](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [CQRS & Event Sourcing in Financial Services](https://iconsolutions.com/blog/cqrs-event-sourcing)
- [Event Sourcing Explained (2025)](https://www.baytechconsulting.com/blog/event-sourcing-explained-2025)

### Financial Services Compliance
- [Harvey.ai — Long Horizon Agents and Ethical Walls](https://www.harvey.ai/blog/long-horizon-agents-and-ethical-walls)
- [AI Agent Compliance & Governance (Galileo)](https://galileo.ai/blog/ai-agent-compliance-governance-audit-trails-risk-management)
- [Compliance for AI Agents in Financial Services](https://www.bankingexchange.com/news-feed/item/10465-compliance-for-ai-agents-what-financial-services-organizations-need-to-know)
- [AI Agents in Regulated Industries (SS&C Blue Prism)](https://www.blueprism.com/resources/blog/ai-agents-regulated-industries/)
- [Insider Risk, Ethical Walls, Data Governance in Financial Services](https://blog.knowbe4.com/insider-risk-ethical-walls-and-the-future-of-data-governance-in-financial-services)
