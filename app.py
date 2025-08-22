from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory,
    abort,
)
from werkzeug.utils import secure_filename
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    Boolean,
)
from sqlalchemy.orm import (
    sessionmaker,
    relationship,
    declarative_base,
    scoped_session,
)
from sqlalchemy.exc import IntegrityError
import os
import json

# =========================
# 基本設定
# =========================
BASE_DIR = os.path.dirname(__file__)
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///shop.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)
SessionLocal = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================
# 資料模型
# =========================
class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True)
    description = Column(Text, default="")
    image_filename = Column(String(255), default="")
    styles = relationship(
        "Style", back_populates="category", cascade="all, delete-orphan"
    )
    products = relationship("Product", back_populates="category")


class Style(Base):
    __tablename__ = "styles"
    id = Column(Integer, primary_key=True)
    category_id = Column(
        Integer, ForeignKey("categories.id"), nullable=False, index=True
    )
    name = Column(String(150), nullable=False)
    description = Column(Text, default="")
    image_filename = Column(String(255), default="")
    category = relationship("Category", back_populates="styles")
    products = relationship("Product", back_populates="style")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    price_cents = Column(Integer, nullable=False, default=0)
    description = Column(Text, default="")
    image_filename = Column(String(255), default="")
    category_id = Column(
        Integer, ForeignKey("categories.id"), nullable=True, index=True
    )
    style_id = Column(Integer, ForeignKey("styles.id"), nullable=True, index=True)
    variants = relationship(
        "Variant", back_populates="product", cascade="all, delete-orphan"
    )

    category = relationship("Category", back_populates="products")
    style = relationship("Style", back_populates="products")

    @property
    def price_display(self) -> str:
        return f"{self.price_cents/100:.2f}"


class Variant(Base):
    __tablename__ = "variants"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    sku = Column(String(120), default="")
    stock = Column(Integer, default=0)
    attributes_json = Column(Text, default="{}")
    product = relationship("Product", back_populates="variants")

    def attributes(self):
        try:
            return json.loads(self.attributes_json or "{}")
        except Exception:
            return {}


class Fabric(Base):
    __tablename__ = "fabrics"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    origin = Column(String(120), default="")
    price_cents = Column(Integer, nullable=False, default=0)
    size = Column(String(120), default="")
    description = Column(Text, default="")
    image_filename = Column(String(255), default="")  # 主圖
    ref_image_filename = Column(String(255), default="")  # 舊版單一參考照（相容）
    is_clearance = Column(Boolean, default=False)
    clearance_price_cents = Column(Integer, nullable=True)

    ref_images = relationship(
        "FabricRef", back_populates="fabric", cascade="all, delete-orphan"
    )

    @property
    def price_display(self) -> str:
        return f"{(self.price_cents or 0)/100:.2f}"

    @property
    def clearance_price_display(self):
        if self.clearance_price_cents is None:
            return None
        return f"{(self.clearance_price_cents or 0)/100:.2f}"


class FabricRef(Base):
    __tablename__ = "fabric_refs"
    id = Column(Integer, primary_key=True)
    fabric_id = Column(Integer, ForeignKey("fabrics.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    fabric = relationship("Fabric", back_populates="ref_images")


class SiteSetting(Base):
    __tablename__ = "site_settings"
    key = Column(String(50), primary_key=True)
    value = Column(String(200), default="")  # "1" or "0"


Base.metadata.create_all(engine)


# =========================
# 工具函式
# =========================
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(file_storage):
    if file_storage and file_storage.filename and allowed_file(file_storage.filename):
        filename = secure_filename(file_storage.filename)
        path = os.path.join(UPLOAD_FOLDER, filename)
        base, ext = os.path.splitext(filename)
        i = 1
        while os.path.exists(path):
            filename = f"{base}_{i}{ext}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            i += 1
        file_storage.save(path)
        return filename
    return None


def parse_price_to_cents(text: str) -> int:
    try:
        return int(round(float((text or "0").strip()) * 100))
    except Exception:
        return 0


# =========================
# 站台開關（SiteSetting）
# =========================
def get_flag(key: str, default: bool = True) -> bool:
    db = SessionLocal()
    s = db.get(SiteSetting, key)
    if not s:
        return default
    return s.value == "1"


def set_flag(key: str, value: bool):
    db = SessionLocal()
    s = db.get(SiteSetting, key) or SiteSetting(key=key)
    s.value = "1" if value else "0"
    db.merge(s)
    db.commit()


@app.context_processor
def inject_flags():
    return dict(
        # 前台是否公開
        FLAG_public_shopfront=get_flag("public_shopfront", True),
        FLAG_public_fabrics_choose=get_flag("public_fabrics_choose", True),
        FLAG_public_fabrics_clearance=get_flag("public_fabrics_clearance", True),
        # 首頁是否顯示入口卡片
        FLAG_show_home_fabrics_choose=get_flag("show_home_fabrics_choose", True),
        FLAG_show_home_fabrics_clearance=get_flag("show_home_fabrics_clearance", True),
    )


# =========================
# 前台（Public）
# =========================
@app.route("/")
def index():
    # 關閉前台時，訪客顯示維護頁；已登入管理者仍可看
    if not get_flag("public_shopfront", True) and not session.get("is_admin"):
        return render_template("site_closed.html"), 403

    db = SessionLocal()
    categories = db.query(Category).order_by(Category.id.desc()).all()
    fabric_count = db.query(Fabric).count()
    clearance_count = (
        db.query(Fabric).filter(Fabric.is_clearance == True).count()
    )  # noqa: E712
    return render_template(
        "categories.html",
        categories=categories,
        fabric_count=fabric_count,
        clearance_count=clearance_count,
    )


@app.route("/category/<int:category_id>")
def category_detail(category_id):
    if not get_flag("public_shopfront", True) and not session.get("is_admin"):
        abort(404)
    db = SessionLocal()
    c = db.get(Category, category_id)
    if not c:
        flash("找不到類別", "warning")
        return redirect(url_for("index"))
    products = (
        db.query(Product)
        .filter_by(category_id=category_id)
        .order_by(Product.id.desc())
        .all()
    )
    return render_template(
        "category_detail.html", category=c, styles=c.styles, products=products
    )


@app.route("/style/<int:style_id>")
def style_detail(style_id):
    if not get_flag("public_shopfront", True) and not session.get("is_admin"):
        abort(404)
    db = SessionLocal()
    s = db.get(Style, style_id)
    if not s:
        flash("找不到款式", "warning")
        return redirect(url_for("index"))
    products = (
        db.query(Product).filter_by(style_id=style_id).order_by(Product.id.desc()).all()
    )
    return render_template("style_detail.html", style=s, products=products)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    if not get_flag("public_shopfront", True) and not session.get("is_admin"):
        abort(404)
    db = SessionLocal()
    p = db.get(Product, product_id)
    if not p:
        flash("找不到商品", "warning")
        return redirect(url_for("index"))
    return render_template("product_detail.html", product=p)


@app.route("/fabrics/choose")
def fabrics_choose():
    if not get_flag("public_fabrics_choose", True) and not session.get("is_admin"):
        abort(404)
    db = SessionLocal()
    fabrics = db.query(Fabric).order_by(Fabric.id.desc()).all()
    return render_template("fabrics_choose.html", fabrics=fabrics)


@app.route("/fabrics/clearance")
def fabrics_clearance():
    if not get_flag("public_fabrics_clearance", True) and not session.get("is_admin"):
        abort(404)
    db = SessionLocal()
    fabrics = (
        db.query(Fabric)
        .filter(Fabric.is_clearance == True)
        .order_by(Fabric.id.desc())
        .all()  # noqa: E712
    )
    return render_template("fabrics_clearance.html", fabrics=fabrics)


# =========================
# 後台登入/登出
# =========================
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("已登入管理後台", "success")
            return redirect(url_for("admin_dashboard"))
        flash("密碼錯誤", "danger")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("已登出", "info")
    return redirect(url_for("admin_login"))


def admin_required():
    if not session.get("is_admin"):
        flash("請先登入後台", "warning")
        return False
    return True


# =========================
# 後台總覽 + 設定
# =========================
@app.route("/admin")
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")


@app.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    if not admin_required():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        # 前台公開
        set_flag("public_shopfront", bool(request.form.get("public_shopfront")))
        set_flag(
            "public_fabrics_choose", bool(request.form.get("public_fabrics_choose"))
        )
        set_flag(
            "public_fabrics_clearance",
            bool(request.form.get("public_fabrics_clearance")),
        )
        # 首頁顯示
        set_flag(
            "show_home_fabrics_choose",
            bool(request.form.get("show_home_fabrics_choose")),
        )
        set_flag(
            "show_home_fabrics_clearance",
            bool(request.form.get("show_home_fabrics_clearance")),
        )
        flash("設定已儲存", "success")
        return redirect(url_for("admin_settings"))

    flags = dict(
        public_shopfront=get_flag("public_shopfront", True),
        public_fabrics_choose=get_flag("public_fabrics_choose", True),
        public_fabrics_clearance=get_flag("public_fabrics_clearance", True),
        show_home_fabrics_choose=get_flag("show_home_fabrics_choose", True),
        show_home_fabrics_clearance=get_flag("show_home_fabrics_clearance", True),
    )
    return render_template("admin_settings.html", flags=flags)


# =========================
# 後台：類別／款式
# =========================
@app.route("/admin/categories")
def admin_categories():
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    categories = db.query(Category).order_by(Category.id.desc()).all()
    return render_template("admin_categories.html", categories=categories)


@app.route("/admin/categories/new", methods=["GET", "POST"])
def admin_category_new():
    if not admin_required():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        image = request.files.get("image")
        image_filename = save_image(image) if image and image.filename else ""
        db = SessionLocal()
        if db.query(Category).filter(Category.name == name).first():
            flash("此類別名稱已存在，請換一個。", "danger")
            return redirect(url_for("admin_category_new"))
        db.add(
            Category(name=name, description=description, image_filename=image_filename)
        )
        db.commit()
        flash("已新增類別", "success")
        return redirect(url_for("admin_categories"))
    return render_template("admin_category_form.html", category=None)


@app.route("/admin/categories/<int:category_id>/edit", methods=["GET", "POST"])
def admin_category_edit(category_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    c = db.get(Category, category_id)
    if not c:
        flash("找不到類別", "warning")
        return redirect(url_for("admin_categories"))

    if request.method == "POST":
        new_name = request.form.get("name", "").strip()
        c.description = request.form.get("description", "").strip()
        image = request.files.get("image")
        if image and image.filename:
            saved = save_image(image)
            if saved:
                c.image_filename = saved

        # 檢查重名（排除自己）
        if (
            new_name
            and new_name != c.name
            and db.query(Category)
            .filter(Category.name == new_name, Category.id != c.id)
            .first()
        ):
            flash("此類別名稱已存在，請換一個。", "danger")
            return redirect(url_for("admin_category_edit", category_id=category_id))

        c.name = new_name or c.name
        try:
            db.add(c)
            db.commit()
            flash("類別已更新", "success")
        except IntegrityError:
            db.rollback()
            flash("類別名稱重複，請換一個。", "danger")
        return redirect(url_for("admin_categories"))

    return render_template("admin_category_form.html", category=c)


@app.route("/admin/categories/<int:category_id>/delete", methods=["POST"])
def admin_category_delete(category_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    c = db.get(Category, category_id)
    if c:
        db.delete(c)
        db.commit()
        flash("已刪除類別", "info")
    return redirect(url_for("admin_categories"))


@app.route("/admin/categories/<int:category_id>/styles", methods=["GET", "POST"])
def admin_styles(category_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    c = db.get(Category, category_id)
    if not c:
        flash("找不到類別", "warning")
        return redirect(url_for("admin_categories"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        image = request.files.get("image")
        image_filename = save_image(image) if image and image.filename else ""
        db.add(
            Style(
                category_id=c.id,
                name=name,
                description=description,
                image_filename=image_filename,
            )
        )
        db.commit()
        flash("已新增款式", "success")
        return redirect(url_for("admin_styles", category_id=category_id))

    styles = db.query(Style).filter_by(category_id=c.id).order_by(Style.id.desc()).all()
    return render_template("admin_styles.html", category=c, styles=styles)


@app.route("/admin/styles/<int:style_id>/edit", methods=["POST"])
def admin_style_edit(style_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    s = db.get(Style, style_id)
    if not s:
        flash("找不到款式", "warning")
        return redirect(url_for("admin_categories"))

    s.name = request.form.get("name", "").strip()
    s.description = request.form.get("description", "").strip()
    image = request.files.get("image")
    if image and image.filename:
        saved = save_image(image)
        if saved:
            s.image_filename = saved
    db.add(s)
    db.commit()
    flash("款式已更新", "success")
    return redirect(url_for("admin_styles", category_id=s.category_id))


@app.route("/admin/styles/<int:style_id>/delete", methods=["POST"])
def admin_style_delete(style_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    s = db.get(Style, style_id)
    if s:
        cid = s.category_id
        db.delete(s)
        db.commit()
        flash("已刪除款式", "info")
        return redirect(url_for("admin_styles", category_id=cid))
    return redirect(url_for("admin_categories"))


# =========================
# 後台：商品／規格
# =========================
@app.route("/admin/products")
@app.route("/admin/products")
def admin_products():
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()

    # 讀取篩選參數
    cat_id = request.args.get("category_id", type=int)
    style_id = request.args.get("style_id", type=int)

    q = db.query(Product)
    if cat_id:
        q = q.filter(Product.category_id == cat_id)
    if style_id:
        q = q.filter(Product.style_id == style_id)

    products = q.order_by(Product.id.desc()).all()
    categories = db.query(Category).order_by(Category.name).all()
    styles = db.query(Style).order_by(Style.name).all()

    current_category = db.get(Category, cat_id) if cat_id else None
    current_style = db.get(Style, style_id) if style_id else None

    return render_template(
        "admin_products.html",
        products=products,
        categories=categories,
        styles=styles,
        current_category=current_category,
        current_style=current_style,
    )


@app.route("/admin/products/new", methods=["GET", "POST"])
def admin_product_new():
    if not admin_required():
        return redirect(url_for("admin_login"))

    db = SessionLocal()
    categories = db.query(Category).order_by(Category.name).all()
    styles = db.query(Style).order_by(Style.name).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price_str = request.form.get("price", "0").strip()
        description = request.form.get("description", "").strip()
        image = request.files.get("image")
        category_id = request.form.get("category_id") or None
        style_id = request.form.get("style_id") or None

        price_cents = parse_price_to_cents(price_str)
        image_filename = save_image(image) if image and image.filename else ""

        p = Product(
            name=name,
            price_cents=price_cents,
            description=description,
            image_filename=image_filename,
            category_id=int(category_id) if category_id else None,
            style_id=int(style_id) if style_id else None,
        )
        db.add(p)
        db.commit()
        flash("已新增商品", "success")
        return redirect(url_for("admin_products"))

    return render_template(
        "admin_product_form.html", product=None, categories=categories, styles=styles
    )


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
def admin_product_edit(product_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    p = db.get(Product, product_id)
    if not p:
        flash("找不到商品", "warning")
        return redirect(url_for("admin_products"))

    categories = db.query(Category).order_by(Category.name).all()
    styles = db.query(Style).order_by(Style.name).all()

    if request.method == "POST":
        p.name = request.form.get("name", "").strip()
        price_str = request.form.get("price", "0").strip()
        p.price_cents = parse_price_to_cents(price_str) or p.price_cents
        p.description = request.form.get("description", "").strip()
        image = request.files.get("image")
        if image and image.filename:
            saved = save_image(image)
            if saved:
                p.image_filename = saved
        category_id = request.form.get("category_id") or None
        style_id = request.form.get("style_id") or None
        p.category_id = int(category_id) if category_id else None
        p.style_id = int(style_id) if style_id else None

        db.add(p)
        db.commit()
        flash("商品已更新", "success")
        return redirect(url_for("admin_products"))

    return render_template(
        "admin_product_form.html", product=p, categories=categories, styles=styles
    )


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
def admin_product_delete(product_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    p = db.get(Product, product_id)
    if p:
        db.delete(p)
        db.commit()
        flash("已刪除商品", "info")
    return redirect(url_for("admin_products"))


@app.route("/admin/products/<int:product_id>/variants", methods=["GET", "POST"])
def admin_variants(product_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    p = db.get(Product, product_id)
    if not p:
        flash("找不到商品", "warning")
        return redirect(url_for("admin_products"))

    if request.method == "POST":
        sku = request.form.get("sku", "").strip()
        stock = int(request.form.get("stock", "0") or 0)
        attributes_json = request.form.get("attributes_json", "{}") or "{}"
        try:
            json.loads(attributes_json)
        except Exception:
            flash("屬性 JSON 格式錯誤，請修正後再送出。", "danger")
            return redirect(url_for("admin_variants", product_id=product_id))

        v = Variant(
            product_id=p.id, sku=sku, stock=stock, attributes_json=attributes_json
        )
        db.add(v)
        db.commit()
        flash("已新增規格/尺寸", "success")
        return redirect(url_for("admin_variants", product_id=product_id))

    variants = (
        db.query(Variant).filter_by(product_id=p.id).order_by(Variant.id.desc()).all()
    )
    return render_template("admin_variants.html", product=p, variants=variants)


@app.route("/admin/variants/<int:variant_id>/edit", methods=["POST"])
def admin_variant_edit(variant_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    v = db.get(Variant, variant_id)
    if not v:
        flash("找不到規格", "warning")
        return redirect(url_for("admin_products"))

    v.sku = request.form.get("sku", "").strip()
    v.stock = int(request.form.get("stock", "0") or 0)
    attributes_json = request.form.get("attributes_json", "{}") or "{}"
    try:
        json.loads(attributes_json)
    except Exception:
        flash("屬性 JSON 格式錯誤，請修正後再送出。", "danger")
        return redirect(url_for("admin_variants", product_id=v.product_id))
    v.attributes_json = attributes_json

    db.add(v)
    db.commit()
    flash("規格已更新", "success")
    return redirect(url_for("admin_variants", product_id=v.product_id))


@app.route("/admin/variants/<int:variant_id>/delete", methods=["POST"])
def admin_variant_delete(variant_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    v = db.get(Variant, variant_id)
    if v:
        pid = v.product_id
        db.delete(v)
        db.commit()
        flash("已刪除規格", "info")
        return redirect(url_for("admin_variants", product_id=pid))
    return redirect(url_for("admin_products"))


# =========================
# 後台：布料（支援多參考作品）
# =========================
@app.route("/admin/fabrics")
def admin_fabrics():
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    fabrics = db.query(Fabric).order_by(Fabric.id.desc()).all()
    return render_template("admin_fabrics.html", fabrics=fabrics)


@app.route("/admin/fabrics/new", methods=["GET", "POST"])
def admin_fabric_new():
    if not admin_required():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        db = SessionLocal()
        name = request.form.get("name", "").strip()
        origin = request.form.get("origin", "").strip()
        size = request.form.get("size", "").strip()
        description = request.form.get("description", "").strip()
        price_cents = parse_price_to_cents(request.form.get("price", "0"))
        is_clearance = bool(request.form.get("is_clearance"))
        cp_text = request.form.get("clearance_price", "").strip()
        clearance_price_cents = parse_price_to_cents(cp_text) if cp_text else None
        image = request.files.get("image")
        image_filename = save_image(image) if image and image.filename else ""

        f = Fabric(
            name=name,
            origin=origin,
            size=size,
            description=description,
            price_cents=price_cents,
            is_clearance=is_clearance,
            clearance_price_cents=clearance_price_cents,
            image_filename=image_filename,
        )
        db.add(f)
        db.commit()

        # 多張參考作品
        for fs in request.files.getlist("ref_images"):
            if fs and fs.filename:
                saved = save_image(fs)
                if saved:
                    db.add(FabricRef(fabric_id=f.id, filename=saved))
        db.commit()

        flash("已新增布料紀錄", "success")
        return redirect(url_for("admin_fabrics"))

    return render_template("admin_fabric_form.html", fabric=None)


@app.route("/admin/fabrics/<int:fabric_id>/edit", methods=["GET", "POST"])
def admin_fabric_edit(fabric_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    f = db.get(Fabric, fabric_id)
    if not f:
        flash("找不到布料", "warning")
        return redirect(url_for("admin_fabrics"))

    if request.method == "POST":
        f.name = request.form.get("name", "").strip()
        f.origin = request.form.get("origin", "").strip()
        f.size = request.form.get("size", "").strip()
        f.description = request.form.get("description", "").strip()
        f.price_cents = (
            parse_price_to_cents(request.form.get("price", "0")) or f.price_cents
        )
        f.is_clearance = bool(request.form.get("is_clearance"))
        cp_text = request.form.get("clearance_price", "").strip()
        f.clearance_price_cents = parse_price_to_cents(cp_text) if cp_text else None

        image = request.files.get("image")
        if image and image.filename:
            saved = save_image(image)
            if saved:
                f.image_filename = saved

        db.add(f)
        db.commit()

        # 新增更多參考作品
        for fs in request.files.getlist("ref_images"):
            if fs and fs.filename:
                saved = save_image(fs)
                if saved:
                    db.add(FabricRef(fabric_id=f.id, filename=saved))
        db.commit()

        flash("布料已更新", "success")
        return redirect(url_for("admin_fabrics"))

    return render_template("admin_fabric_form.html", fabric=f)


@app.route("/admin/fabrics/<int:fabric_id>/delete", methods=["POST"])
def admin_fabric_delete(fabric_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    f = db.get(Fabric, fabric_id)
    if f:
        db.delete(f)
        db.commit()
        flash("已刪除布料", "info")
    return redirect(url_for("admin_fabrics"))


@app.route("/admin/fabrics/<int:fabric_id>/refs/<int:ref_id>/delete", methods=["POST"])
def admin_fabric_ref_delete(fabric_id, ref_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db = SessionLocal()
    ref = db.get(FabricRef, ref_id)
    if ref and ref.fabric_id == fabric_id:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, ref.filename))
        except Exception:
            pass
        db.delete(ref)
        db.commit()
        flash("已刪除參考作品圖片", "info")
    return redirect(url_for("admin_fabric_edit", fabric_id=fabric_id))


# =========================
# 檔案服務（可選）
# =========================
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# =========================
# Main（開發環境執行）
# =========================
if __name__ == "__main__":
    # 首次執行時：初始化一些旗標 / Demo 資料
    for k in [
        "public_shopfront",
        "public_fabrics_choose",
        "public_fabrics_clearance",
        "show_home_fabrics_choose",
        "show_home_fabrics_clearance",
    ]:
        set_flag(k, True)

    db = SessionLocal()
    if db.query(Category).count() == 0:
        bib = Category(name="圍兜兜", description="手作寶寶圍兜兜")
        hair = Category(name="髮飾", description="手作髮飾")
        db.add_all([bib, hair])
        db.commit()
        s1 = Style(category_id=bib.id, name="圓型")
        s2 = Style(category_id=bib.id, name="花型")
        s3 = Style(category_id=bib.id, name="360度型")
        db.add_all([s1, s2, s3])
        db.commit()
        p = Product(
            name="示範圍兜 - 圓型 A",
            price_cents=39000,
            description="棉紗布圍兜，親膚吸水。",
            style_id=s1.id,
            category_id=bib.id,
        )
        db.add(p)
        db.commit()

    if db.query(Fabric).count() == 0:
        db.add(
            Fabric(
                name="示範布料 - 小花棉布",
                origin="台灣",
                price_cents=25000,
                size="幅寬150cm",
                description="柔軟親膚。",
                is_clearance=False,
            )
        )
        db.add(
            Fabric(
                name="示範布料 - 條紋棉麻",
                origin="日本",
                price_cents=32000,
                size="幅寬140cm",
                description="透氣挺度佳。",
                is_clearance=True,
                clearance_price_cents=19900,
            )
        )
        db.commit()

    app.run(host="0.0.0.0", port=5000, debug=True)
