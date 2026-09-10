# Existing System Architecture (Inherited from ELYSIA)

> Fill this in by INSPECTING the code, not guessing.
> Do NOT modify source files while writing this.

## Runtime
_TBD_

## Frontend
_TBD_

## Model integration (Gemini Live)
_TBD_

## Session management
_TBD_

## Tool system (registration + routing)
_TBD_

## Desktop execution
_TBD_

## Browser execution (Playwright)
_TBD_

## Python bridge
_TBD_

## Memory
_TBD_

## Safety / authorization boundary
_TBD_

## External integrations (Gmail / Calendar / Tasks)
_TBD_

## Startup flow
_TBD_

## Execution flow (intent -> tool call -> OS action -> response)
_TBD_

## Architecture diagram
\\\
(replace with a diagram that reflects the actual repo)
\\\
"@

New-DocIfMissing "docs/development/setup.md" @"
# Zarya Development Setup

## Prerequisites
- Node (version: TBD after inspecting package.json)
- Python (version: TBD)
- Playwright browsers
- API keys (see .env.example)

## Clone
\\\
git clone <zarya-repo-url>
cd Zarya
\\\

## Install
_TBD_

## Configure
_TBD_

## Run
_TBD_

## Verify
See docs/development/acceptance-tests.md
