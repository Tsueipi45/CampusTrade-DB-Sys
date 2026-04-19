import datetime
from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db

ITEM_CATEGORIES = ["数码", "户外", "穿搭", "首饰", "图书影音", "美妆", "食品", "其他"]
CATEGORY_DISPLAY_MAP = {
    "Book": "图书影音",
    "DailyGoods": "生活用品",
    "Electronics": "数码",
    "Furniture": "其他",
}
QUERY_CATEGORIES = ["全部类别", "生活用品"] + ITEM_CATEGORIES


def fetch_user_by_id(user_id):
    if not user_id:
        return None

    with get_db() as conn:
        cursor = conn.cursor()
        return cursor.execute(
            """
            SELECT user_id, user_name, phone, password_hash, role
            FROM AppUser
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()


def fetch_all_users():
    with get_db() as conn:
        cursor = conn.cursor()
        return cursor.execute(
            """
            SELECT user_id, user_name, phone, password_hash, role
            FROM AppUser
            ORDER BY user_id
            """
        ).fetchall()


def set_session_user(user):
    session["user_id"] = user[0]
    session["user_name"] = user[1]
    session["user_role"] = user[4]


def clear_session_user():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_role", None)


def build_template_context(user=None):
    current_user = user or fetch_user_by_id(session.get("user_id"))
    return {
        "current_user_id": current_user[0] if current_user else None,
        "current_user_name": current_user[1] if current_user else None,
        "current_role": current_user[4] if current_user else None,
    }


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("login"))
        
        current_user = fetch_user_by_id(user_id)
        if not current_user:
            clear_session_user()
            flash("登录会话已过期，请重新登录。")
            return redirect(url_for("login"))

        set_session_user(current_user)
        return view_func(*args, **kwargs)

    return wrapped_view


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("login"))
        
        current_user = fetch_user_by_id(user_id)
        if not current_user:
            clear_session_user()
            flash("登录会话已过期，请重新登录。")
            return redirect(url_for("login"))

        if current_user[4] != "admin":
            flash("当前账号没有管理员权限。")
            return redirect(url_for("index"))

        set_session_user(current_user)
        return view_func(*args, **kwargs)

    return wrapped_view


def generate_next_item_id():
    with get_db() as conn:
        cursor = conn.cursor()
        item_ids = cursor.execute("SELECT item_id FROM Item").fetchall()

    numeric_ids = []
    for row in item_ids:
        value = row[0]
        if str(value).isdigit():
            numeric_ids.append(int(value))

    next_id = max(numeric_ids, default=1000) + 1
    return str(next_id)


def mark_current_user_as_self(headers, rows, current_user_id):
    formatted_rows = []
    for row in rows:
        row_values = list(row)

        if "类别" in headers:
            category_index = headers.index("类别")
            row_values[category_index] = CATEGORY_DISPLAY_MAP.get(
                row_values[category_index], row_values[category_index]
            )

        if "卖家ID" in headers and current_user_id:
            seller_index = headers.index("卖家ID")
            if row_values[seller_index] == current_user_id:
                row_values[seller_index] = "本人"

        formatted_rows.append(tuple(row_values))
    return formatted_rows


def register_routes(app):
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user_id"):
            return redirect(url_for("index"))

        if request.method == "POST":
            user_id = request.form["user_id"].strip()
            password = request.form["password"]
            user = fetch_user_by_id(user_id)

            if not user or not check_password_hash(user[3], password):
                flash("用户 ID 或密码错误。")
                return redirect(url_for("login"))

            set_session_user(user)
            flash("登录成功。")
            return redirect(url_for("index"))

        return render_template("login.html", **build_template_context())

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if session.get("user_id"):
            return redirect(url_for("index"))

        if request.method == "POST":
            user_id = request.form["user_id"].strip()
            user_name = request.form["user_name"].strip()
            phone = request.form["phone"].strip()
            password = request.form["password"]

            if not user_id or not user_name or not phone or not password:
                flash("请完整填写注册信息。")
                return redirect(url_for("register"))

            if len(password) < 6:
                flash("密码长度至少为 6 位。")
                return redirect(url_for("register"))

            with get_db() as conn:
                cursor = conn.cursor()
                exists = cursor.execute(
                    "SELECT 1 FROM AppUser WHERE user_id = ?", (user_id,)
                ).fetchone()
                if exists:
                    flash("该用户 ID 已存在，请更换后再试。")
                    return redirect(url_for("register"))

                cursor.execute(
                    """
                    INSERT INTO AppUser (user_id, user_name, phone, password_hash, role)
                    VALUES (?, ?, ?, ?, 'user')
                    """,
                    (user_id, user_name, phone, generate_password_hash(password)),
                )
                conn.commit()

            flash("注册成功，请使用新账号登录。")
            return redirect(url_for("login"))

        return render_template("register.html", **build_template_context())

    @app.route("/logout")
    def logout():
        clear_session_user()
        flash("已退出登录。")
        return redirect(url_for("login"))

    @app.route("/sell", methods=["GET", "POST"])
    @login_required
    def sell_item():
        profile = fetch_user_by_id(session.get("user_id"))
        if profile[4] != "user":
            flash("只有普通用户可以上架商品。")
            return redirect(url_for("index"))

        if request.method == "POST":
            item_name = request.form["item_name"].strip()
            category = request.form["category"].strip()
            price_text = request.form["price"].strip()

            if not item_name or not category or not price_text:
                flash("请完整填写商品信息。")
                return redirect(url_for("sell_item"))

            if category not in ITEM_CATEGORIES:
                flash("请选择系统提供的商品类别。")
                return redirect(url_for("sell_item"))

            try:
                price = float(price_text)
            except ValueError:
                flash("价格格式不正确。")
                return redirect(url_for("sell_item"))

            if price <= 0:
                flash("价格必须大于 0。")
                return redirect(url_for("sell_item"))

            item_id = generate_next_item_id()
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO Item (item_id, item_name, category, price, status, seller_id)
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (item_id, item_name, category, price, profile[0]),
                )
                conn.commit()

            flash(f"商品上架成功，商品编号为 {item_id}。")
            return redirect(url_for("index"))

        return render_template(
            "sell.html",
            categories=ITEM_CATEGORIES,
            **build_template_context(profile),
        )

    @app.route("/my/items")
    @login_required
    def my_items():
        profile = fetch_user_by_id(session.get("user_id"))
        if profile[4] != "user":
            flash("管理员请使用维护页管理商品。")
            return redirect(url_for("manage_items"))

        with get_db() as conn:
            cursor = conn.cursor()
            items = cursor.execute(
                "SELECT * FROM Item WHERE seller_id = ? ORDER BY status ASC, item_id DESC", (profile[0],)
            ).fetchall()

        items = mark_current_user_as_self(
            ["ID", "名称", "类别", "价格", "状态", "卖家ID"],
            items,
            profile[0],
        )
        return render_template(
            "my_items.html",
            managed_items=items,
            **build_template_context(profile),
        )

    @app.route("/my/items/take-down/<item_id>", methods=["POST"])
    @login_required
    def take_down_item(item_id):
        profile = fetch_user_by_id(session.get("user_id"))
        with get_db() as conn:
            cursor = conn.cursor()
            # 只能下架自己的、处于“在售”状态的商品
            cursor.execute(
                "UPDATE Item SET status = 2 WHERE item_id = ? AND seller_id = ? AND status = 0",
                (item_id, profile[0]),
            )
            if cursor.rowcount:
                conn.commit()
                flash(f"商品 {item_id} 已成功下架。")
            else:
                flash("下架失败：只能下架您发布的且处于在售状态的商品。")
        return redirect(url_for("my_items"))

    @app.route("/my/items/re-list/<item_id>", methods=["POST"])
    @login_required
    def relist_item(item_id):
        profile = fetch_user_by_id(session.get("user_id"))
        with get_db() as conn:
            cursor = conn.cursor()
            # 重新上架已下架的商品
            cursor.execute(
                "UPDATE Item SET status = 0 WHERE item_id = ? AND seller_id = ? AND status = 2",
                (item_id, profile[0]),
            )
            if cursor.rowcount:
                conn.commit()
                flash(f"商品 {item_id} 已重新上架。")
            else:
                flash("操作失败：该商品无法重新上架。")
        return redirect(url_for("my_items"))

    @app.route("/my/items/update-price/<item_id>", methods=["POST"])
    @login_required
    def update_my_item_price(item_id):
        profile = fetch_user_by_id(session.get("user_id"))
        price_text = request.form["price"].strip()
        try:
            price = float(price_text)
        except ValueError:
            flash("价格格式不正确。")
            return redirect(url_for("my_items"))

        if price <= 0:
            flash("价格必须大于 0。")
            return redirect(url_for("my_items"))

        with get_db() as conn:
            cursor = conn.cursor()
            # 确保商品属于当前用户
            item = cursor.execute(
                "SELECT 1 FROM Item WHERE item_id = ? AND seller_id = ?",
                (item_id, profile[0]),
            ).fetchone()

            if not item:
                flash("您没有权限修改该商品，或商品不存在。")
                return redirect(url_for("my_items"))

            cursor.execute("UPDATE Item SET price = ? WHERE item_id = ?", (price, item_id))
            conn.commit()

        flash(f"您的商品 {item_id} 的价格已更新。")
        return redirect(url_for("my_items"))

    @app.route("/")
    @login_required
    def index():
        profile = fetch_user_by_id(session.get("user_id"))
        with get_db() as conn:
            cursor = conn.cursor()
            items = cursor.execute("SELECT * FROM Item ORDER BY item_id").fetchall()
            items = mark_current_user_as_self(
                ["ID", "名称", "类别", "价格", "状态", "卖家ID"],
                items,
                None,
            )
            unsold_items = [item for item in items if item[4] == 0]
            sold_items = [item for item in items if item[4] == 1]
            if profile[4] == "admin":
                users = cursor.execute("SELECT * FROM AppUser ORDER BY user_id").fetchall()
                orders = []
                my_sold_items = []
                order_section_title = ""
            else:
                users = []
                orders = cursor.execute(
                    """
                    SELECT * FROM Orders
                    WHERE buyer_id = ?
                    ORDER BY order_date DESC, order_id DESC
                    """,
                    (profile[0],),
                ).fetchall()
                my_sold_items = cursor.execute(
                    """
                    SELECT i.item_id, i.item_name, i.price, o.order_date, u.user_name as buyer_name
                    FROM Item i
                    JOIN Orders o ON i.item_id = o.item_id
                    JOIN AppUser u ON o.buyer_id = u.user_id
                    WHERE i.seller_id = ? AND i.status = 1
                    ORDER BY o.order_date DESC
                    """,
                    (profile[0],),
                ).fetchall()
                order_section_title = "我的订单"

        return render_template(
            "home.html",
            profile=profile,
            users=users,
            unsold_items=unsold_items,
            sold_items=sold_items,
            orders=orders,
            my_sold_items=my_sold_items,
            order_section_title=order_section_title,
            **build_template_context(profile),
        )

    @app.route("/manage/users")
    @login_required
    @admin_required
    def manage_users():
        search_query = request.args.get("search", "").strip()
        with get_db() as conn:
            cursor = conn.cursor()
            if search_query:
                users = cursor.execute(
                    "SELECT user_id, user_name, phone, role FROM AppUser WHERE user_id LIKE ? OR user_name LIKE ? OR phone LIKE ? ORDER BY user_id",
                    (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"),
                ).fetchall()
            else:
                users = cursor.execute(
                    "SELECT user_id, user_name, phone, role FROM AppUser ORDER BY user_id"
                ).fetchall()

        return render_template(
            "admin_users.html",
            managed_users=users,
            search_query=search_query,
            **build_template_context(fetch_user_by_id(session.get("user_id"))),
        )

    @app.route("/manage/items")
    @login_required
    @admin_required
    def manage_items():
        search_query = request.args.get("search", "").strip()
        selected_category = request.args.get("category", "全部类别")
        sort_by = request.args.get("sort", "item_id")
        order = request.args.get("order", "DESC")

        valid_sort_columns = ["item_id", "item_name", "category", "price", "status", "seller_id"]
        if sort_by not in valid_sort_columns:
            sort_by = "item_id"
        
        if order not in ["ASC", "DESC"]:
            order = "DESC"

        with get_db() as conn:
            cursor = conn.cursor()
            
            where_clauses = ["(item_name LIKE ? OR item_id LIKE ? OR seller_id LIKE ?)"]
            params = [f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"]
            
            if selected_category != "全部类别":
                where_clauses.append("category = ?")
                params.append(selected_category)
            
            where_sql = " WHERE " + " AND ".join(where_clauses)
            query = f"SELECT * FROM Item{where_sql} ORDER BY {sort_by} {order}"
            managed_items = cursor.execute(query, params).fetchall()

        managed_items = mark_current_user_as_self(
            ["ID", "名称", "类别", "价格", "状态", "卖家ID"],
            managed_items,
            None,
        )
        return render_template(
            "admin_maintaince.html",
            managed_items=managed_items,
            search_query=search_query,
            categories=QUERY_CATEGORIES,
            selected_category=selected_category,
            sort_by=sort_by,
            order=order,
            **build_template_context(fetch_user_by_id(session.get("user_id"))),
        )

    @app.route("/manage/items/update-price/<item_id>", methods=["POST"])
    @login_required
    @admin_required
    def update_item_price(item_id):
        price_text = request.form["price"].strip()
        try:
            price = float(price_text)
        except ValueError:
            flash("价格格式不正确。")
            return redirect(url_for("manage_items"))

        if price <= 0:
            flash("价格必须大于 0。")
            return redirect(url_for("manage_items"))

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE Item SET price = ? WHERE item_id = ?", (price, item_id))
            conn.commit()

        flash(f"商品 {item_id} 的价格已更新。")
        return redirect(url_for("manage_items"))

    @app.route("/manage/items/delete/<item_id>", methods=["POST"])
    @login_required
    @admin_required
    def delete_item(item_id):
        with get_db() as conn:
            cursor = conn.cursor()
            # 管理员可以删除在售 (0) 或下架 (2) 的商品
            cursor.execute(
                "DELETE FROM Item WHERE item_id = ? AND status IN (0, 2)",
                (item_id,),
            )
            deleted_count = cursor.rowcount
            conn.commit()

        if deleted_count:
            flash(f"商品 {item_id} 已从系统中永久删除。")
        else:
            flash("删除失败：只能删除在售或已下架的商品。已售商品不可删除。")
        return redirect(url_for("manage_items"))

    @app.route("/manage/items/take-down/<item_id>", methods=["POST"])
    @login_required
    @admin_required
    def admin_take_down_item(item_id):
        with get_db() as conn:
            cursor = conn.cursor()
            # 管理员下架在售商品
            cursor.execute(
                "UPDATE Item SET status = 2 WHERE item_id = ? AND status = 0",
                (item_id,),
            )
            if cursor.rowcount:
                conn.commit()
                flash(f"商品 {item_id} 已下架。")
            else:
                flash("下架失败：该商品可能已售出或已经是下架状态。")
        return redirect(url_for("manage_items"))

    @app.route("/demo_ops", methods=["POST"])
    @login_required
    @admin_required
    def demo_ops():
        with get_db() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO Item VALUES "
                    "('1006', 'PythonBook', '图书影音', 45, 0, 'u002')"
                )
                cursor.execute("UPDATE Item SET price = 25 WHERE item_id = '1001'")
                cursor.execute("DELETE FROM Item WHERE item_id = '1005' AND status = 0")
                conn.commit()
                flash("示例维护操作已完成：新增了 1006，更新了 1001 的价格，并删除了 1005。")
            except Exception as exc:
                conn.rollback()
                flash(f"维护操作失败: {exc}")
        return redirect(url_for("index"))

    @app.route("/buy/<item_id>", methods=["POST"])
    @login_required
    def buy_item(item_id):
        buyer_id = session["user_id"]
        if session.get("user_role") == "admin":
            flash("管理员账号仅用于管理，不能直接下单。")
            return redirect(url_for("index"))

        order_id = "O" + datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
        order_date = datetime.date.today().strftime("%Y-%m-%d")

        with get_db() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN TRANSACTION")
                cursor.execute(
                    "SELECT status, seller_id FROM Item WHERE item_id = ?", (item_id,)
                )
                result = cursor.fetchone()
                if not result or result[0] != 0:
                    conn.rollback()
                    flash("该商品目前不可购买（可能已售出或已下架）。")
                    return redirect(url_for("index"))

                if result[1] == buyer_id:
                    conn.rollback()
                    flash("不能购买自己发布的商品。")
                    return redirect(url_for("index"))

                cursor.execute(
                    "INSERT INTO Orders (order_id, item_id, buyer_id, order_date) "
                    "VALUES (?, ?, ?, ?)",
                    (order_id, item_id, buyer_id, order_date),
                )
                cursor.execute("UPDATE Item SET status = 1 WHERE item_id = ?", (item_id,))

                conn.commit()
                flash("下单成功。")
            except Exception as exc:
                conn.rollback()
                flash(f"下单失败: {exc}")

        return redirect(url_for("index"))

    @app.route("/queries")
    @login_required
    def queries():
        profile = fetch_user_by_id(session.get("user_id"))
        selected_category = request.args.get("category", "全部类别")
        selected_seller_id = request.args.get("seller_id", "")
        selected_buyer_id = request.args.get("buyer_id", "")
        selected_status = request.args.get("status", "全部")
        min_price = request.args.get("min_price", "")
        max_price = request.args.get("max_price", "")

        with get_db() as conn:
            cursor = conn.cursor()
            # 仅获取角色为 'user' 的用户作为筛选选项
            seller_options = cursor.execute("SELECT user_id, user_name FROM AppUser WHERE role = 'user'").fetchall()
            buyer_options = cursor.execute("SELECT user_id, user_name FROM AppUser WHERE role = 'user'").fetchall()

        if selected_category not in QUERY_CATEGORIES:
            selected_category = "全部类别"

        with get_db() as conn:
            cursor = conn.cursor()
            
            # 综合查询逻辑：整合商品与订单数据
            where_clauses = []
            params = []
            
            if selected_status == "在售":
                where_clauses.append("i.status = 0")
            elif selected_status == "已售":
                where_clauses.append("i.status = 1")
            elif selected_status == "已下架":
                where_clauses.append("i.status = 2")
            
            if selected_category != "全部类别":
                if selected_category == "生活用品":
                    where_clauses.append("i.category IN ('生活用品', 'DailyGoods')")
                else:
                    where_clauses.append("i.category = ?")
                    params.append(selected_category)
            
            if selected_seller_id:
                where_clauses.append("i.seller_id = ?")
                params.append(selected_seller_id)
                
            if selected_buyer_id:
                where_clauses.append("o.buyer_id = ?")
                params.append(selected_buyer_id)

            if min_price:
                try:
                    where_clauses.append("i.price >= ?")
                    params.append(float(min_price))
                except ValueError:
                    min_price = ""
            
            if max_price:
                try:
                    where_clauses.append("i.price <= ?")
                    params.append(float(max_price))
                except ValueError:
                    max_price = ""
            
            where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
            
            query = f"""
                SELECT 
                    i.item_id, 
                    i.item_name, 
                    i.category, 
                    i.price, 
                    i.status || CASE 
                                   WHEN i.status = 0 THEN ' (在售)'
                                   WHEN i.status = 1 THEN ' (已售)'
                                   WHEN i.status = 2 THEN ' (下架)'
                                 END as status_text,
                    i.seller_id,
                    IFNULL(o.buyer_id, '-') as buyer_id,
                    IFNULL(o.order_date, '-') as order_date
                FROM Item i
                LEFT JOIN Orders o ON i.item_id = o.item_id
                {where_sql}
                ORDER BY i.item_id DESC
            """
            combined_items = cursor.execute(query, params).fetchall()

            raw_queries_data = [
                (
                    "综合查询结果",
                    ["ID", "名称", "类别", "价格", "状态 (注释)", "卖家ID", "买家ID", "成交日期"],
                    combined_items,
                ),
                (
                    "市场统计概况",
                    ["统计项", "数值"],
                    [
                        ("有效商品总数 (在售+已售)", cursor.execute("SELECT COUNT(*) FROM Item WHERE status IN (0, 1)").fetchone()[0]),
                        ("当前在售数量", cursor.execute("SELECT COUNT(*) FROM Item WHERE status = 0").fetchone()[0]),
                        ("在售商品平均价格", f"¥{cursor.execute('SELECT ROUND(AVG(price), 2) FROM Item WHERE status = 0').fetchone()[0] or 0}"),
                    ],
                ),
                (
                    "各类商品分布",
                    ["商品类别", "库存数量"],
                    cursor.execute(
                        """
                        SELECT category, COUNT(*) 
                        FROM Item 
                        WHERE status IN (0, 1) 
                        GROUP BY category 
                        ORDER BY COUNT(*) DESC
                        """
                    ).fetchall(),
                ),
                (
                    "活跃卖家排行 (前三)",
                    ["排名", "用户ID", "发布数量"],
                    [
                        (i + 1, row[0], row[1])
                        for i, row in enumerate(cursor.execute(
                            """
                            SELECT seller_id, COUNT(*) AS c
                            FROM Item
                            GROUP BY seller_id
                            ORDER BY c DESC
                            LIMIT 3
                            """
                        ).fetchall())
                    ],
                ),
            ]

        queries_data = [
            (
                title,
                headers,
                mark_current_user_as_self(headers, rows, profile[0]),
            )
            for title, headers, rows in raw_queries_data
        ]

        return render_template(
            "statics.html",
            queries_data=queries_data,
            query_categories=QUERY_CATEGORIES,
            selected_category=selected_category,
            seller_options=seller_options,
            selected_seller_id=selected_seller_id,
            buyer_options=buyer_options,
            selected_buyer_id=selected_buyer_id,
            selected_status=selected_status,
            min_price=min_price,
            max_price=max_price,
            **build_template_context(profile),
        )
