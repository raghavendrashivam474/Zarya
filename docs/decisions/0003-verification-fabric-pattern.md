# ADR 0003: Multi-Domain Verification Fabric Strategy

## Status
Accepted

## Context and Problem Statement
Zarya requires post-condition verification of results across multiple execution domains (Applications, Filesystem, Terminal).
We must decide whether to build a centralized abstraction framework (base classes, strategy registries, factory interfaces) or extend S1's decentralized, helper-based return dict pattern.

## Decision Drivers
1. **Evidence-driven design:** S2 targets three domains with fundamentally divergent observation dynamics:
   - Application: Asynchronous process polling (up to 3s).
   - Filesystem: Synchronous file stat and content inspection (instant).
   - Terminal: Synchronous stdout/stderr string analysis (instant).
2. **Zero overhead:** Tool execution latency must remain minimal without introducing indirection overhead.
3. **Compatibility:** Dict payloads are native to Python tool handlers and serialize directly into JSON responses over WebSocket/HTTP.

## Decision
We select **Option A: Decentralized Domain Helpers with Shared Verification Contract Shape**.

Each domain tool module defines a dedicated helper (`_verify_file_created`, `_verify_terminal_execution`, `_verify_application_launched`) returning:

```json
{
  "status": "VERIFIED_SUCCESS | VERIFIED_FAILURE | UNKNOWN",
  "method": "<domain_method_name>",
  "detail": "<human_readable_explanation>",
  "observation": { "<domain_specific_evidence>" }
}
```
Consequences
Positive: Simple, zero-dependency, testable, fast. Preserves full backward compatibility with S0/S1.
Negative: Schema shape is governed by convention and regression test assertions rather than an enforced metaclass.
Mitigation: Comprehensive unit and contract tests in tests/test_s1_verification.py and tests/test_s2_verification.py.
