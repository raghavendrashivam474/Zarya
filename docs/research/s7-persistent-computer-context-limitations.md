# S7 Persistent Computer Context Limitations

## Out of Scope (Explicit Boundaries)

### 1. Vector Search & Semantic Embeddings
S7 does not perform semantic, natural-language, or vector search. Retrieval is purely deterministic and database-driven (filtering by domain, subject, type, work ID, and time). This prevents "fuzzy matching" from retrieving incorrect contexts.

### 2. Conversational Memory
Zarya's conversational interaction log, user personality profiles, and chat history are explicitly excluded. S7 is strictly a **Computer Context** store, capturing what happened on the operating system, file system, and step execution pipelines.

### 3. Credentials and Secret Scrubbing
S7 must not be used to store passwords, auth tokens, API keys, or active credentials. Tool argument serialization in the parent process must scrub these fields before they reach the execution pipeline, and S7 records only capture the verified metadata.

### 4. Continuous Background Observation
S7 does not run a background daemon or hook into OS-level filesystem watcher events (like Windows ReadDirectoryChanges). It is strictly **event-driven**, persisting observations when tools are explicitly invoked by Zarya.

## Technical Constraints

### 1. Concurrency
SQLite supports concurrent reads but serializes writes. Since Zarya executes tasks in a single-agent linear fashion, this constraint does not impact performance. A thread lock is included in `MemoryStore` to make thread-safe execution deterministic.

### 2. File Lock / Permission Failures
If Zarya is executed in a highly restricted container or environment where writing to local app data directories is blocked, the context store will automatically degrade to `MEMORY_UNAVAILABLE`. While persistence will not function in this mode, multi-step actions (S6) and tools will continue to run without interruption.
