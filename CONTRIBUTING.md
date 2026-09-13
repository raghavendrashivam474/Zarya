# Contributing to ZARYA

Thanks for your interest! Contributions and suggestions to Zarya are welcome.

## How to Contribute

1. **Fork** the repo
2. Create a feature branch: \git checkout -b feature/your-feature\
3. Make your changes
4. Run the checks:
   \\\ash
   npm run build       # Frontend & server build
   pytest -q           # Python agent regression suite
   \\\
5. Commit with a clear message
6. Push and open a Pull Request

## Code Style

- **TypeScript**: Prettier default formatting, no unused variables, strict mode
- **Python**: PEP 8, 4-space indentation
- No commented-out code or \console.log\/\print\ debug stubs
- Async for all I/O-bound Python tools

## Pull Request Checklist

- [ ] TypeScript builds clean (\
px tsc --noEmit\)
- [ ] Python tests pass (\pytest -q\)
- [ ] No hardcoded secrets or API keys
- [ ] If adding a tool: register in \gent/registry.py\ and add declaration in \server.ts\

## Reporting Issues

Open an issue at the repository tracker with:
- What you were doing
- What happened vs what you expected
- Relevant logs (check browser console + agent logs)
