from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, declarative_base, scoped_session
from sqlalchemy.exc import IntegrityError
import os, json

# --- Config ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///shop.db")

# --- App & DB setup ---
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()

# --- Models ---
class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True)
    description = Column(Text, default="")
    image_filename = Column(String(255), default="")
    styles = relationship("Style", back_populates="category", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="category")

class Style(Base):
    __tablename__ = "styles"
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
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
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    style_id = Column(Integer, ForeignKey("styles.id"), nullable=True, index=True)
    variants = relationship("Variant", back_populates="product", cascade="all, delete-orphan")

    category = relationship("Category", back_populates="products")
    style = relationship("Style", back_populates="products")

    @property
    def price_display(self):
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

# Create tables if not exists
Base.metadata.create_all(engine)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- Helpers ---
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

# --- Public routes ---
@app.route("/")
def index():
    db = SessionLocal()
    categories = db.query(Category).order_by(Category.id.desc()).all()
    return render_template("categories.html", categories=categories)

@app.route("/category/<int:category_id>")
def category_detail(category_id):
    db = SessionLocal()
    c = db.get(Category, category_id)
    if not c:
        flash("找不到類別", "warning"); return redirect(url_for("index"))
    products = db.query(Product).filter_by(category_id=category_id).order_by(Product.id.desc()).all()
    return render_template("category_detail.html", category=c, styles=c.styles, products=products)

@app.route("/style/<int:style_id>")
def style_detail(style_id):
    db = SessionLocal()
    s = db.get(Style, style_id)
    if not s:
        flash("找不到款式", "warning"); return redirect(url_for("index"))
    products = db.query(Product).filter_by(style_id=style_id).order_by(Product.id.desc()).all()
    return render_template("style_detail.html", style=s, products=products)

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    db = SessionLocal()
    product = db.get(Product, product_id)
    if not product:
        flash("找不到商品", "warning"); return redirect(url_for("index"))
    return render_template("product_detail.html", product=product)

# --- Admin auth ---
@app.route("/admin/login", methods=["GET","POST"])
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

# --- Admin: dashboard ---
@app.route("/admin")
def admin_dashboard():
    if not admin_required(): return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")

# --- Admin: categories ---
@app.route("/admin/categories")
def admin_categories():
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    categories = db.query(Category).order_by(Category.id.desc()).all()
    return render_template("admin_categories.html", categories=categories)

@app.route("/admin/categories/new", methods=["GET","POST"])
def admin_category_new():
    if not admin_required(): return redirect(url_for("admin_login"))
    if request.method == "POST":
        name = request.form.get("name","").strip()
        description = request.form.get("description","").strip()
        image = request.files.get("image")
        image_filename = save_image(image) if image and image.filename else ""
        db = SessionLocal()
        if db.query(Category).filter(Category.name == name).first():
            flash("此類別名稱已存在，請換一個。", "danger")
            return redirect(url_for("admin_category_new"))
        db.add(Category(name=name, description=description, image_filename=image_filename))
        db.commit()
        flash("已新增類別", "success")
        return redirect(url_for("admin_categories"))
    return render_template("admin_category_form.html", category=None)

@app.route("/admin/categories/<int:category_id>/edit", methods=["GET","POST"])
def admin_category_edit(category_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    c = db.get(Category, category_id)
    if not c:
        flash("找不到類別", "warning"); return redirect(url_for("admin_categories"))
    if request.method == "POST":
        c.name = request.form.get("name","").strip()
        c.description = request.form.get("description","").strip()
        image = request.files.get("image")
        if image and image.filename:
            saved = save_image(image)
            if saved: c.image_filename = saved
        if db.query(Category).filter(Category.name == c.name, Category.id != category_id).first():
            flash("此類別名稱已存在，請換一個。", "danger")
            return redirect(url_for("admin_category_edit", category_id=category_id))
        try:
            db.add(c); db.commit()
            flash("類別已更新", "success")
        except IntegrityError:
            db.rollback()
            flash("類別名稱重複，請換一個。", "danger")
        return redirect(url_for("admin_categories"))
    return render_template("admin_category_form.html", category=c)

@app.route("/admin/categories/<int:category_id>/delete", methods=["POST"])
def admin_category_delete(category_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    c = db.get(Category, category_id)
    if c:
        db.delete(c); db.commit()
        flash("已刪除類別", "info")
    return redirect(url_for("admin_categories"))

# --- Admin: styles ---
@app.route("/admin/categories/<int:category_id>/styles", methods=["GET","POST"])
def admin_styles(category_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    c = db.get(Category, category_id)
    if not c: flash("找不到類別", "warning"); return redirect(url_for("admin_categories"))
    if request.method == "POST":
        name = request.form.get("name","").strip()
        description = request.form.get("description","").strip()
        image = request.files.get("image")
        image_filename = save_image(image) if image and image.filename else ""
        db.add(Style(category_id=c.id, name=name, description=description, image_filename=image_filename))
        db.commit(); flash("已新增款式", "success")
        return redirect(url_for("admin_styles", category_id=category_id))
    styles = db.query(Style).filter_by(category_id=c.id).order_by(Style.id.desc()).all()
    return render_template("admin_styles.html", category=c, styles=styles)

@app.route("/admin/styles/<int:style_id>/edit", methods=["POST"])
def admin_style_edit(style_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    s = db.get(Style, style_id)
    if not s: flash("找不到款式", "warning"); return redirect(url_for("admin_categories"))
    s.name = request.form.get("name","").strip()
    s.description = request.form.get("description","").strip()
    image = request.files.get("image")
    if image and image.filename:
        saved = save_image(image)
        if saved: s.image_filename = saved
    db.add(s); db.commit(); flash("款式已更新", "success")
    return redirect(url_for("admin_styles", category_id=s.category_id))

@app.route("/admin/styles/<int:style_id>/delete", methods=["POST"])
def admin_style_delete(style_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    s = db.get(Style, style_id)
    if s:
        cid = s.category_id
        db.delete(s); db.commit(); flash("已刪除款式", "info")
        return redirect(url_for("admin_styles", category_id=cid))
    return redirect(url_for("admin_categories"))

# --- Admin: products ---
@app.route("/admin/products")
def admin_products():
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    products = db.query(Product).order_by(Product.id.desc()).all()
    categories = db.query(Category).order_by(Category.name).all()
    styles = db.query(Style).order_by(Style.name).all()
    return render_template("admin_products.html", products=products, categories=categories, styles=styles)

@app.route("/admin/products/new", methods=["GET","POST"])
def admin_product_new():
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    categories = db.query(Category).order_by(Category.name).all()
    styles = db.query(Style).order_by(Style.name).all()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        price_str = request.form.get("price","0").strip()
        description = request.form.get("description","").strip()
        image = request.files.get("image")
        category_id = request.form.get("category_id") or None
        style_id = request.form.get("style_id") or None
        try: price_cents = int(round(float(price_str)*100))
        except: price_cents = 0
        image_filename = save_image(image) if image and image.filename else ""
        p = Product(name=name, price_cents=price_cents, description=description, image_filename=image_filename,
                    category_id=int(category_id) if category_id else None,
                    style_id=int(style_id) if style_id else None)
        db.add(p); db.commit(); flash("已新增商品", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin_product_form.html", product=None, categories=categories, styles=styles)

@app.route("/admin/products/<int:product_id>/edit", methods=["GET","POST"])
def admin_product_edit(product_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    p = db.get(Product, product_id)
    if not p: flash("找不到商品", "warning"); return redirect(url_for("admin_products"))
    categories = db.query(Category).order_by(Category.name).all()
    styles = db.query(Style).order_by(Style.name).all()
    if request.method == "POST":
        p.name = request.form.get("name","").strip()
        price_str = request.form.get("price","0").strip()
        try: p.price_cents = int(round(float(price_str)*100))
        except: pass
        p.description = request.form.get("description","").strip()
        image = request.files.get("image")
        if image and image.filename:
            saved = save_image(image)
            if saved: p.image_filename = saved
        category_id = request.form.get("category_id") or None
        style_id = request.form.get("style_id") or None
        p.category_id = int(category_id) if category_id else None
        p.style_id = int(style_id) if style_id else None
        db.add(p); db.commit(); flash("商品已更新", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin_product_form.html", product=p, categories=categories, styles=styles)

@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
def admin_product_delete(product_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    p = db.get(Product, product_id)
    if p:
        db.delete(p); db.commit(); flash("已刪除商品", "info")
    return redirect(url_for("admin_products"))

# --- Admin: variants ---
@app.route("/admin/products/<int:product_id>/variants", methods=["GET","POST"])
def admin_variants(product_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    p = db.get(Product, product_id)
    if not p: flash("找不到商品", "warning"); return redirect(url_for("admin_products"))
    if request.method == "POST":
        sku = request.form.get("sku","").strip()
        stock = int(request.form.get("stock","0") or 0)
        attributes_json = request.form.get("attributes_json","{}") or "{}"
        try: json.loads(attributes_json)
        except: flash("屬性 JSON 格式錯誤，請修正後再送出。", "danger"); return redirect(url_for("admin_variants", product_id=product_id))
        v = Variant(product_id=p.id, sku=sku, stock=stock, attributes_json=attributes_json)
        db.add(v); db.commit(); flash("已新增規格/尺寸", "success")
        return redirect(url_for("admin_variants", product_id=product_id))
    variants = db.query(Variant).filter_by(product_id=p.id).order_by(Variant.id.desc()).all()
    return render_template("admin_variants.html", product=p, variants=variants)

@app.route("/admin/variants/<int:variant_id>/edit", methods=["POST"])
def admin_variant_edit(variant_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    v = db.get(Variant, variant_id)
    if not v: flash("找不到規格", "warning"); return redirect(url_for("admin_products"))
    v.sku = request.form.get("sku","").strip()
    v.stock = int(request.form.get("stock","0") or 0)
    attributes_json = request.form.get("attributes_json","{}") or "{}"
    try: json.loads(attributes_json)
    except: flash("屬性 JSON 格式錯誤，請修正後再送出。", "danger"); return redirect(url_for("admin_variants", product_id=v.product_id))
    v.attributes_json = attributes_json
    db.add(v); db.commit(); flash("規格已更新", "success")
    return redirect(url_for("admin_variants", product_id=v.product_id))

@app.route("/admin/variants/<int:variant_id>/delete", methods=["POST"])
def admin_variant_delete(variant_id):
    if not admin_required(): return redirect(url_for("admin_login"))
    db = SessionLocal()
    v = db.get(Variant, variant_id)
    if v:
        pid = v.product_id
        db.delete(v); db.commit(); flash("已刪除規格", "info")
        return redirect(url_for("admin_variants", product_id=pid))
    return redirect(url_for("admin_products"))

# --- Serving uploads ---
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

if __name__ == "__main__":
    db = SessionLocal()
    # Seed demo data for first run
    if db.query(Category).count() == 0:
        bib = Category(name="圍兜兜", description="手作寶寶圍兜兜")
        hair = Category(name="髮飾", description="手作髮飾")
        db.add_all([bib, hair]); db.commit()
        s1 = Style(category_id=bib.id, name="圓型")
        s2 = Style(category_id=bib.id, name="花型")
        s3 = Style(category_id=bib.id, name="360度型")
        db.add_all([s1, s2, s3]); db.commit()
        p = Product(name="示範圍兜 - 圓型 A", price_cents=39000, description="棉紗布圍兜，親膚吸水。", style_id=s1.id, category_id=bib.id)
        db.add(p); db.commit()
    app.run(host="0.0.0.0", port=5000, debug=True)
