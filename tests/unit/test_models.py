"""
模型单元测试 (unittest)
"""

import unittest
from datetime import datetime, timezone

from sqlite_cdc.models.sync_config import (
    ConverterType,
    FieldMapping,
    MySQLConnection,
    OracleConnection,
    RetryPolicy,
    SQLiteConfig,
    SyncConfig,
    TableMapping,
    TargetConfig,
    TargetType,
)
from sqlite_cdc.models.event import ChangeEvent, OperationType
from sqlite_cdc.models.audit import AuditLog
from sqlite_cdc.models.position import InitialSyncCheckpoint, SyncPosition, SyncState


class TestSyncConfig(unittest.TestCase):
    """同步配置模型测试"""

    def test_basic_config(self):
        """测试基本配置创建"""
        config = SyncConfig(
            source=SQLiteConfig(db_path="test.db"),
            targets=[
                TargetConfig(
                    name="mysql1",
                    type=TargetType.MYSQL,
                    connection=MySQLConnection(
                        host="localhost",
                        database="test",
                        username="root",
                        password="secret"
                    )
                )
            ],
            mappings=[
                TableMapping(source_table="users", target_table="users_backup")
            ]
        )

        self.assertEqual(config.source.db_path, "test.db")
        self.assertEqual(len(config.targets), 1)
        self.assertEqual(config.targets[0].name, "mysql1")
        self.assertEqual(config.batch_size, 100)  # 默认值

    def test_target_names_unique_validation(self):
        """测试目标名称唯一性验证"""
        with self.assertRaises(ValueError) as cm:
            SyncConfig(
                source=SQLiteConfig(db_path="test.db"),
                targets=[
                    TargetConfig(
                        name="target1",
                        type=TargetType.MYSQL,
                        connection=MySQLConnection(
                            host="host1", database="db", username="u", password="p"
                        )
                    ),
                    TargetConfig(
                        name="target1",
                        type=TargetType.MYSQL,
                        connection=MySQLConnection(
                            host="host2", database="db", username="u", password="p"
                        )
                    ),
                ],
                mappings=[TableMapping(source_table="users")]
            )
        self.assertIn("目标名称必须唯一", str(cm.exception))

    def test_field_mapping_default_target(self):
        """测试字段映射默认目标字段"""
        mapping = FieldMapping(source_field="name")
        self.assertEqual(mapping.target_field, "name")  # 默认同源字段

    def test_table_mapping_default_target(self):
        """测试表映射默认目标表"""
        mapping = TableMapping(source_table="users")
        self.assertEqual(mapping.target_table, "users")  # 默认同源表


class TestChangeEvent(unittest.TestCase):
    """变更事件模型测试"""

    def test_valid_insert_event(self):
        """测试有效 INSERT 事件"""
        event = ChangeEvent(
            event_id="123:users:42",
            audit_id=123,
            operation=OperationType.INSERT,
            table_name="users",
            row_id=42,
            after_data={"id": 42, "name": "张三"}
        )

        self.assertEqual(event.operation, OperationType.INSERT)
        self.assertIsNotNone(event.after_data)

    def test_insert_requires_after_data(self):
        """测试 INSERT 必须提供 after_data"""
        with self.assertRaises(ValueError) as cm:
            ChangeEvent(
                event_id="123:users:42",
                audit_id=123,
                operation=OperationType.INSERT,
                table_name="users",
                row_id=42
            )
        self.assertIn("INSERT 操作必须提供 after_data", str(cm.exception))

    def test_delete_requires_before_data(self):
        """测试 DELETE 必须提供 before_data"""
        with self.assertRaises(ValueError) as cm:
            ChangeEvent(
                event_id="123:users:42",
                audit_id=123,
                operation=OperationType.DELETE,
                table_name="users",
                row_id=42
            )
        self.assertIn("DELETE 操作必须提供 before_data", str(cm.exception))

    def test_event_id_validation(self):
        """测试 event_id 格式验证"""
        with self.assertRaises(ValueError) as cm:
            ChangeEvent(
                event_id="invalid-format",  # 错误格式
                audit_id=123,
                operation=OperationType.INSERT,
                table_name="users",
                row_id=42,
                after_data={"id": 42}
            )
        self.assertIn("event_id 格式错误", str(cm.exception))


class TestAuditLog(unittest.TestCase):
    """审计日志模型测试"""

    def test_mark_consumed(self):
        """测试标记为已消费"""
        log = AuditLog(
            id=1,
            table_name="users",
            operation=OperationType.INSERT,
            after_data={"id": 1}
        )

        self.assertFalse(log.is_consumed())
        log.mark_consumed()
        self.assertTrue(log.is_consumed())
        self.assertIsNotNone(log.consumed_at)

    def test_to_change_event(self):
        """测试转换为 ChangeEvent"""
        log = AuditLog(
            id=123,
            table_name="users",
            operation=OperationType.INSERT,
            row_id="42",
            after_data={"id": 42, "name": "张三"}
        )

        event = log.to_change_event()
        self.assertEqual(event.event_id, "123:users:42")
        self.assertEqual(event.audit_id, 123)
        self.assertEqual(event.row_id, 42)  # 自动转为 int


class TestCheckpoint(unittest.TestCase):
    """断点模型测试"""

    def test_sync_position_update(self):
        """测试同步位置更新"""
        pos = SyncPosition(
            source_db_path="/data/app.db",
            target_name="mysql1",
            last_audit_id=0
        )

        pos.update(100)
        self.assertEqual(pos.last_audit_id, 100)
        self.assertEqual(pos.total_events, 1)

        pos.update(200)
        self.assertEqual(pos.last_audit_id, 200)
        self.assertEqual(pos.total_events, 2)

    def test_initial_sync_checkpoint_complete(self):
        """测试存量同步断点完成"""
        cp = InitialSyncCheckpoint(
            table_name="users",
            total_synced=1000,
            status=SyncState.RUNNING
        )

        cp.complete()
        self.assertEqual(cp.status, SyncState.COMPLETED)

    def test_initial_sync_checkpoint_fail(self):
        """测试存量同步断点失败"""
        cp = InitialSyncCheckpoint(
            table_name="users",
            total_synced=100
        )

        cp.fail()
        self.assertEqual(cp.status, SyncState.ERROR)


if __name__ == "__main__":
    unittest.main()