# Baseline Regression Tests

Purpose: capture the CURRENT behavior of inherited components so that
we can detect regressions when we start improving.

## Rule
Every test in this folder tests INHERITED behavior.
Do not add tests for new Zarya features here — those go under \	ests/zarya/\.

## Structure
- \	ools/\     — one file per tool group
- \safety/\    — authorization / confirmation boundary tests
- \untime/\   — startup + session tests
