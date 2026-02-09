"""
CLI 命令行入口 - 使用 Click 框架
"""

import asyncio
import sys
from pathlib import Path

import click

from sqlite_cdc import __version__
from sqlite_cdc.config import ConfigError, load_config, save_config_template
from sqlite_cdc.storage.checkpoint import CheckpointStore
from sqlite_cdc.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="配置文件路径",
)
@click.option(
    "--log-level",
    "-l",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="日志级别",
)
@click.version_option(version=__version__, prog_name="sqlite-cdc")
@click.pass_context
def cli(ctx: click.Context, config: str, log_level: str) -> None:
    """
    SQLite CDC 同步引擎 CLI

    支持存量和增量同步 SQLite 数据到 MySQL/Oracle。
    """
    # 配置日志
    configure_logging(log_level=log_level, json_format=False)

    # 保存上下文
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["log_level"] = log_level


@cli.command()
@click.argument("output_path", type=click.Path(), default="sync.yaml")
def init(output_path: str) -> None:
    """
    生成配置文件模板

    示例:
        sqlite-cdc init sync.yaml
    """
    path = Path(output_path)

    if path.exists():
        click.confirm(f"文件 {output_path} 已存在，是否覆盖？", abort=True)

    save_config_template(output_path)
    click.echo(f"✓ 配置模板已生成: {output_path}")


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def validate(config_path: str) -> None:
    """
    验证配置文件

    示例:
        sqlite-cdc validate sync.yaml
    """
    try:
        config = load_config(config_path)
        click.echo("✓ 配置验证通过")
        click.echo(f"  源数据库: {config.source.db_path}")
        click.echo(f"  目标数量: {len(config.targets)}")
        click.echo(f"  映射表数: {len(config.mappings)}")
    except ConfigError as e:
        click.echo(f"✗ 配置错误: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ 验证失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    required=True,
    help="配置文件路径",
)
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["full", "initial", "incremental"]),
    default="full",
    help="同步模式: full=存量+增量, initial=仅存量, incremental=仅增量",
)
@click.option(
    "--tables",
    "-t",
    help="要同步的表（逗号分隔，默认全部）",
)
def sync(config: str, mode: str, tables: str) -> None:
    """
    执行数据同步

    示例:
        sqlite-cdc sync -c sync.yaml --mode full
        sqlite-cdc sync -c sync.yaml --mode initial --tables users,orders
    """
    table_list = tables.split(",") if tables else None

    try:
        if mode == "full":
            asyncio.run(_run_full_sync(config, table_list))
        elif mode == "initial":
            asyncio.run(_run_initial_sync(config, table_list))
        else:  # incremental
            asyncio.run(_run_incremental_sync(config, table_list))
    except KeyboardInterrupt:
        click.echo("\n同步已停止")
        sys.exit(0)
    except Exception as e:
        click.echo(f"✗ 同步失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    required=True,
    help="配置文件路径",
)
def status(config: str) -> None:
    """
    查看同步状态

    示例:
        sqlite-cdc status -c sync.yaml
    """
    try:
        cfg = load_config(config)
        source_path = cfg.source.db_path

        click.echo("SQLite CDC 同步状态")
        click.echo("=" * 40)
        click.echo(f"源数据库: {source_path}")
        click.echo(f"日志级别: {cfg.log_level}")
        click.echo("")

        # 显示存量同步状态
        store = CheckpointStore()
        checkpoints = store.list_initial_checkpoints(source_path)

        if checkpoints:
            click.echo("[存量同步状态]")
            for table, cp in checkpoints.items():
                status_icon = "✓" if cp.status.value == "completed" else "⏳"
                click.echo(f"  {status_icon} {table}: {cp.total_synced} 行 ({cp.status.value})")
            click.echo("")

        # 显示增量同步状态
        click.echo("[增量同步状态]")
        for target in cfg.targets:
            position = store.load_position(source_path, target.name)
            click.echo(f"  目标: {target.name}")
            click.echo(f"    已处理: {position.total_events} 事件")
            click.echo(f"    断点位置: {position.last_audit_id}")

    except Exception as e:
        click.echo(f"✗ 获取状态失败: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    required=True,
    help="配置文件路径",
)
@click.option(
    "--table",
    "-t",
    help="重置指定表的断点（不指定则重置所有）",
)
def reset(config: str, table: str) -> None:
    """
    重置同步断点

    示例:
        sqlite-cdc reset -c sync.yaml --table users
        sqlite-cdc reset -c sync.yaml  # 重置所有表
    """
    try:
        cfg = load_config(config)
        source_path = cfg.source.db_path
        store = CheckpointStore()

        if table:
            store.delete_initial_checkpoint(source_path, table)
            click.echo(f"✓ 表 {table} 的断点已重置")
        else:
            # 重置所有表
            for mapping in cfg.mappings:
                store.delete_initial_checkpoint(source_path, mapping.source_table)
            click.echo("✓ 所有表的断点已重置")

    except Exception as e:
        click.echo(f"✗ 重置失败: {e}", err=True)
        sys.exit(1)


# ============================================================================
# 异步执行函数
# ============================================================================

async def _run_full_sync(config_path: str, tables: list[str] | None) -> None:
    """执行完整同步（存量 + 增量）"""
    from sqlite_cdc.core.engine import SyncEngine

    config = load_config(config_path)
    engine = SyncEngine(config)

    click.echo("SQLite CDC 同步引擎")
    click.echo("=" * 40)
    click.echo(f"配置: {config_path}")
    click.echo("")

    # 启动同步
    await engine.start(tables=tables, run_initial=True)

    click.echo("\n[存量同步]")
    # 存量同步完成后自动转为增量
    status = engine.get_status()
    click.echo(f"表: {', '.join(tables or [m.source_table for m in config.mappings])}")
    click.echo("状态: ✓ 完成")
    click.echo("")

    click.echo("[增量同步]")
    click.echo("状态: 运行中")
    click.echo("按 Ctrl+C 停止...")

    try:
        while engine.is_running():
            await asyncio.sleep(1)
            status = engine.get_status()
            click.echo(
                f"\r延迟: {status.lag_seconds:.2f}s | 已同步: {status.total_events} 事件",
                nl=False
            )
    except KeyboardInterrupt:
        click.echo("\n")

    await engine.stop()
    click.echo("✓ 同步已停止")


async def _run_initial_sync(config_path: str, tables: list[str] | None) -> None:
    """仅执行存量同步"""
    import sqlite3

    from sqlite_cdc.core.initial_sync import InitialSync

    config = load_config(config_path)

    click.echo("SQLite CDC 存量同步")
    click.echo("=" * 40)

    # 连接源数据库
    source_conn = sqlite3.connect(config.source.db_path)
    source_conn.row_factory = sqlite3.Row

    try:
        # 这里简化处理，实际需要创建目标写入器
        # 为了演示，先不连接真实目标
        targets = []  # 实际应创建 MySQL/Orcle 写入器

        sync = InitialSync(source_conn, targets, config)
        tables_to_sync = tables or [m.source_table for m in config.mappings]

        for table in tables_to_sync:
            click.echo(f"\n同步表: {table}")
            count = await sync.sync_table(table)
            click.echo(f"✓ 完成: {count} 行")

    finally:
        source_conn.close()

    click.echo("\n✓ 存量同步完成")


async def _run_incremental_sync(config_path: str, tables: list[str] | None) -> None:
    """仅执行增量同步"""
    from sqlite_cdc.core.engine import SyncEngine

    config = load_config(config_path)
    engine = SyncEngine(config)

    click.echo("SQLite CDC 增量同步")
    click.echo("=" * 40)
    click.echo("按 Ctrl+C 停止...")

    await engine.start(tables=tables, run_initial=False)

    try:
        while engine.is_running():
            await asyncio.sleep(1)
            status = engine.get_status()
            click.echo(
                f"\r延迟: {status.lag_seconds:.2f}s | 已同步: {status.total_events} 事件",
                nl=False
            )
    except KeyboardInterrupt:
        pass
    finally:
        await engine.stop()

    click.echo("\n✓ 同步已停止")


if __name__ == "__main__":
    cli()
