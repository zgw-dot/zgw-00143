import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theater_booking.db")

def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def add_column_if_not_exists(cursor, table_name, column_name, column_def):
    if not column_exists(cursor, table_name, column_name):
        print(f"  添加列 {table_name}.{column_name}...")
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
        return True
    else:
        print(f"  列 {table_name}.{column_name} 已存在，跳过")
        return False

def main():
    print("=" * 60)
    print("  数据库迁移 - 添加演练数据隔离字段")
    print("=" * 60)
    print(f"数据库路径: {DB_PATH}")
    print()

    if not os.path.exists(DB_PATH):
        print(f"错误: 数据库文件不存在: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("步骤1: 为 bookings 表添加演练字段")
        add_column_if_not_exists(cursor, "bookings", "is_drill", "BOOLEAN DEFAULT 0")
        add_column_if_not_exists(cursor, "bookings", "drill_session_id", "VARCHAR(100) DEFAULT ''")
        print()

        print("步骤2: 为 waitlist_entries 表添加演练字段")
        add_column_if_not_exists(cursor, "waitlist_entries", "is_drill", "BOOLEAN DEFAULT 0")
        add_column_if_not_exists(cursor, "waitlist_entries", "drill_session_id", "VARCHAR(100) DEFAULT ''")
        print()

        print("步骤3: 为 closed_windows 表添加演练字段")
        add_column_if_not_exists(cursor, "closed_windows", "is_drill", "BOOLEAN DEFAULT 0")
        add_column_if_not_exists(cursor, "closed_windows", "drill_session_id", "VARCHAR(100) DEFAULT ''")
        print()

        print("步骤4: 为 reschedule_records 表添加演练字段")
        add_column_if_not_exists(cursor, "reschedule_records", "is_drill", "BOOLEAN DEFAULT 0")
        add_column_if_not_exists(cursor, "reschedule_records", "drill_session_id", "VARCHAR(100) DEFAULT ''")
        print()

        print("步骤5: 为 waitlist_logs 表添加演练字段（如果表存在）")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='waitlist_logs'")
        if cursor.fetchone():
            add_column_if_not_exists(cursor, "waitlist_logs", "is_drill", "BOOLEAN DEFAULT 0")
            add_column_if_not_exists(cursor, "waitlist_logs", "drill_session_id", "VARCHAR(100) DEFAULT ''")
        else:
            print("  表 waitlist_logs 不存在，跳过")
        print()

        print("步骤6: 为已存在的演练数据设置索引（可选优化）")
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_drill ON bookings(is_drill, drill_session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_waitlist_drill ON waitlist_entries(is_drill, drill_session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_closed_drill ON closed_windows(is_drill, drill_session_id)")
            print("  索引创建完成")
        except Exception as e:
            print(f"  索引创建警告: {e}")
        print()

        conn.commit()
        print("=" * 60)
        print("  数据库迁移完成!")
        print("=" * 60)

        print("\n验证迁移结果:")
        tables_to_check = ["bookings", "waitlist_entries", "closed_windows", "reschedule_records"]
        for table in tables_to_check:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            has_is_drill = "is_drill" in columns
            has_drill_session = "drill_session_id" in columns
            status = "✓" if (has_is_drill and has_drill_session) else "✗"
            print(f"  {status} {table}: is_drill={has_is_drill}, drill_session_id={has_drill_session}")

        return 0

    except Exception as e:
        conn.rollback()
        print(f"\n错误: 迁移失败 - {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()

if __name__ == "__main__":
    import sys
    sys.exit(main())
