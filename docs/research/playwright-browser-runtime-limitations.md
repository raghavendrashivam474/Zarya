
Playwright Browser Runtime — Profile & Safety Limitations
Status: Active Invariant Documentation

1. Invariant: Profile Isolation
Zarya maintains a strict separation between daily human browsing and automated script execution:

Managed Default: Zarya’s automated tools default to managed mode. This session is persistent but runs in isolation inside ~/.zarya_browser_data.
No Daily Profile Pollution: Under no circumstances should Zarya's automated execution target your personal daily Chrome directory (%LOCALAPPDATA%\Google\Chrome\User Data) directly. This prevents profile-lock collisions and safeguards personal data/credentials.
2. Invariant: Explicit CDP Consent
If you want Zarya to interact with your active günlük/personal tabs and logins:

Explicit Selection: You must explicitly set ZARYA_BROWSER_MODE=cdp or invoke desktopBrowserSetMode(mode='cdp').
Active Port Requirements: You must manually launch Chrome on port 9222 (chrome.exe --remote-debugging-port=9222). Zarya will connect transparently but will never launch a new "ghost" process behind your back.
3. Invariant: Action Tracing
Automated page reads or clicks are bounded strictly by Playwright locator timeouts (default 30s).
Any manual profile logins executed inside the managed window persist securely across future executions.