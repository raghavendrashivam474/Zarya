# Zarya Development Setup (Inherited Baseline)

## Runtime Prerequisites
- **Node.js**: LTS (>= 20)
- **Package Manager**: npm
- **Python**: Python 3.10+

## Available Scripts in package.json
- `dev`: tsx server.ts
- `build`: vite build && esbuild server.ts --bundle --platform=node --format=cjs --sourcemap --outfile=dist/server.cjs
- `start`: node dist/server.cjs
- `preview`: vite preview
- `clean`: rm -rf dist server.js
- `lint`: tsc --noEmit

## Required Environment Variables


## Quick Start
1. Install dependencies: `npm install`
2. Setup browsers: `npx playwright install`
3. Copy environment file: `cp .env.example .env`
4. Start development server: `npm run dev`
