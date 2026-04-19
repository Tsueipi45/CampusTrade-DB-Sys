import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash


DB_PATH = Path(__file__).resolve().parent / "campus_trade.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.executescript(
            """
            DROP TABLE IF EXISTS Orders;
            DROP TABLE IF EXISTS Item;
            DROP TABLE IF EXISTS User;
            DROP VIEW IF EXISTS sold_items_view;
            DROP VIEW IF EXISTS unsold_items_view;

            CREATE TABLE User (
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
                status INTEGER NOT NULL CHECK(status IN (0, 1, 2)), -- 0:在售, 1:已售, 2:下架
                seller_id TEXT NOT NULL,
                FOREIGN KEY (seller_id) REFERENCES User(user_id)
            );

            CREATE TABLE Orders (
                order_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL UNIQUE,
                buyer_id TEXT NOT NULL,
                order_date TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES Item(item_id),
                FOREIGN KEY (buyer_id) REFERENCES User(user_id)
            );

            -- 触发器：确保订单插入时，商品状态同步更新为已售 (status=1)
            CREATE TRIGGER IF NOT EXISTS update_item_status_after_order
            AFTER INSERT ON Orders
            BEGIN
                UPDATE Item SET status = 1 WHERE item_id = NEW.item_id;
            END;

            -- 触发器：防止对非“在售”状态 (status != 0) 的商品创建订单
            -- 这涵盖了用户规则：status=1(已售) 或 status=2(下架) 的商品不能出现在新订单中
            CREATE TRIGGER IF NOT EXISTS prevent_order_on_non_available_item
            BEFORE INSERT ON Orders
            BEGIN
                SELECT CASE
                    WHEN (SELECT status FROM Item WHERE item_id = NEW.item_id) != 0
                    THEN RAISE(ABORT, '该商品目前不可购买（已售出或已下架）')
                END;
            END;

            -- 触发器：禁止手动将已售商品 (存在于 Orders 表) 的状态改回 0 或 2
            CREATE TRIGGER IF NOT EXISTS prevent_status_revert_on_sold_item
            BEFORE UPDATE OF status ON Item
            FOR EACH ROW
            WHEN OLD.status = 1 AND NEW.status != 1
            BEGIN
                SELECT RAISE(ABORT, '已售出的商品状态不可更改');
            END;
            """
        )

        users = [
            (
                "admin001",
                "SystemAdmin",
                "13800000000",
                generate_password_hash("admin123"),
                "admin",
            ),
            (
                "u001",
                "ZhangSan",
                "13800000001",
                generate_password_hash("user123"),
                "user",
            ),
            (
                "u002",
                "LiSi",
                "13800000002",
                generate_password_hash("user123"),
                "user",
            ),
            (
                "u003",
                "WangWu",
                "13800000003",
                generate_password_hash("user123"),
                "user",
            ),
            (
                "u004",
                "ZhaoLiu",
                "13800000004",
                generate_password_hash("user123"),
                "user",
            ),
        ]
        cursor.executemany("INSERT INTO User VALUES (?, ?, ?, ?, ?)", users)

        items = [
            ("1001", "CalculusBook", "图书影音", 20, 0, "u001"),
            ("1002", "DeskLamp", "生活用品", 35, 0, "u002"),
            ("1003", "Microcontroller", "数码", 80, 0, "u001"),
            ("1004", "Chair", "其他", 50, 0, "u003"),
            ("1005", "WaterBottle", "生活用品", 15, 0, "u004"),
        ]
        cursor.executemany("INSERT INTO Item VALUES (?, ?, ?, ?, ?, ?)", items)

        orders = [
            ("0001", "1002", "u001", "2024-05-01"),
            ("0002", "1004", "u002", "2024-05-03"),
        ]
        cursor.executemany("INSERT INTO Orders VALUES (?, ?, ?, ?)", orders)

        cursor.executescript(
            """
            CREATE VIEW sold_items_view AS
            SELECT Item.item_name, Orders.buyer_id
            FROM Item
            JOIN Orders ON Item.item_id = Orders.item_id
            WHERE Item.status = 1;

            CREATE VIEW unsold_items_view AS
            SELECT *
            FROM Item
            WHERE status = 0;
            """
        )

        conn.commit()
