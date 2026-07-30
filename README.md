# DeepInsight

DeepInsight is an AI-native, multi-market investment research platform.

Phase One is limited to generating standardized investment research reports.
Trading, order execution, portfolio optimization, backtesting, strategy
generation, and model training are outside the MVP scope.

## Repository layout

- `apps/`: deployable API, scheduler, worker, and web applications
- `config/`: application and provider configuration
- `data/`: local runtime data, indexes, snapshots, and backups
- `docs/`: specifications, engineering documentation, and task definitions
- `infra/`: Docker, Compose, and reserved infrastructure definitions
- `scripts/`: repository maintenance and operational scripts
- `src/`: backend application packages
- `tests/`: unit, integration, and test fixture packages

The repository currently contains scaffold files only. No business logic has
been implemented.
