# Quick Start Guide

This guide will help you quickly get started with the SQLite CDC Sync Engine.

## Installation

```bash
pip install sqlite-cdc
```

## Prerequisites

### 1. SQLite Must Use WAL Mode

CDC functionality requires SQLite to be in WAL (Write-Ahead Logging) mode:

```sql
-- Enable WAL mode in SQLite
PRAGMA journal_mode=WAL;
```

Or configure it via Python:

```python
import sqlite3
conn = sqlite3.connect("source.db")
conn.execute("PRAGMA journal_mode=WAL")
conn.close()
```

### 2. Prepare Target Database

Ensure the target MySQL/Oracle database and tables are already created.

## Quick Start

### Step 1: Initialize Configuration File

```bash
sqlite-cdc init sync.yaml
```

This will generate a configuration template; modify it according to your actual environment.

### Step 2: Edit Configuration

```yaml
source:
  db_path: "./source.db"
  tables: ["users", "orders"]

targets:
  - name: "mysql_backup"
    type: "mysql"
    connection:
      host: "localhost"
      port: 3306
      database: "cdc_backup"
      username: "${MYSQL_USER}"
      password: "${MYSQL_PASSWORD}"

mappings:
  - source_table: "users"
    target_table: "users_backup"

batch_size: 100
checkpoint_interval: 10
```

### Step 3: Validate Configuration

```bash
sqlite-cdc validate --config sync.yaml
```

### Step 4: Execute Sync

**Full Sync (Full Sync + Incremental Sync):**

```bash
sqlite-cdc sync --config sync.yaml --mode full
```

**Initial Sync Only (Migrate existing data):**

```bash
sqlite-cdc sync --config sync.yaml --mode initial
```

**Incremental Sync Only (Process new changes):**

```bash
sqlite-cdc sync --config sync.yaml --mode incremental
```

### Step 5: View Sync Status

```bash
sqlite-cdc status --config sync.yaml
```

## Python Library Usage

### Basic Example

```python
import asyncio
from sqlite_cdc import SyncEngine, load_config

async def main():
    # Load configuration
    config = await load_config("sync.yaml")

    # Create sync engine
    engine = SyncEngine(config)

    # Start sync (full sync + incremental sync)
    await engine.start()

if __name__ == "__main__":
    asyncio.run(main())
```

### Using CDCConnection

Use `CDCConnection` to automatically record audit logs in your application:

```python
import sqlite3
from sqlite_cdc import CDCConnection

# Wrap the regular connection
raw_conn = sqlite3.connect("source.db")
cdc_conn = CDCConnection(raw_conn, enabled_tables=["users"])

# Execute SQL; CDC automatically records changes
cdc_conn.execute(
    "INSERT INTO users (name, email) VALUES (?, ?)",
    ("Zhang San", "zhangsan@example.com")
)
cdc_conn.commit()
cdc_conn.close()
```

## Common Issues

### Issue 1: "CDC requires SQLite must use WAL mode"

**Solution:**

```sql
PRAGMA journal_mode=WAL;
```

### Issue 2: "Target table does not exist"

**Solution:** Manually create the target table first, ensuring the structure matches the source table.

### Issue 3: Resume from breakpoint after interruption

Sync engine automatically saves progress. Restart the sync command to resume from the breakpoint:

```bash
sqlite-cdc sync --config sync.yaml --mode full
```

### Issue 4: Reset breakpoint

If you need to re-sync from scratch:

```bash
sqlite-cdc reset --config sync.yaml --table users
```

## Next Steps

- View [Configuration Details](configuration.md) for a complete configuration guide
- View [API Reference](API.md) for programmatic usage
