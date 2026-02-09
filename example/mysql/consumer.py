import asyncio
from sqlite_cdc import SyncEngine, load_config

def create_sqlite_data():
    import sqlite3

    conn = sqlite3.connect("source.db")
    cursor = conn.cursor()

    # 创建用户表
    cursor.execute("""
                   DROP TABLE IF EXISTS users 
                   """)
    cursor.execute("""
                   CREATE TABLE users
                   (
                       id         INTEGER PRIMARY KEY AUTOINCREMENT,
                       name       TEXT        NOT NULL,
                       email      TEXT UNIQUE NOT NULL,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                   )
                   """)

    # 插入测试数据
    for i in range(100):
        cursor.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            (f"用户{i}", f"user{i}@example.com")
        )

    conn.commit()
    conn.close()
    print("✓ 测试数据库创建完成: source.db (100 条用户数据)")

async def main():
    # 准备测试数据
    create_sqlite_data()

    # 加载配置
    config = load_config("sync.yaml")

    # 创建同步引擎
    engine = SyncEngine(config)

    # 启动同步（存量 + 增量）
    await engine.start()

    # 查看状态
    status = engine.get_status()
    print(f"状态: {status.state}")
    print(f"已处理: {status.total_events} 事件")

    # 保持运行
    try:
        while True:
            await asyncio.sleep(1)
            status = engine.get_status()
            print(f"\r延迟: {status.lag_seconds:.2f}s", end="")
    except KeyboardInterrupt:
        print("\n停止同步...")
        await engine.stop()

if __name__ == "__main__":
    asyncio.run(main())