# S1 Verification Scope & Limitations

## Bounded Verification Scope
For the S1 milestone, Zarya implements post-launch process verification for desktop applications launched through the `openApplication` tool. 

### Operational Characteristics
- **Platform Focus**: Microsoft Windows platforms using the `tasklist` utility. Non-Windows systems (Linux, macOS) and environments where processes cannot be probed return a status of `UNKNOWN` gracefully.
- **Detection Method**: Bounded process image name polling. Max timeout is set to 3.0 seconds with check intervals every 0.5 seconds.
- **Contract Safety**: Added a non-breaking `verification` metadata payload adjacent to the traditional `result` string. This ensures existing agent models and interface parser integrations remain fully compatible.

## Limitations & Edge Cases

1. **UWP / AppX Spawning Patterns**:
   Some Windows Universal Platform apps (e.g., Calculator, Settings) spawn via intermediate system processes, or launch with custom background lifecycle handlers. Process names may vary or be hidden from basic `tasklist` queries, resulting in an `UNKNOWN` verification state.
   
2. **Helper/Wrapper Process Redirection**:
   Certain platforms (like VS Code running as a shell script .cmd wrapping native executables) require tracking the final graphical executable name (Code.exe) rather than the initial launcher PID. S1 uses the designated static image mapping from APP_COMMANDS to solve this mapping layer.

3. **No Lifecycle Tracking**:
   Verification is performed *immediately post-launch*. S1 does not track process health, crashes that occur after the 3-second window, or process exits.

4. **Closed-Loop Recovery**:
   There is no autonomous self-healing or relaunch execution path configured for VERIFIED_FAILURE states. S1 focuses solely on establishing high-fidelity outcome transparency.

## Future Path (S2+)
- Capture and retain explicit sub-process PIDs during backend launch.
- Implement post-action verification for filesystem writes and terminal-based mutations.
- Introduce closed-loop retry behaviors and agent planning actions based on VERIFIED_FAILURE signals.
