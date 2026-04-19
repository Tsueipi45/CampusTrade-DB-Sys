from flask import Flask

from database import DB_PATH, init_db
from views import register_routes


def create_app():
    if not DB_PATH.exists():
        init_db()

    app = Flask(__name__, template_folder="htmls")
    app.secret_key = "dlut_db_homework"
    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
