# S3 Limitations: Computer State Model

## 1. Scope and Design Boundaries
S3 strictly establishes the substrate for representing, caching, and evaluating the freshness of computer state. It intentionally defers complex state-orchestration mechanisms to subsequent milestones.

## 2. Identified Limitations

### 1. In-Memory Persistence Lifetime
The `StateCache` is in-memory and bound to the agent process runtime. Observations do not persist across agent restarts or system reboots.
*Mitigation / Roadmap:* Persistent context storage will be evaluated in S7 (Context Memory).

### 2. Lack of Active Background Subscriptions / Push Notifications
State is captured strictly on-demand (either when an action is dispatched or when explicitly probed). If an external actor or process modifies a file or closes an application outside Zarya's knowledge, the cache will retain the stale observation until freshness decay triggers a refresh.
*Design rationale:* Continuous file watching and process monitoring are resource-heavy and unnecessary for single-task workflows.

### 3. Exit Code Absence in Terminal State
As established in S2, the Windows backend runs commands without capturing granular exit codes directly. Terminal state observations remain based on stdout/stderr output heuristics rather than OS-level process return codes.

### 4. Uniform Freshness Thresholds
The current freshness heuristic defaults to a standard 30-second window across all domains. In practice, file system changes happen at different temporal frequencies than application lifecycles or network sockets. Domain-customized decay profiles are deferred until multi-step task workflows demonstrate the requirement in S6.
