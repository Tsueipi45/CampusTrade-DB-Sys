import os
from flask import Flask
from database import DB_PATH, init_db, get_db, DATABASE_URL
from views import register_routes

def create_app():
    # 自动初始化数据库逻辑
    should_init = False
    if DATABASE_URL:
        # PostgreSQL: 检查 User 表是否存在
        try:
            with get_db() as db:
                cursor = db.cursor()
                user_table = '"User"'
                cursor.execute(f"SELECT 1 FROM {user_table} LIMIT 1")
        except Exception:
            should_init = True
    else:
        # SQLite: 检查文件是否存在
        if not DB_PATH.exists():
            should_init = True

    if should_init:
        init_db()

    app = Flask(__name__, template_folder="htmls")
    app.secret_key = os.environ.get("SECRET_KEY", "dlut_db_homework")
    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
