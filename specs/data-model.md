# 数据模型设计: SQLite CDC 同步引擎

**日期**: 2026-02-07
**关联**: [spec.md](./spec.md), [research.md](./research.md)

---

## 实体关系图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SyncConfig (配置根对象)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  source: SQLiteConfig ─────────────┐                                        │
│  targets: List[TargetConfig] ──┐   │                                        │
│  mappings: List[TableMapping]  │   │                                        │
│  batch_size: int               │   │                                        │
│  checkpoint_interval: int      │   │                                        │
└────────────────────────────────┼───┼────────────────────────────────────────┘
                                 │   │
                                 ▼   ▼
┌──────────────────┐    ┌──────────────────┐
│  SQLiteConfig    │    │  TargetConfig    │
├──────────────────┤    ├──────────────────┤
│  db_path: str    │    │  name: str       │
│  journal_mode:   │    │  type: TargetType│
│    str = "WAL"   │    │  connection:     │
├──────────────────┤    │    ConnectionConfig│
│  tables: List    │    │  batch_size: int │
│  [str]           │    │  retry_policy:   │
└──────────────────┘    │    RetryPolicy   │
                        └──────────────────┘
                                 │
           ┌─────────────────────┴─────────────────────┐
           ▼                                           ▼
┌─────────────────────┐                    ┌─────────────────────┐
│  MySQLConnection    │                    │  OracleConnection   │
├─────────────────────┤                    ├─────────────────────┤
│  host: str          │                    │  host: str          │
│  port: int          │                    │  port: int          │
│  database: str      │                    │  service_name: str  │
│  username: str      │                    │  username: str      │
│  password: str      │                    │  password: str      │
└─────────────────────┘                    └─────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          TableMapping (表映射)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  source_table: str ──────────────────┐                                      │
│  target_table: str                   │                                      │
│  field_mappings: List[FieldMapping] ─┼──┐                                   │
│  filter_condition: str (可选)        │   │                                   │
└──────────────────────────────────────┼───┼───────────────────────────────────┘
                                       │   │
                                       ▼   │
                              ┌─────────────────────┐
                              │   FieldMapping       │
                              ├─────────────────────┤
                              │  source_field: str   │
                              │  target_field: str   │
                              │  converter: str (可选)│
                              │  default_value: Any  │
                              └─────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          AuditLog (审计日志表)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  业务库 _cdc_audit_log 表，存储变更记录                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  id: INTEGER PK (AUTOINCREMENT) ← 消费断点                                  │
│  table_name: TEXT                                                           │
│  operation: TEXT (INSERT/UPDATE/DELETE)                                     │
│  row_id: TEXT                                                               │
│  before_data: JSON                                                          │
│  after_data: JSON                                                           │
│  created_at: TIMESTAMP                                                      │
│  consumed_at: TIMESTAMP (NULL = 未消费)                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       │ CDCConnection 拦截写入
                                       │ 并自动生成记录
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CDCConnection (连接包装器)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  包装 sqlite3.Connection，拦截 INSERT/UPDATE/DELETE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  _conn: sqlite3.Connection                                                  │
│  _audit_table: str = "_cdc_audit_log"                                       │
│  _enabled_tables: Set[str]                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  execute(sql, params) -> Cursor  ──────┐                                    │
│  _write_audit_log(...)                 │                                    │
│  _parse_sql(sql) -> (op, table)        │                                    │
└────────────────────────────────────────┼────────────────────────────────────┘
                                       │ 生成审计记录
                                       ▼
                                AuditLog (表)
```

---

## 核心实体定义

### 1. SyncConfig (同步配置)

配置根对象，定义整个同步任务的参数。

```python
class SyncConfig(BaseModel):
    """
    CDC 同步配置根对象

    属性:
        source: 源 SQLite 数据库配置
        targets: 目标数据库配置列表（支持多个目标）
        mappings: 表映射规则列表
        batch_size: 批量写入大小，默认 100
        checkpoint_interval: 断点刷新间隔（事件数），默认 10
        log_level: 日志级别，默认 INFO
    """
    source: SQLiteConfig
    targets: List[TargetConfig] = Field(min_length=1)
    mappings: List[TableMapping] = Field(min_length=1)
    batch_size: int = Field(default=100, ge=1, le=1000)
    checkpoint_interval: int = Field(default=10, ge=1)
    log_level: str = Field(default="INFO")
```

**验证规则**:
- `targets` 至少包含一个目标
- `mappings` 至少包含一个表映射
- `batch_size` 范围 1-1000

---

### 2. SQLiteConfig (源数据库配置)

```python
class SQLiteConfig(BaseModel):
    """
    SQLite 源数据库配置

    属性:
        db_path: SQLite 数据库文件路径
        journal_mode: 日志模式，必须为 WAL
        tables: 需要同步的表名列表，为空表示同步所有表
        wal_path: WAL 文件路径（可选，默认自动推导）
    """
    db_path: str = Field(..., description="SQLite 数据库文件路径")
    journal_mode: Literal["WAL"] = Field(default="WAL", description="日志模式，必须为 WAL")
    tables: List[str] = Field(default=[], description="同步表列表，空表示所有表")
    wal_path: Optional[str] = Field(default=None, description="WAL 文件路径")

    @field_validator("db_path")
    @classmethod
    def validate_db_exists(cls, v: str) -> str:
        if not os.path.exists(v):
            raise ValueError(f"数据库文件不存在: {v}")
        return v

    @field_validator("journal_mode")
    @classmethod
    def validate_wal_mode(cls, v: str) -> str:
        if v != "WAL":
            raise ValueError("CDC 要求 SQLite 必须使用 WAL 模式")
        return v
```

**验证规则**:
- `db_path` 必须指向存在的文件
- `journal_mode` 必须为 WAL (CDC 依赖 WAL 日志)

---

### 3. TargetConfig (目标数据库配置)

```python
class TargetType(str, Enum):
    """目标数据库类型"""
    MYSQL = "mysql"
    ORACLE = "oracle"

class TargetConfig(BaseModel):
    """
    目标数据库配置

    属性:
        name: 目标名称，用于标识
        type: 数据库类型 (mysql/oracle)
        connection: 连接配置
        batch_size: 此目标的批量大小（覆盖全局配置）
        retry_policy: 重试策略
    """
    name: str = Field(..., min_length=1, description="目标名称标识")
    type: TargetType
    connection: Union[MySQLConnection, OracleConnection] = Field(
        ..., discriminator="type"
    )
    batch_size: Optional[int] = Field(default=None, ge=1, le=1000)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)

class RetryPolicy(BaseModel):
    """
    重试策略配置

    属性:
        max_retries: 最大重试次数，默认 3
        backoff_factor: 退避系数，默认 1.0
        max_delay: 最大退避延迟(秒)，默认 60
    """
    max_retries: int = Field(default=3, ge=0)
    backoff_factor: float = Field(default=1.0, ge=0)
    max_delay: int = Field(default=60, ge=1)
```

**验证规则**:
- `name` 不能为空，且在全局唯一
- 连接配置根据 `type` 自动选择对应模型

---

### 4. ConnectionConfig (连接配置)

```python
class MySQLConnection(BaseModel):
    """MySQL 连接配置"""
    model_config = ConfigDict(title="MySQL Connection")
    type: Literal["mysql"] = "mysql"
    host: str
    port: int = Field(default=3306, ge=1, le=65535)
    database: str
    username: str
    password: str
    charset: str = Field(default="utf8mb4")
    pool_size: int = Field(default=5, ge=1, le=50)

class OracleConnection(BaseModel):
    """Oracle 连接配置"""
    model_config = ConfigDict(title="Oracle Connection")
    type: Literal["oracle"] = "oracle"
    host: str
    port: int = Field(default=1521, ge=1, le=65535)
    service_name: str
    username: str
    password: str
    pool_size: int = Field(default=5, ge=1, le=50)
```

---

### 5. TableMapping (表映射)

```python
class TableMapping(BaseModel):
    """
    表级映射配置

    属性:
        source_table: 源表名
        target_table: 目标表名（默认同源表名）
        field_mappings: 字段映射列表
        filter_condition: 过滤条件 SQL（可选）
        primary_key: 主键字段名（默认 "id"）
    """
    source_table: str = Field(..., min_length=1)
    target_table: Optional[str] = Field(default=None)
    field_mappings: List[FieldMapping] = Field(default=[])
    filter_condition: Optional[str] = Field(
        default=None,
        description="行级过滤条件，如: status = 'active'"
    )
    primary_key: str = Field(default="id", description="主键字段名，用于幂等判断")

    @model_validator(mode="after")
    def set_default_target(self):
        if self.target_table is None:
            self.target_table = self.source_table
        return self
```

**验证规则**:
- `source_table` 不能为空
- 如果 `target_table` 为空，默认使用 `source_table`

---

### 6. FieldMapping (字段映射)

```python
class ConverterType(str, Enum):
    """字段转换器类型"""
    LOWERCASE = "lowercase"           # 转为小写
    UPPERCASE = "uppercase"           # 转为大写
    TRIM = "trim"                     # 去除空白
    DEFAULT = "default"               # 默认值
    TYPECAST = "typecast"             # 类型转换
    CUSTOM = "custom"                 # 自定义表达式

class FieldMapping(BaseModel):
    """
    字段级映射配置

    属性:
        source_field: 源字段名
        target_field: 目标字段名（默认同源字段名）
        converter: 转换器类型（可选）
        converter_params: 转换器参数
    """
    source_field: str = Field(..., min_length=1)
    target_field: Optional[str] = Field(default=None)
    converter: Optional[ConverterType] = Field(default=None)
    converter_params: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def set_default_target(self):
        if self.target_field is None:
            self.target_field = self.source_field
        return self

    @field_validator("converter_params")
    @classmethod
    def validate_converter_params(cls, v: Dict, info) -> Dict:
        # 根据 converter 类型验证参数
        converter = info.data.get("converter")
        if converter == ConverterType.DEFAULT and "value" not in v:
            raise ValueError("default 转换器必须提供 value 参数")
        return v
```

---

### 7. ChangeEvent (变更事件)

运行时事件对象，表示一次数据变更。

```python
class OperationType(str, Enum):
    """数据库操作类型"""
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

class ChangeEvent(BaseModel):
    """
    变更事件对象

    表示 SQLite WAL 中捕获的单行数据变更。
    此对象是 CDC 系统的核心数据流单元。

    属性:
        event_id: 全局唯一事件标识 (格式: "{audit_id}:{table_name}:{row_id}")
        audit_id: 审计日志序列号，用于排序和断点恢复
        timestamp: 事件捕获时间戳
        operation: 操作类型 (INSERT/UPDATE/DELETE)
        table_name: 源表名
        row_id: 主键值
        before_data: 变更前数据 (UPDATE/DELETE 时有值)
        after_data: 变更后数据 (INSERT/UPDATE 时有值)

    示例:
        ```python
        event = ChangeEvent(
            event_id="12345:users:42",
            audit_id=12345,
            timestamp=datetime.now(),
            operation=OperationType.INSERT,
            table_name="users",
            row_id=42,
            after_data={"id": 42, "name": "张三", "email": "zhang@example.com"}
        )
        ```
    """
    event_id: str = Field(..., description="全局唯一事件标识")
    audit_id: int = Field(..., ge=0, description="审计日志序列号")
    timestamp: datetime = Field(default_factory=datetime.now)
    operation: OperationType
    table_name: str
    row_id: Union[int, str]
    before_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="变更前数据快照"
    )
    after_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="变更后数据快照"
    )

    @model_validator(mode="after")
    def validate_event_id(self):
        expected = f"{self.audit_id}:{self.table_name}:{self.row_id}"
        if self.event_id != expected:
            raise ValueError(f"event_id 格式错误，期望: {expected}, 实际: {self.event_id}")
        return self

    @model_validator(mode="after")
    def validate_data_consistency(self):
        if self.operation == OperationType.INSERT and self.after_data is None:
            raise ValueError("INSERT 操作必须提供 after_data")
        if self.operation == OperationType.DELETE and self.before_data is None:
            raise ValueError("DELETE 操作必须提供 before_data")
        return self

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，用于序列化"""
        return self.model_dump()
```

**验证规则**:
- `event_id` 必须符合格式 `{audit_id}:{table_name}:{row_id}`
- `INSERT` 必须提供 `after_data`
- `DELETE` 必须提供 `before_data`
- `audit_id` 必须 >= 0

---

### 8. SyncPosition (同步位置)

断点信息实体，用于故障恢复。

```python
class SyncPosition(BaseModel):
    """
    同步位置（断点）信息

    用于记录同步进度，支持故障恢复。

    属性:
        source_db_path: 源数据库路径
        target_name: 目标名称
        last_audit_id: 最后处理的 审计日志序列号
        last_processed_at: 最后处理时间
        total_events: 已处理事件总数
    """
    source_db_path: str
    target_name: str
    last_audit_id: int = Field(default=0, ge=0)
    last_processed_at: datetime = Field(default_factory=datetime.now)
    total_events: int = Field(default=0, ge=0)

    class Config:
        # SQLAlchemy 表映射配置
        from_attributes = True
```

---

### 9. AuditLog (审计日志记录)

审计日志表 `_cdc_audit_log` 的 ORM 模型，存储所有数据变更记录。

```python
class AuditLog(BaseModel):
    """
    审计日志记录

    审计日志表存储所有被 CDC 捕获的数据变更，
    是增量同步的数据源。

    属性:
        id: 自增主键，作为消费断点
        table_name: 变更的业务表名
        operation: 操作类型 (INSERT/UPDATE/DELETE)
        row_id: 业务表主键值（字符串形式）
        before_data: 变更前的行数据（JSON 格式）
        after_data: 变更后的行数据（JSON 格式）
        created_at: 记录创建时间（即变更发生时间）
        consumed_at: 记录被消费时间（NULL 表示未消费）
        retry_count: 消费重试次数

    数据库表结构:
        ```sql
        CREATE TABLE _cdc_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('INSERT', 'UPDATE', 'DELETE')),
            row_id TEXT,
            before_data JSON,
            after_data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            retry_count INTEGER DEFAULT 0
        );

        CREATE INDEX idx_audit_unconsumed ON _cdc_audit_log(id)
            WHERE consumed_at IS NULL;
        ```
    """
    id: int = Field(..., description="自增主键，消费断点")
    table_name: str = Field(..., description="变更的业务表名")
    operation: OperationType = Field(..., description="操作类型")
    row_id: Optional[str] = Field(default=None, description="业务表主键值")
    before_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="变更前数据（UPDATE/DELETE）"
    )
    after_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="变更后数据（INSERT/UPDATE）"
    )
    created_at: datetime = Field(default_factory=datetime.now)
    consumed_at: Optional[datetime] = Field(
        default=None,
        description="消费时间戳，NULL 表示未消费"
    )
    retry_count: int = Field(default=0, ge=0, description="消费重试次数")

    @model_validator(mode="after")
    def validate_data_consistency(self):
        """验证数据一致性"""
        if self.operation == OperationType.INSERT and self.after_data is None:
            raise ValueError("INSERT 操作必须提供 after_data")
        if self.operation == OperationType.DELETE and self.before_data is None:
            raise ValueError("DELETE 操作必须提供 before_data")
        return self

    def to_change_event(self) -> ChangeEvent:
        """转换为 ChangeEvent 对象"""
        return ChangeEvent(
            event_id=f"{self.id}:{self.table_name}:{self.row_id}",
            audit_id=self.id,
            timestamp=self.created_at,
            operation=self.operation,
            table_name=self.table_name,
            row_id=self.row_id or "",
            before_data=self.before_data,
            after_data=self.after_data
        )

    def is_consumed(self) -> bool:
        """检查是否已消费"""
        return self.consumed_at is not None

    def mark_consumed(self):
        """标记为已消费"""
        self.consumed_at = datetime.now()
```

**验证规则**:
- `id` 必须 >= 1
- `operation` 必须为 INSERT/UPDATE/DELETE 之一
- `INSERT` 必须提供 `after_data`
- `DELETE` 必须提供 `before_data`
- `consumed_at` 为 NULL 表示未消费

---

### 10. CDCConnection (CDC 连接包装器)

包装 SQLite 连接，拦截写入操作并记录审计日志。

```python
class CDCConnection:
    """
    CDC 包装的 SQLite 连接

    拦截 execute 系列操作，将 INSERT/UPDATE/DELETE 自动记录到审计表。
    审计记录和业务数据在同一事务中写入，保证原子性。

    属性:
        _conn: 底层 SQLite 连接
        _audit_table: 审计表名，默认 "_cdc_audit_log"
        _enabled_tables: 需要审计的表名列表（空表示所有表）

    示例:
        ```python
        # 使用 CDC 包装连接
        raw_conn = sqlite3.connect("/data/app.db")
        cdc_conn = CDCConnection(raw_conn, enabled_tables=["users", "orders"])

        # 所有写入自动记录审计日志
        cdc_conn.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhang@example.com")
        )
        # 自动在 _cdc_audit_log 生成记录
        ```
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        audit_table: str = "_cdc_audit_log",
        enabled_tables: Optional[List[str]] = None
    ):
        self._conn = conn
        self._audit_table = audit_table
        self._enabled_tables = set(enabled_tables or [])
        self._ensure_audit_table()

    def _ensure_audit_table(self):
        """确保审计表存在"""
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {self._audit_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            row_id TEXT,
            before_data JSON,
            after_data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            retry_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_{self._audit_table}_unconsumed
            ON {self._audit_table}(id) WHERE consumed_at IS NULL;
        """
        self._conn.executescript(create_sql)

    def execute(
        self,
        sql: str,
        parameters: Union[tuple, dict] = ()
    ) -> sqlite3.Cursor:
        """
        执行 SQL，自动记录审计日志

        对于 INSERT/UPDATE/DELETE 操作：
        1. 解析 SQL 获取表名和操作类型
        2. 对于 UPDATE/DELETE，查询变更前的数据
        3. 执行业务 SQL
        4. 获取变更后的数据（INSERT/UPDATE）
        5. 在同一事务中写入审计表
        """
        operation, table = self._parse_sql(sql)

        if operation and self._should_audit(table):
            # 获取变更前数据
            before_data = None
            if operation in ("UPDATE", "DELETE"):
                before_data = self._fetch_before_data(table, sql, parameters)

            # 执行业务 SQL
            with self._conn:  # 自动事务
                cursor = self._conn.execute(sql, parameters)
                row_id = self._get_last_row_id(table) if operation == "INSERT" else None

                # 获取变更后数据
                after_data = None
                if operation in ("INSERT", "UPDATE"):
                    after_data = self._fetch_after_data(table, row_id, sql, parameters)

                # 写入审计表
                self._write_audit_log(
                    table=table,
                    operation=operation,
                    row_id=row_id,
                    before_data=before_data,
                    after_data=after_data
                )

            return cursor
        else:
            # 非写入操作，直接执行
            return self._conn.execute(sql, parameters)

    def _parse_sql(self, sql: str) -> Tuple[Optional[str], Optional[str]]:
        """解析 SQL，返回 (operation, table_name)"""
        # 简化实现，实际使用 sqlparse
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT"):
            return "INSERT", self._extract_table(sql)
        elif sql_upper.startswith("UPDATE"):
            return "UPDATE", self._extract_table(sql)
        elif sql_upper.startswith("DELETE"):
            return "DELETE", self._extract_table(sql)
        return None, None
```

**设计要点**:
- 审计日志和业务数据在同一事务，保证原子性
- 使用 `with self._conn` 自动管理事务
- 自动提取业务表主键作为 `row_id`
- 通过 `enabled_tables` 可配置只审计特定表

---

## 配置示例 (YAML)

```yaml
# sync.yaml 配置文件示例
source:
  db_path: "/data/source.db"
  journal_mode: "WAL"
  tables: ["users", "orders", "products"]

targets:
  - name: "mysql_prod"
    type: "mysql"
    connection:
      type: "mysql"
      host: "mysql.example.com"
      port: 3306
      database: "backup_db"
      username: "sync_user"
      password: "${MYSQL_PASSWORD}"  # 支持环境变量
    retry_policy:
      max_retries: 5

  - name: "oracle_dr"
    type: "oracle"
    connection:
      type: "oracle"
      host: "oracle.example.com"
      port: 1521
      service_name: "ORCL"
      username: "sync_user"
      password: "${ORACLE_PASSWORD}"

mappings:
  - source_table: "users"
    target_table: "app_users"
    field_mappings:
      - source_field: "name"
        target_field: "user_name"
      - source_field: "email"
        converter: "lowercase"
      - source_field: "status"
        converter: "default"
        converter_params:
          value: "active"
    filter_condition: "deleted_at IS NULL"
    primary_key: "id"

  - source_table: "orders"
    primary_key: "order_id"

batch_size: 100
checkpoint_interval: 100
log_level: "INFO"
```

---

## 状态转换图

### ChangeEvent 生命周期

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ChangeEvent 生命周期                                │
└─────────────────────────────────────────────────────────────────────────────┘

WAL 文件变更
      │
      ▼
┌──────────┐    解析    ┌──────────┐    验证    ┌──────────┐
│  Binary  │ ─────────▶ │  Parsed  │ ─────────▶ │ Validated│
│   Data   │           │  Event   │            │  Event   │
└──────────┘           └──────────┘            └─────┬────┘
                                                     │
                   ┌─────────────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │    Event Queue     │ (asyncio.Queue)
         └─────────┬──────────┘
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
┌─────────┐  ┌─────────┐  ┌─────────┐
│Failed   │  │Filtered │  │Ready    │
│(Error)  │  │(Skip)   │  │(Process)│
└────┬────┘  └────┬────┘  └────┬────┘
     │            │            │
     ▼            ▼            ▼
 Error Log    (Drop)      ┌──────────┐
                           │  Batch   │
                           │  Buffer  │
                           └────┬─────┘
                                │ 达到 batch_size 或超时
                                ▼
                           ┌──────────┐
                           │ Flushed  │
                           └──────────┘
```

---

## 数据库 Schema

### 1. 源数据库审计表 Schema (业务库)

在应用的业务数据库中创建的审计表，存储所有变更记录。

```sql
-- _cdc_audit_log 表（每个业务库一个）
-- 用于 CDC 捕获变更事件

CREATE TABLE IF NOT EXISTS _cdc_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增 ID，消费断点
    table_name TEXT NOT NULL,               -- 变更的业务表名
    operation TEXT NOT NULL                 -- 操作类型
        CHECK(operation IN ('INSERT', 'UPDATE', 'DELETE')),
    row_id TEXT,                            -- 业务表主键值（字符串形式）
    before_data JSON,                       -- 变更前数据（UPDATE/DELETE）
    after_data JSON,                        -- 变更后数据（INSERT/UPDATE）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 记录创建时间
    consumed_at TIMESTAMP,                  -- 消费时间戳，NULL 表示未消费
    retry_count INTEGER DEFAULT 0,          -- 消费重试次数

    -- 索引
    UNIQUE(id)
);

-- 创建部分索引，只索引未消费记录，节省空间
CREATE INDEX IF NOT EXISTS idx_audit_unconsumed
    ON _cdc_audit_log(id)
    WHERE consumed_at IS NULL;

-- 按表名索引，便于统计和清理
CREATE INDEX IF NOT EXISTS idx_audit_table
    ON _cdc_audit_log(table_name, created_at);
```

### 2. 元数据存储 Schema (checkpoints.db)

用于存储断点、统计信息等元数据。

```sql
-- checkpoints.db (SQLite)

-- 同步位置表
CREATE TABLE IF NOT EXISTS sync_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_db_path TEXT NOT NULL,
    target_name TEXT NOT NULL,
    last_audit_id INTEGER NOT NULL DEFAULT 0,
    total_events INTEGER NOT NULL DEFAULT 0,
    last_processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_db_path, target_name)
);

-- 同步统计表
CREATE TABLE IF NOT EXISTS sync_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_db_path TEXT NOT NULL,
    target_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL, -- INSERT/UPDATE/DELETE
    count INTEGER NOT NULL DEFAULT 0,
    last_sync_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_db_path, target_name, table_name, operation)
);

-- 错误日志表
CREATE TABLE IF NOT EXISTS sync_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_db_path TEXT NOT NULL,
    target_name TEXT NOT NULL,
    event_id TEXT,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_positions_source
    ON sync_positions(source_db_path, target_name);

CREATE INDEX IF NOT EXISTS idx_errors_unresolved
    ON sync_errors(resolved, created_at) WHERE resolved = FALSE;
```

---

## 验证矩阵

| 实体 | 字段级验证 | 跨字段验证 | 外部依赖验证 | 默认值 |
|------|-----------|-----------|-------------|--------|
| SyncConfig | ✅ | ✅ | ❌ | ✅ |
| SQLiteConfig | ✅ | ✅ | ✅ (文件存在性) | ✅ |
| TargetConfig | ✅ | ✅ | ❌ | ✅ |
| TableMapping | ✅ | ✅ | ❌ | ✅ |
| FieldMapping | ✅ | ✅ | ❌ | ✅ |
| ChangeEvent | ✅ | ✅ | ❌ | ✅ |
| SyncPosition | ✅ | ❌ | ❌ | ✅ |
| AuditLog | ✅ | ✅ | ❌ | ✅ |
| CDCConnection | ✅ | ✅ | ✅ (SQL 语法验证) | ✅ |

---

## 变更记录

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2026-02-07 | 1.0.0 | 初始设计 | Claude |
| 2026-02-07 | 1.1.0 | 重大架构变更：从 WAL 监听方案改为审计日志方案 | Claude |
