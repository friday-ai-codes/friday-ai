# Security Policy
## Supported Versions
Security fixes target the current public release line:
| Version | Supported |
| --- | --- |
| `0.0.x` | yes |
## Reporting a Vulnerability
Please do not open a public issue for a vulnerability or suspected secret leak.
Use GitHub Security Advisories for this repository when available, or contact a
maintainer privately with:
- A short description of the issue.
- Reproduction steps or proof of impact.
- Affected versions, commit hashes, or deployment details.
- Any logs or screenshots with secrets redacted.
We will acknowledge valid reports as quickly as possible and coordinate a fix
before public disclosure.
## Secret Handling
Never commit `.env`, database files, service account keys, personal access tokens,
customer data exports, or production logs. If a secret is committed by accident:
1. Rotate or revoke the secret immediately.
2. Remove it from history with a history-rewrite tool.
3. Run secret scanning before pushing the cleaned history.
4. Notify affected maintainers or users if data exposure may have occurred.
