# API Reference

Complete API documentation for SQLite CDC Sync Engine.

## Table of Contents

- [SyncEngine](#syncengine)
- [CDCConnection](#cdcconnection)
- [AuditReader](#auditreader)
- [Data Models](#data-models)
- [Utility Functions](#utility-functions)

## SyncEngine

The main synchronization engine responsible for coordinating the full synchronization process.

### Constructor

```python
SyncEngine(config: SyncConfig)
```

**Parameters:**

- `config` (SyncConfig): Synchronization configuration object

**Example:**

```python
from sqlite_cdc import SyncEngine, load_config

config = await load_config("sync.yaml")
engine = SyncEngine(config)
```

### Methods

#### start()

```python
async def start(
    tables: Optional[List[str]] = None,
    run_initial: bool = True
) -> None
```

Start the synchronization engine.

**Parameters:**

- `tables` (Optional[List[str]]): Specify the list of tables to synchronize; if None, synchronize all tables in the configuration
- `run_initial` (bool): Whether to execute initial synchronization; defaults to True

**Example:**

```python
# Full sync + incremental sync
await engine.start()

# Only incremental sync
await engine.start(run_initial=False)

# Sync specified tables only
await engine.start(tables=["users", "orders"])
```

#### stop()

```python
async def stop() -> None
```

Stop the synchronization engine.

**Example:**

```python
await engine.stop()
```

#### is_running()

```python
def is_running() -> bool
```

Check if the engine is running.

**Returns:**

- `bool`: Returns True if running

#### get_status()

```python
def get_status() -> SyncStatus
```

Get the current synchronization status.

**Returns:**

- `SyncStatus`: Status object containing state, source database, and target list

**Example:**

```python
status = engine.get_status()
print(f"Status: {status.state}")
print(f"Source Database: {status.source_db}")
print(f"Target List: {status.targets}")
```

---

## CDCConnection

Wraps a SQLite connection to automatically record audit logs.

### Constructor

```python
CDCConnection(
    conn: sqlite3.Connection,
    audit_table: str = "_cdc_audit_log",
    enabled_tables: Optional[List[str]] = None
)
```

**Parameters:**

- `conn` (sqlite3.Connection): Native SQLite connection
- `audit_table` (str): Audit table name; defaults to `_cdc_audit_log`
- `enabled_tables` (Optional[List[str]]): List of tables to audit; empty means all tables

**Example:**

```python
import sqlite3
from sqlite_cdc import CDCConnection

raw_conn = sqlite3.connect("app.db")
cdc_conn = CDCConnection(raw_conn, enabled_tables=["users", "orders"])
```

### Methods

#### execute()

```python
def execute(
    sql: str,
    parameters: Union[tuple, dict, list] = ()
) -> sqlite3.Cursor
```

Execute SQL statements and automatically record audit logs.

**Parameters:**

- `sql` (str): SQL statement
- `parameters`: SQL parameters

**Returns:**

- `sqlite3.Cursor`: Cursor object

**Example:**

```python
# INSERT
cdc_conn.execute(
    "INSERT INTO users (name, email) VALUES (?, ?)",
    ("Zhang San", "zhangsan@example.com")
)

# UPDATE
cdc_conn.execute(
    "UPDATE users SET email = ? WHERE id = ?",
    ("new@example.com", 1)
)

# DELETE
cdc_conn.execute("DELETE FROM users WHERE id = ?", (1,))

cdc_conn.commit()
```

#### executemany()

```python
def executemany(
    sql: str,
    parameters: List[Union[tuple, dict]]
) -> sqlite3.Cursor
```

Execute SQL statements in batch and record audit logs.

#### commit() / rollback()

```python
def commit() -> None
def rollback() -> None
```

Transaction control methods.

#### close()

```python
def close() -> None
```

Close the connection.

### Context Manager Support

```python
with CDCConnection(raw_conn) as cdc:
    cdc.execute("INSERT INTO users (name) VALUES (?)", ("Zhang San",))
    # Automatically commit
```

---

## AuditReader

Reads change events from the audit log table.

### Constructor

```python
AuditReader(
    conn: sqlite3.Connection,
    batch_size: int = 100,
    poll_interval: float = 1.0,
    audit_table: str = "_cdc_audit_log"
)
```

**Parameters:**

- `conn` (sqlite3.Connection): SQLite connection
- `batch_size` (int): Batch read size
- `poll_interval` (float): Polling interval (seconds)
- `audit_table` (str): Audit table name

### Methods

#### start()

```python
async def start(from_id: int = 0) -> None
```

Start the reader.

**Parameters:**

- `from_id` (int): Start reading from the specified audit ID

#### stop()

```python
async def stop() -> None
```

Stop the reader.

#### fetch_batch()

```python
async def fetch_batch() -> List[ChangeEvent]
```

Fetch a batch of change events.

**Returns:**

- `List[ChangeEvent]`: List of change events

**Example:**

```python
reader = AuditReader(conn)
await reader.start(from_id=0)

events = await reader.fetch_batch()
for event in events:
    print(f"{event.operation}: {event.table_name} #{event.row_id}")

await reader.stop()
```

#### mark_consumed()

```python
def mark_consumed(audit_ids: List[int]) -> None
```

Mark audit records as consumed.

**Parameters:**

- `audit_ids` (List[int]): List of audit record IDs

---

## Data Models

### SyncConfig

Synchronization configuration root object.

```python
class SyncConfig(BaseModel):
    source: SQLiteConfig                    # Source database configuration
    targets: List[TargetConfig]             # Target database list
    mappings: List[TableMapping]            # Table mapping list
    batch_size: int = 100                   # Batch size
    checkpoint_interval: int = 10          # Checkpoint interval
    log_level: str = "INFO"               # Log level
    checkpoint_dir: str = "checkpoints"   # Checkpoint directory
```

### ChangeEvent

Change event object.

```python
class ChangeEvent(BaseModel):
    event_id: str                          # Event ID
    audit_id: int                          # Audit record ID
    operation: OperationType              # Operation type: INSERT/UPDATE/DELETE
    table_name: str                       # Table name
    row_id: Union[int, str]              # Row ID
    before_data: Optional[Dict]          # Data before change
    after_data: Optional[Dict]           # Data after change
```

### TableMapping

Table mapping configuration.

```python
class TableMapping(BaseModel):
    source_table: str                      # Source table name
    target_table: Optional[str]          # Target table name; defaults to source table name
    primary_key: str = "id"              # Primary key
    field_mappings: List[FieldMapping]   # Field mapping list
    filter_condition: Optional[str]     # Filter condition
```

### FieldMapping

Field mapping configuration.

```python
class FieldMapping(BaseModel):
    source_field: str                      # Source field name
    target_field: Optional[str]          # Target field name; defaults to source field name
    converter: Optional[ConverterType]  # Converter type
    converter_params: Dict = {}         # Converter parameters
```

---

## Utility Functions

### load_config()

```python
async def load_config(path: str) -> SyncConfig
```

Load a configuration file.

**Parameters:**

- `path` (str): Path to the configuration file

**Returns:**

- `SyncConfig`: Configuration object

**Example:**

```python
from sqlite_cdc import load_config

config = await load_config("sync.yaml")
```

### Converters

Built-in field converters.

#### lowercase

Converts string to lowercase.

```python
from sqlite_cdc.utils.converters import convert
from sqlite_cdc.models.sync_config import ConverterType

result = convert("HELLO", ConverterType.LOWERCASE, {})
# Returns: "hello"
```

#### uppercase

Converts string to uppercase.

```python
result = convert("hello", ConverterType.UPPERCASE, {})
# Returns: "HELLO"
```

#### trim

Removes whitespace from both ends of a string.

```python
result = convert("  hello  ", ConverterType.TRIM, {})
# Returns: "hello"
```

#### default

If the value is None or an empty string, return the default value.

```python
result = convert(None, ConverterType.DEFAULT, {"value": "default_value"})
# Returns: "default_value"
```

#### typecast

Type conversion.

```python
# String to integer
result = convert("123", ConverterType.TYPECAST, {"target_type": "int"})
# Returns: 123

# Integer to string
result = convert(123, ConverterType.TYPECAST, {"target_type": "str"})
# Returns: "123"

# String to float
result = convert("3.14", ConverterType.TYPECAST, {"target_type": "float"})
# Returns: 3.14
```

---

## Usage Examples

### Complete Synchronization Flow

```python
import asyncio
from sqlite_cdc import SyncEngine, load_config

async def sync_data():
    # Load configuration
    config = await load_config("sync.yaml")

    # Create engine
    engine = SyncEngine(config)

    try:
        # Start sync
        await engine.start(run_initial=True)

        # View status
        while engine.is_running():
            status = engine.get_status()
            print(f"Status: {status.state}")
            await asyncio.sleep(5)

    except KeyboardInterrupt:
        # Graceful stop
        await engine.stop()

if __name__ == "__main__":
    asyncio.run(sync_data())
```

### Manual Audit Log Reading

```python
import sqlite3
import asyncio
from sqlite_cdc.core.audit_reader import AuditReader

async def read_changes():
    conn = sqlite3.connect("source.db")

    reader = AuditReader(conn, batch_size=10)
    await reader.start(from_id=0)

    try:
        while True:
            events = await reader.fetch_batch()

            for event in events:
                print(f"[{event.operation}] {event.table_name}")
                print(f"  Row ID: {event.row_id}")

                if event.before_data:
                    print(f"  Before: {event.before_data}")
                if event.after_data:
                    print(f"  After: {event.after_data}")

            # Mark as consumed
            if events:
                await reader.mark_consumed([e.audit_id for e in events])

    except KeyboardInterrupt:
        await reader.stop()
        conn.close()

asyncio.run(read_changes())
```
