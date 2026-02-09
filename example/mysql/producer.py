import sqlite3
from sqlite_cdc import CDCConnection

if __name__ == '__main__':
    # 使用 CDC 连接包装器
    conn = sqlite3.connect("source.db")
    cdc_conn = CDCConnection(conn)

    # 插入新数据
    cdc_conn.execute(
        "INSERT INTO users (name, email) VALUES (?, ?)",
        ("用户101", "user101@example.com")
    )
    cdc_conn.commit()

    print("✓ 新数据已插入，将在 1-5 秒内同步到 MySQL")
