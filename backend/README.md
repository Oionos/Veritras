# Veritras Backend

Supply chain traceability backend for Veritras. Indexes blockchain events from Ethereum (Sepolia testnet) and serves analytics via a FastAPI REST API.

## Prerequisites

- Python 3.11+
- (Optional) Docker
- (Optional) PostgreSQL (SQLite is used by default for local development)

## Local Setup

1. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example environment file and fill in your values:
   ```bash
   cp .env.example .env
   ```

4. Run the application:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. Run tests:
   ```bash
   pytest
   ```

## Docker

Build and run with Docker:
```bash
docker build -t veritras-backend .
docker run -p 8000:8000 --env-file .env veritras-backend
```

## Database Migrations

Migrations are managed with [Alembic](https://alembic.sqlalchemy.org/). The configuration lives in `alembic.ini` and `alembic/env.py`.

### Quick Reference

Run pending migrations:
```bash
alembic upgrade head
```

Generate a new migration after changing models:
```bash
alembic revision --autogenerate -m "Add users table"
```

Downgrade one revision:
```bash
alembic downgrade -1
```

Show current revision:
```bash
alembic current
```

### Development Notes

- `Base.metadata.create_all()` in `app.main` is still active for local development, so the database will auto-create tables on startup. In hosted environments, run `python manage_schema.py --apply` as an explicit schema release before starting the API. `start_api.py` checks the schema head without applying DDL. See [canonical identity release](../CANONICAL_PRODUCT_IDENTITY.md).
- The `alembic/env.py` script imports all models from `app.models` so that `Base.metadata` is fully populated for autogenerate.
- Both SQLite and PostgreSQL are supported. The database URL is read dynamically from `app.core.config.settings.database_url`.

## Project Structure

```
backend/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   └── database.py
│   ├── models/
│   │   ├── product.py
│   │   └── shipment.py
│   ├── api/
│   │   └── routes/
│   │       ├── products.py
│   │       ├── shipments.py
│   │       └── analytics.py
│   └── services/
│       ├── indexer.py
│       └── analytics.py
├── tests/
├── alembic.ini
├── requirements.txt
└── Dockerfile
```

## Production Deployment

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg2://user:password@db:5432/veritras` |
| `ENVIRONMENT` | Set to `production` to enable production mode | `production` |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend domains | `https://veritras.vercel.app` |
| `SEPOLIA_RPC_URL` | Ethereum Sepolia RPC endpoint | `https://sepolia.infura.io/v3/...` |
| `PRODUCT_REGISTRY_CONTRACT` | Product registry contract address | `0x...` |
| `SHIPMENT_TRACKER_CONTRACT` | Shipment tracker contract address | `0x...` |

### Running with Gunicorn

The Docker image uses Gunicorn with Uvicorn workers by default:

```bash
docker build -t veritras-backend .
docker run -p 8000:8000 --env-file .env veritras-backend
```

Or run locally with Gunicorn:

```bash
gunicorn -c gunicorn.conf.py app.main:app
```

For local development, continue using uvicorn with auto-reload:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Database

In production, set `DATABASE_URL` to a PostgreSQL instance. The application automatically switches from SQLite to PostgreSQL based on the URL prefix.

## License

MIT

## Indexer startup and health

Use `/health/live` for hosting HTTP checks and `/health/ready` for dependency/indexer readiness. Initialization, confirmed-target lag, cursor progress and head freshness are reported separately. See [INDEXER_HEALTH.md](../INDEXER_HEALTH.md) for configuration, capped retries, safe diagnostics and bounded release probes. Production indexing remains disabled pending its separate enablement gate.

## Shipment exceptions

See [the exception guide](../SHIPMENT_EXCEPTIONS.md) for configurable rules, synchronization gates, acknowledgement/history, owner permissions and additive schema revision `e93a107bd624`. Open `/exceptions` or a shipment detail page. Production evaluation remains paused while indexing is disabled.
