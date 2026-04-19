import os
import sqlite3
import psycopg2
from pathlib import Path
from werkzeug.security import generate_password_hash

DB_PATH = Path(__file__).resolve().parent / "campus_trade.db"
DATABASE_URL = os.environ.get("DATABASE_URL")

class DBProxy:
    """数据库代理类，处理 SQLite 和 PostgreSQL 的差异"""
    def __init__(self, conn, is_postgres):
        self.conn = conn
        self.is_postgres = is_postgres

    def cursor(self):
        return CursorProxy(self.conn.cursor(), self.is_postgres)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

class CursorProxy:
    def __init__(self, cursor, is_postgres):
        self.cursor = cursor
        self.is_postgres = is_postgres

    def execute(self, sql, params=None):
        if self.is_postgres:
            # 将 SQLite 的 ? 占位符替换为 PostgreSQL 的 %s
            sql = sql.replace("?", "%s")
            # 处理 SQLite 特有的 ROUND(AVG(price), 2)
            if "ROUND(AVG(price), 2)" in sql:
                sql = sql.replace("ROUND(AVG(price), 2)", "ROUND(CAST(AVG(price) AS numeric), 2)")
            # 处理 IFNULL -> COALESCE
            if "IFNULL(" in sql:
                sql = sql.replace("IFNULL(", "COALESCE(")
            # 处理 SQLite 的 || 字符串拼接（PostgreSQL 也支持，但有时会有类型问题，不过这里应该还好）
        
        if params:
            return self.cursor.execute(sql, params)
        return self.cursor.execute(sql)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def rowcount(self):
        return self.cursor.rowcount

def get_db():
    if DATABASE_URL:
        # Render 提供的 URL 可能以 postgres:// 开头，psycopg2 建议使用 postgresql://
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url)
        return DBProxy(conn, is_postgres=True)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        return DBProxy(conn, is_postgres=False)

def init_db():
    db_type = "PostgreSQL" if DATABASE_URL else "SQLite"
    print(f"Initializing {db_type} database...")
    
    with get_db() as db:
        cursor = db.cursor()
        
        if DATABASE_URL:
            # PostgreSQL 初始化脚本
            init_script = """
            DROP TABLE IF EXISTS Orders CASCADE;
            DROP TABLE IF EXISTS Item CASCADE;
            DROP TABLE IF EXISTS AppUser CASCADE;

            CREATE TABLE AppUser (
                user_id TEXT PRIMARY KEY,
                user_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'user'))
            );

            CREATE TABLE Item (
                item_id TEXT PRIMARY KEY,
                item_name TEXT NOT NULL,
                category TEXT NOT NULL,
                price NUMERIC NOT NULL CHECK(price > 0),
                status INTEGER NOT NULL CHECK(status IN (0, 1, 2)),
                seller_id TEXT NOT NULL REFERENCES AppUser(user_id)
            );

            CREATE TABLE Orders (
                order_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL UNIQUE REFERENCES Item(item_id),
                buyer_id TEXT NOT NULL REFERENCES AppUser(user_id),
                order_date TEXT NOT NULL
            );

            -- PostgreSQL 触发器函数：更新状态
            CREATE OR REPLACE FUNCTION fn_update_item_status() RETURNS TRIGGER AS $$
            BEGIN
                UPDATE Item SET status = 1 WHERE item_id = NEW.item_id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_update_item_status
            AFTER INSERT ON Orders
            FOR EACH ROW EXECUTE FUNCTION fn_update_item_status();

            -- PostgreSQL 触发器函数：防止购买非在售商品
            CREATE OR REPLACE FUNCTION fn_prevent_invalid_order() RETURNS TRIGGER AS $$
            BEGIN
                IF (SELECT status FROM Item WHERE item_id = NEW.item_id) != 0 THEN
                    RAISE EXCEPTION '该商品目前不可购买（已售出或已下架）';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_prevent_invalid_order
            BEFORE INSERT ON Orders
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_invalid_order();

            -- PostgreSQL 触发器函数：防止修改已售商品状态
            CREATE OR REPLACE FUNCTION fn_prevent_status_revert() RETURNS TRIGGER AS $$
            BEGIN
                IF OLD.status = 1 AND NEW.status != 1 THEN
                    RAISE EXCEPTION '已售出的商品状态不可更改';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_prevent_status_revert
            BEFORE UPDATE OF status ON Item
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_status_revert();
            """
            for statement in init_script.split(';'):
                if statement.strip():
                    cursor.cursor.execute(statement)
        else:
            # SQLite 初始化脚本 (保持原样)
            cursor.cursor.executescript("""
            DROP TABLE IF EXISTS Orders;
            DROP TABLE IF EXISTS Item;
            DROP TABLE IF EXISTS AppUser;

            CREATE TABLE AppUser (
                user_id TEXT PRIMARY KEY,
                user_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'user'))
            );

            CREATE TABLE Item (
                item_id TEXT PRIMARY KEY,
                item_name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL CHECK(price > 0),
                status INTEGER NOT NULL CHECK(status IN (0, 1, 2)),
                seller_id TEXT NOT NULL,
                FOREIGN KEY (seller_id) REFERENCES AppUser(user_id)
            );

            CREATE TABLE Orders (
                order_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL UNIQUE,
                buyer_id TEXT NOT NULL,
                order_date TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES Item(item_id),
                FOREIGN KEY (buyer_id) REFERENCES AppUser(user_id)
            );

            CREATE TRIGGER IF NOT EXISTS update_item_status_after_order
            AFTER INSERT ON Orders
            BEGIN
                UPDATE Item SET status = 1 WHERE item_id = NEW.item_id;
            END;

            CREATE TRIGGER IF NOT EXISTS prevent_order_on_non_available_item
            BEFORE INSERT ON Orders
            BEGIN
                SELECT CASE
                    WHEN (SELECT status FROM Item WHERE item_id = NEW.item_id) != 0
                    THEN RAISE(ABORT, '该商品目前不可购买（已售出或已下架）')
                END;
            END;

            CREATE TRIGGER IF NOT EXISTS prevent_status_revert_on_sold_item
            BEFORE UPDATE OF status ON Item
            FOR EACH ROW
            WHEN OLD.status = 1 AND NEW.status != 1
            BEGIN
                SELECT RAISE(ABORT, '已售出的商品状态不可更改');
            END;
            """)

        # 初始数据插入
        users = [
            ("admin001", "SystemAdmin", "13800000000", generate_password_hash("admin123"), "admin"),
            ("u001", "ZhangSan", "13800000001", generate_password_hash("user123"), "user"),
            ("u002", "LiSi", "13800000002", generate_password_hash("user123"), "user"),
            ("u003", "WangWu", "13800000003", generate_password_hash("user123"), "user"),
            ("u004", "ZhaoLiu", "13800000004", generate_password_hash("user123"), "user"),
        ]
        for user in users:
            cursor.execute("INSERT INTO AppUser VALUES (?, ?, ?, ?, ?)", user)

        items = [
            ("1001", "CalculusBook", "图书影音", 20, 0, "u001"),
            ("1002", "DeskLamp", "生活用品", 35, 0, "u002"),
            ("1003", "Microcontroller", "数码", 80, 0, "u001"),
            ("1004", "Chair", "其他", 50, 0, "u003"),
            ("1005", "WaterBottle", "生活用品", 15, 0, "u004"),
        ]
        for item in items:
            cursor.execute("INSERT INTO Item VALUES (?, ?, ?, ?, ?, ?)", item)

        orders = [
            ("0001", "1002", "u001", "2024-05-01"),
            ("0002", "1004", "u002", "2024-05-03"),
        ]
        for order in orders:
            cursor.execute("INSERT INTO Orders VALUES (?, ?, ?, ?)", order)
            # 在手动插入初始数据时，由于触发器已经存在，status 会自动更新

        # 创建视图
        if DATABASE_URL:
            cursor.cursor.execute("""
            CREATE OR REPLACE VIEW sold_items_view AS
            SELECT Item.item_name, Orders.buyer_id
            FROM Item
            JOIN Orders ON Item.item_id = Orders.item_id
            WHERE Item.status = 1;

            CREATE OR REPLACE VIEW unsold_items_view AS
            SELECT * FROM Item WHERE status = 0;
            """)
        else:
            cursor.cursor.executescript("""
            CREATE VIEW IF NOT EXISTS sold_items_view AS
            SELECT Item.item_name, Orders.buyer_id
            FROM Item
            JOIN Orders ON Item.item_id = Orders.item_id
            WHERE Item.status = 1;

            CREATE VIEW IF NOT EXISTS unsold_items_view AS
            SELECT * FROM Item WHERE status = 0;
            """)

        db.commit()
