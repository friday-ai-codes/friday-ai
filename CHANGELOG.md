# Changelog
All notable changes to Friday AI will be documented in this file.
This project follows [Semantic Versioning](https://semver.org/). The public
release line starts at `0.0.1`.
## [0.0.1] - 2026-06-05
### Added
- Initial open-source release baseline.
- MIT license, contribution guide, and security reporting policy.
- One-command local setup through `scripts/setup.sh`.
- Docker Compose deployment for Web, Server, Runner, PostgreSQL, Redis, and Qdrant.
- CI coverage reporting for backend and frontend tests.
- Playwright smoke e2e coverage for the web entrypoint.
- Secret scanning and Docker Compose configuration validation in CI.
### Changed
- Reset package versions to `0.0.1` for the public release line.
- Cleaned repository-level documentation for public contributors.
- Made Docker image prefix and tag configurable through environment variables.
### Removed
- Internal agent instructions, project docs, and obsolete release config from
 the public repository surface.
