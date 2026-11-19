"""M MUSICS - music services marketplace (Flask). Run: python app.py"""
import os, secrets, smtplib, time, uuid, calendar as _cal, json
from email.message import EmailMessage
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, abort, g, send_from_directory, jsonify)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# On Vercel the deployment is a read-only serverless function. The only
# writable path is /tmp, so the SQLite database (when no DATABASE_URL is set)
# and uploaded media are written there. For a real production deploy set the
# DATABASE_URL env var to a managed Postgres and move uploads to S3/Cloudinary.
_IS_VERCEL = bool(os.environ.get("VERCEL"))
_WRITEABLE_ROOT = "/tmp" if _IS_VERCEL else os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.join(_WRITEABLE_ROOT, "mmusics.db")
_DEFAULT_DB_URI = os.environ.get(
    "DATABASE_URL", f"sqlite:///{_DEFAULT_DB_PATH}"
)
# Vercel serves files placed in /public directly from its CDN. We keep Flask's
# static assets under public/static/ and mount them at the /static URL prefix,
# so url_for('static', filename='style.css') -> /static/style.css. Vercel serves
# that path from public/static/style.css on the CDN (no function invocation),
# while Flask serves it in local dev. Using a prefix (not "") avoids clashes
# with real routes such as /logout.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "static")

app = Flask(__name__, static_folder=_STATIC_DIR, static_url_path="/static")
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-me-in-production"),
    SQLALCHEMY_DATABASE_URI=_DEFAULT_DB_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    SESSION_COOKIE_SAMESITE="Lax",
    PREFERRED_URL_SCHEME="https",
)
db = SQLAlchemy(app)
# Uploads land under /tmp on Vercel (the only writable, ephemeral location).
# They survive for the lifetime of a warm instance but are not shared, so for
# production you should point uploads at an object store (S3/R2/Cloudinary).
UPLOAD_DIR = os.environ.get("UPLOAD_DIR") or os.path.join(
    "/tmp/mmusics_uploads" if _IS_VERCEL else app.instance_path, "uploads"
)
IMG, AUDIO = {"png", "jpg", "jpeg", "webp"}, {"mp3", "wav", "m4a", "ogg"}
FAILS = {}

CATEGORIES = {
    "musicians": ("Hire Instrumentalists", "Instrument players only, for events, churches, schools and studios."),
    "composers": ("Composers", "Original songs, scores, jingles, arrangements and notation."),
    "producers": ("Producers", "Recording, mixing, mastering and beat production."),
    "trainers": ("Music Training", "Lessons and courses, in person or online."),
}
CAT_SINGULAR = {"musicians": "Instrumentalist", "composers": "Composer",
                "producers": "Producer", "trainers": "Trainer"}
INSTRUMENT_FAMILIES = ["Keyboard and piano", "Guitar", "Percussion", "Strings",
                       "Brass", "Woodwind", "Traditional African", "Other instrument"]
STATUSES = ["Pending", "Accepted", "Declined", "Confirmed",
            "In Progress", "Completed", "Cancelled"]
PAY_METHODS = ["MTN Mobile Money", "Airtel Money", "Bank payment", "Card"]
COMMISSION = 0.10  # platform commission on completed bookings (adjustable)

# Per-category accent colour (matches the .cat-* classes in style.css).
CAT_COLOR = {"musicians": "plum", "composers": "violet",
             "producers": "brass", "trainers": "teal"}

# Bundled stock images. provider_image()/product_image() pick a real photo for
# cards and profiles even when the artist has not uploaded one.
CAT_IMG = {"musicians": "img/musicians.jpg", "composers": "img/composers.jpg",
           "producers": "img/producers.jpg", "trainers": "img/trainers.jpg"}
SPEC_IMG = {
    "piano": "img/piano.jpg", "drum kit": "img/drums.jpeg", "drums": "img/drums.jpeg",
    "film scoring": "img/film.jpg", "mixing and mastering": "img/studio.jpg",
    "vocal training": "img/vocals.jpg",
}
PROD_IMG = {
    "keyboard": "img/keyboard.jpg", "guitar": "img/guitar.jpg",
    "drum": "img/drumkit.jpg", "microphone": "img/mic.jpg",
    "strings": "img/strings.jpg",
}


def provider_image(p):
    """Best image URL for a provider: uploaded photo -> specialisation stock
    photo -> category stock photo."""
    if p.photo:
        return url_for("media", name=p.photo)
    key = (p.specialisation or "").lower()
    for k, v in SPEC_IMG.items():
        if k in key:
            return url_for("static", filename=v)
    return url_for("static", filename=CAT_IMG.get(p.category, "img/musicians.jpg"))


def product_image(p):
    """Best image URL for a shop product."""
    if p.image:
        return url_for("media", name=p.image)
    name = (p.name or "").lower()
    for k, v in PROD_IMG.items():
        if k in name:
            return url_for("static", filename=v)
    return url_for("static", filename="img/musicians.jpg")

# Four kinds of user. Stored in User.role.
ROLES = {"superadmin": "Super admin",   # developers and site overseers
         "admin": "Admin",              # site owner and administrator
         "provider": "Artist",          # offers services
         "customer": "User"}            # books services and buys from the shop
STAFF_ROLES = ("admin", "superadmin")


# ---------------------------------------------------------------- models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    phone = db.Column(db.String(40))
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default="customer")  # customer|provider|admin|superadmin
    suspended = db.Column(db.Boolean, default=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    provider = db.relationship("Provider", backref="user", uselist=False)

    @property
    def is_staff(self):
        return self.role in STAFF_ROLES

    @property
    def is_superadmin(self):
        return self.role == "superadmin"

    @property
    def role_label(self):
        return ROLES.get(self.role, self.role)


class Provider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    category = db.Column(db.String(20), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    specialisation = db.Column(db.String(120), nullable=False)  # e.g. Piano
    genres = db.Column(db.String(200))
    bio = db.Column(db.Text)
    location = db.Column(db.String(120))
    experience_years = db.Column(db.Integer, default=0)
    rate = db.Column(db.Integer, default=0)  # UGX per hour (see rate_unit)
    rate_unit = db.Column(db.String(10), default="hour")  # hour | event
    availability = db.Column(db.String(200))  # free-text note (legacy)
    portfolio_url = db.Column(db.String(300))
    instrument_family = db.Column(db.String(40))
    photo = db.Column(db.String(80))
    audio = db.Column(db.String(80))
    approved = db.Column(db.Boolean, default=False)
    verified = db.Column(db.Boolean, default=False)
    featured = db.Column(db.Boolean, default=False)
    days = db.relationship("ProviderDay", backref="provider",
                           cascade="all, delete-orphan", lazy="dynamic")
    reviews = db.relationship("Review", backref="provider")

    @property
    def rating(self):
        r = [x.stars for x in self.reviews if x.approved]
        return round(sum(r) / len(r), 1) if r else None

    @property
    def rate_label(self):
        """Human rate label, e.g. 'UGX 150,000 / hour'."""
        ugx = f"{self.rate:,}" if self.rate else "0"
        suffix = {"hour": "/ hour", "event": "/ event"}.get(self.rate_unit, "/ hour")
        return f"UGX {ugx}{suffix}"


class ProviderDay(db.Model):
    """A provider's free/busy status for one calendar day (YYYY-MM-DD)."""
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("provider.id"), nullable=False)
    date = db.Column(db.String(20), nullable=False)        # 'YYYY-MM-DD'
    status = db.Column(db.String(10), default="free")       # free | busy
    note = db.Column(db.String(120))
    __table_args__ = (db.UniqueConstraint("provider_id", "date", name="uq_provider_day"),)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    provider_id = db.Column(db.Integer, db.ForeignKey("provider.id"))
    event_type = db.Column(db.String(120))
    date = db.Column(db.String(20))
    time = db.Column(db.String(20))
    location = db.Column(db.String(160))
    duration = db.Column(db.String(60))
    budget = db.Column(db.Integer)
    details = db.Column(db.Text)
    quote = db.Column(db.Integer)
    status = db.Column(db.String(20), default="Pending")
    created = db.Column(db.DateTime, default=datetime.utcnow)
    customer = db.relationship("User")
    provider = db.relationship("Provider")

    @property
    def paid(self):
        return any(p.status == "Paid" for p in self.payments)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("provider.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    stars = db.Column(db.Integer)
    comment = db.Column(db.Text)
    approved = db.Column(db.Boolean, default=True)  # admin can hide
    user = db.relationship("User")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(60))
    brand = db.Column(db.String(80))
    description = db.Column(db.Text)
    specs = db.Column(db.Text)
    price = db.Column(db.Integer, nullable=False)  # UGX
    stock = db.Column(db.Integer, default=0)
    warranty = db.Column(db.String(120))
    image = db.Column(db.String(80))


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    total = db.Column(db.Integer)
    address = db.Column(db.String(250))
    status = db.Column(db.String(20), default="Placed")  # Placed|Paid|Shipped|Delivered|Cancelled
    created = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship("OrderItem", backref="order")
    payment = db.relationship("Payment", backref="order", uselist=False)
    user = db.relationship("User")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"))
    qty = db.Column(db.Integer)
    price = db.Column(db.Integer)
    product = db.relationship("Product")


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(40))
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"))
    booking = db.relationship("Booking", backref="payments")
    method = db.Column(db.String(40))
    amount = db.Column(db.Integer)
    status = db.Column(db.String(20), default="Pending")
    created = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"))
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    text = db.Column(db.Text)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    booking = db.relationship("Booking", backref="messages")
    sender = db.relationship("User")


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    text = db.Column(db.String(250))
    read = db.Column(db.Boolean, default=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)


def notify(user_id, text):
    """Save an in-site notification and email it when SMTP_* env vars are set."""
    db.session.add(Notification(user_id=user_id, text=text))
    u, host = db.session.get(User, user_id), os.environ.get("SMTP_HOST")
    if u and host:
        try:
            m = EmailMessage()
            m["Subject"], m["To"] = "M MUSICS: " + text[:60], u.email
            m["From"] = os.environ.get("SMTP_FROM", "no-reply@mmusics.local")
            m.set_content(text)
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=10) as s:
                s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(m)
        except Exception as exc:  # never break a request over email
            app.logger.warning("Email failed: %s", exc)


# ---------------------------------------------------------------- helpers
@app.before_request
def load_user():
    session.setdefault("csrf", secrets.token_hex(16))
    if request.method == "POST" and not secrets.compare_digest(
            request.form.get("csrf", ""), session["csrf"]):
        abort(400)
    g.user = db.session.get(User, session["uid"]) if "uid" in session else None
    if g.user and g.user.suspended:
        session.pop("uid", None)
        g.user = None
        flash("Your account is suspended. Contact the site admin.", "error")
    g.unread = (Notification.query.filter_by(user_id=g.user.id, read=False).count()
                if g.user else 0)
    g.cart_count = sum(session.get("cart", {}).values())


@app.context_processor
def inject_csrf():
    theme = request.cookies.get("theme", "")
    if theme not in ("light", "dark"):
        theme = "auto"
    return {"csrf": session.get("csrf", ""),
            "theme": theme,
            "CATEGORIES": CATEGORIES,
            "CAT_COLOR": CAT_COLOR,
            "provider_image": provider_image,
            "product_image": product_image}


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def error_page(e):
    return render_template("error.html", e=e), e.code


def save_upload(field, allowed):
    f = request.files.get(field)
    if not f or not f.filename:
        return None
    ext = secure_filename(f.filename).rsplit(".", 1)[-1].lower()
    if ext not in allowed:
        flash(f"Unsupported file type. Allowed: {', '.join(sorted(allowed))}.", "error")
        return None
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    f.save(os.path.join(UPLOAD_DIR, name))
    return name


@app.route("/media/<name>")
def media(name):
    r = send_from_directory(UPLOAD_DIR, name)
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


@app.template_filter("ugx")
def ugx(v):
    return f"UGX {int(v or 0):,}"


@app.template_filter("to_date")
def to_date(s, fmt="%a %d %b %Y"):
    """Format a 'YYYY-MM-DD' string as a friendly date."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime(fmt)
    except (ValueError, TypeError):
        return s


def has_role(user, role):
    """'admin' means any staff (admin or super admin); 'superadmin' is developers only."""
    if role == "admin":
        return user.is_staff
    return user.role == role


def can_manage(actor, target):
    """Super admins manage everyone but themselves; admins manage non-staff only."""
    if actor.id == target.id:
        return False
    return actor.is_superadmin or (actor.is_staff and not target.is_staff)


def login_required(role=None):
    def deco(f):
        @wraps(f)
        def inner(*a, **kw):
            if not g.user:
                flash("Log in to continue.", "error")
                return redirect(url_for("login", next=request.path))
            if role and not has_role(g.user, role):
                abort(403)
            return f(*a, **kw)
        return inner
    return deco


# ---------------------------------------------------------------- public
@app.route("/")
def index():
    featured = {c: Provider.query.filter_by(category=c, approved=True)
                .order_by(Provider.featured.desc()).limit(3).all() for c in CATEGORIES}
    products = Product.query.order_by(Product.id.desc()).limit(4).all()
    return render_template("index.html", featured=featured, products=products)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/services")
def services():
    counts = {c: Provider.query.filter_by(category=c, approved=True).count() for c in CATEGORIES}
    counts["shop"] = Product.query.count()
    return render_template("services.html", counts=counts)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    like = f"%{q}%"
    providers = Provider.query.filter(Provider.approved, db.or_(
        Provider.display_name.ilike(like), Provider.specialisation.ilike(like),
        Provider.genres.ilike(like))).all() if q else []
    products = Product.query.filter(db.or_(
        Product.name.ilike(like), Product.brand.ilike(like),
        Product.category.ilike(like))).all() if q else []
    return render_template("search.html", q=q, providers=providers, products=products)


@app.route("/hire/<cat>")
def directory(cat):
    if cat not in CATEGORIES:
        abort(404)
    q = Provider.query.filter_by(category=cat, approved=True)
    a = request.args
    if a.get("family") in INSTRUMENT_FAMILIES:
        q = q.filter_by(instrument_family=a["family"])
    if a.get("specialisation"):
        q = q.filter(Provider.specialisation.ilike(f"%{a['specialisation']}%"))
    if a.get("location"):
        q = q.filter(Provider.location.ilike(f"%{a['location']}%"))
    if a.get("genre"):
        q = q.filter(Provider.genres.ilike(f"%{a['genre']}%"))
    if a.get("max_rate", type=int):
        q = q.filter(Provider.rate <= a.get("max_rate", type=int))
    if a.get("min_exp", type=int):
        q = q.filter(Provider.experience_years >= a.get("min_exp", type=int))
    results = q.order_by(Provider.featured.desc(), Provider.verified.desc()).all()
    title, blurb = CATEGORIES[cat]
    return render_template("directory.html", cat=cat, title=title, blurb=blurb,
                           results=results, args=a, families=INSTRUMENT_FAMILIES)


@app.route("/provider/<int:pid>")
def provider(pid):
    p = db.get_or_404(Provider, pid)
    if not p.approved and not (g.user and (g.user.is_staff or p.user_id == g.user.id)):
        abort(404)
    # Free days for the next 90 days, for the booking form's calendar hint.
    today = date.today()
    horizon = (today + timedelta(days=90)).strftime("%Y-%m-%d")
    day_map = {d.date: d.status for d in
               p.days.filter(ProviderDay.date >= today.strftime("%Y-%m-%d"),
                             ProviderDay.date <= horizon).all()}
    free_days = [d for d, s in day_map.items() if s == "free"]
    busy_days = [d for d, s in day_map.items() if s == "busy"]
    is_owner = g.user and (p.user_id == g.user.id)
    return render_template("provider.html", p=p, free_days=free_days,
                           busy_days=busy_days, is_owner=is_owner)


@app.route("/provider/<int:pid>/book", methods=["POST"])
@login_required()
def book(pid):
    p = db.get_or_404(Provider, pid)
    f = request.form
    if not p.approved or p.user_id == g.user.id:
        flash("You can't book this profile.", "error")
        return redirect(url_for("provider", pid=pid))
    if not f.get("date") or not f.get("event_type"):
        flash("Enter an event or project type and a date.", "error")
        return redirect(url_for("provider", pid=pid))
    # Block dates the provider explicitly marked busy.
    busy = p.days.filter_by(date=f["date"], status="busy").first()
    if busy:
        flash(f"{p.display_name} is marked unavailable on {f['date']}. "
              f"Pick another date.", "error")
        return redirect(url_for("provider", pid=pid))
    # Auto-quote when the provider charges by the hour and hours were given.
    quote = None
    if p.rate_unit == "hour" and p.rate:
        hours = _parse_hours(f.get("duration"))
        if hours:
            quote = p.rate * hours
    b = Booking(customer_id=g.user.id, provider_id=p.id, event_type=f["event_type"],
                date=f["date"], time=f.get("time"), location=f.get("location"),
                duration=f.get("duration"), budget=f.get("budget", type=int),
                details=f.get("details"), quote=quote)
    db.session.add(b)
    notify(p.user_id, f"New booking request from {g.user.name} for {b.date}.")
    db.session.commit()
    flash("Request sent. You'll be notified when the provider responds.", "ok")
    return redirect(url_for("dashboard"))


def _parse_hours(s):
    """Pull a number of hours out of free text like '3 hours' or '2.5h'."""
    if not s:
        return None
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", s.lower())
    if not m:
        return None
    try:
        h = float(m.group(1))
    except ValueError:
        return None
    return h if h > 0 else None


@app.route("/provider/<int:pid>/review", methods=["POST"])
@login_required()
def review(pid):
    p = db.get_or_404(Provider, pid)
    # An artist cannot rate their own profile.
    if p.user_id == g.user.id:
        flash("You can't review your own profile.", "error")
        return redirect(url_for("provider", pid=pid))
    done = Booking.query.filter_by(customer_id=g.user.id, provider_id=pid,
                                   status="Completed").first()
    if not done:
        flash("You can review a provider after a completed booking.", "error")
    else:
        db.session.add(Review(provider_id=pid, user_id=g.user.id,
                              stars=max(1, min(5, request.form.get("stars", 5, type=int))),
                              comment=request.form.get("comment", "")))
        db.session.commit()
        flash("Review posted.", "ok")
    return redirect(url_for("provider", pid=pid))


# ---------------------------------------------------------------- shop
@app.route("/shop")
def shop():
    q = Product.query
    a = request.args
    if a.get("category"):
        q = q.filter_by(category=a["category"])
    if a.get("brand"):
        q = q.filter(Product.brand.ilike(f"%{a['brand']}%"))
    if a.get("max_price", type=int):
        q = q.filter(Product.price <= a.get("max_price", type=int))
    cats = [c[0] for c in db.session.query(Product.category).distinct() if c[0]]
    return render_template("shop.html", products=q.all(), cats=cats, args=a)


@app.route("/product/<int:pid>")
def product(pid):
    return render_template("product.html", p=db.get_or_404(Product, pid))


def cart_items():
    items, total = [], 0
    for pid, qty in session.get("cart", {}).items():
        p = db.session.get(Product, int(pid))
        if p:
            items.append((p, qty))
            total += p.price * qty
    return items, total


@app.route("/cart")
def cart():
    items, total = cart_items()
    return render_template("cart.html", items=items, total=total)


@app.route("/cart/add/<int:pid>", methods=["POST"])
def cart_add(pid):
    p = db.get_or_404(Product, pid)
    c = session.get("cart", {})
    qty = c.get(str(pid), 0) + max(1, request.form.get("qty", 1, type=int))
    c[str(pid)] = min(qty, p.stock)
    session["cart"] = c
    flash(f"{p.name} added to cart." if p.stock else "Out of stock.", "ok")
    return redirect(request.referrer or url_for("shop"))


@app.route("/cart/remove/<int:pid>", methods=["POST"])
def cart_remove(pid):
    c = session.get("cart", {})
    c.pop(str(pid), None)
    session["cart"] = c
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
@login_required()
def checkout():
    items, total = cart_items()
    if not items:
        return redirect(url_for("cart"))
    if request.method == "POST":
        order = Order(user_id=g.user.id, total=total, address=request.form.get("address"))
        db.session.add(order)
        db.session.flush()
        for p, qty in items:
            if qty > p.stock:
                db.session.rollback()
                flash(f"Only {p.stock} of {p.name} left in stock.", "error")
                return redirect(url_for("cart"))
            p.stock -= qty
            db.session.add(OrderItem(order_id=order.id, product_id=p.id, qty=qty, price=p.price))
        notify(g.user.id, f"Order #{order.id} placed. Complete payment to confirm it.")
        db.session.commit()
        session["cart"] = {}
        return redirect(url_for("pay", kind="order", oid=order.id))
    return render_template("checkout.html", items=items, total=total)


# ---------------------------------------------------------------- accounts
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        if User.query.filter_by(email=f["email"].lower()).first():
            flash("That email already has an account. Log in instead.", "error")
        elif len(f["password"]) < 8:
            flash("Use a password of at least 8 characters.", "error")
        else:
            u = User(name=f["name"], email=f["email"].lower(), phone=f.get("phone"),
                     password_hash=generate_password_hash(f["password"]))
            db.session.add(u)
            db.session.commit()
            session["uid"] = u.id
            if f.get("account_type") == "artist":
                flash("Account created. Now set up your artist profile.", "ok")
                return redirect(url_for("become_provider"))
            return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr
        recent = FAILS[ip] = [t for t in FAILS.get(ip, []) if time.time() - t < 600]
        u = User.query.filter_by(email=request.form["email"].lower()).first()
        if len(recent) >= 10:
            flash("Too many failed attempts. Try again in 10 minutes.", "error")
        elif u and check_password_hash(u.password_hash, request.form["password"]) and u.suspended:
            flash("This account is suspended. Contact the site admin.", "error")
            return render_template("login.html")
        elif u and check_password_hash(u.password_hash, request.form["password"]):
            session["uid"] = u.id
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        if len(recent) < 10:
            recent.append(time.time())
            flash("Email or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/theme", methods=["POST"])
def set_theme():
    """Persist the chosen colour scheme in a cookie (1 year). Accepts the CSRF
    token as form data so it works from a normal form POST."""
    nxt = request.form.get("next") or request.referrer or url_for("index")
    nxt = nxt if nxt.startswith("/") else url_for("index")
    theme = request.form.get("theme", "auto")
    if theme not in ("light", "dark", "auto"):
        theme = "auto"
    resp = redirect(nxt)
    resp.set_cookie("theme", theme, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@app.route("/become-provider", methods=["GET", "POST"])
@login_required()
def become_provider():
    p = g.user.provider
    if request.method == "POST":
        f = request.form
        if f["category"] not in CATEGORIES:
            abort(400)
        if f["category"] == "musicians" and f.get("instrument_family") not in INSTRUMENT_FAMILIES:
            flash("Choose the instrument family you play. Only instrumentalists can list under Hire Instrumentalists.", "error")
            return render_template("provider_form.html", p=p, cats=CAT_SINGULAR, families=INSTRUMENT_FAMILIES)
        p = p or Provider(user_id=g.user.id)
        p.instrument_family = f["instrument_family"] if f["category"] == "musicians" else None
        for k in ("category", "display_name", "specialisation", "genres", "bio",
                  "location", "availability", "portfolio_url"):
            setattr(p, k, f.get(k))
        for field, kinds, attr in (("photo", IMG, "photo"), ("audio", AUDIO, "audio")):
            name = save_upload(field, kinds)
            if name:
                setattr(p, attr, name)
        p.rate = f.get("rate", 0, type=int)
        p.rate_unit = f.get("rate_unit") if f.get("rate_unit") in ("hour", "event") else "hour"
        p.experience_years = f.get("experience_years", 0, type=int)
        db.session.add(p)
        if g.user.role == "customer":
            g.user.role = "provider"
        db.session.commit()
        flash("Profile saved. It goes live after admin approval.", "ok")
        return redirect(url_for("dashboard"))
    return render_template("provider_form.html", p=p, cats=CAT_SINGULAR, families=INSTRUMENT_FAMILIES)


def _month_args(a):
    """Parse ?y= & ?m= from the query string, clamped to sane ranges."""
    today = date.today()
    y = max(2020, min(2099, a.get("y", type=int) or today.year))
    m = max(1, min(12, a.get("m", type=int) or today.month))
    return y, m


def _build_month(y, m, day_status):
    """Return the 6x7 week grid for year y / month m. Each cell is a dict
    {date, in_month, today, status}. `day_status` maps 'YYYY-MM-DD' -> status."""
    cal = _cal.Calendar(firstweekday=0)  # Monday-first
    today = date.today()
    weeks = []
    for week in cal.monthdatescalendar(y, m):
        cells = []
        for d in week:
            cells.append({
                "date": d,
                "iso": d.strftime("%Y-%m-%d"),
                "in_month": d.month == m,
                "today": d == today,
                "status": day_status.get(d.strftime("%Y-%m-%d")),
            })
        weeks.append(cells)
    return weeks


@app.route("/provider/<int:pid>/availability")
@login_required()
def provider_availability(pid):
    """Render the editable availability calendar for the provider's owner (or
    admin). GET shows a month grid; POST toggles a day free/busy."""
    p = db.get_or_404(Provider, pid)
    if p.user_id != g.user.id and not g.user.is_staff:
        abort(403)
    y, m = _month_args(request.args)
    rows = p.days.filter(ProviderDay.date.like(f"{y:04d}-{m:02d}-%")).all()
    day_status = {d.date: d.status for d in rows}
    cells = _build_month(y, m, day_status)
    return render_template("availability.html", p=p, cells=cells,
                           year=y, month=m, month_name=date(y, m, 1).strftime("%B %Y"),
                           prev={"y": y - (m == 1), "m": 12 if m == 1 else m - 1},
                           next={"y": y + (m == 12), "m": 1 if m == 12 else m + 1})


@app.route("/provider/<int:pid>/availability/toggle", methods=["POST"])
@login_required()
def provider_availability_toggle(pid):
    """Toggle one day free/busy. Returns JSON for the inline widget."""
    p = db.get_or_404(Provider, pid)
    if p.user_id != g.user.id and not g.user.is_staff:
        abort(403)
    d = request.form.get("date", "")
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        return jsonify(ok=False, error="bad date"), 400
    row = p.days.filter_by(date=d).first()
    if row:
        row.status = "busy" if row.status == "free" else "free"
    else:
        row = ProviderDay(provider_id=p.id, date=d, status="busy")
        db.session.add(row)
    db.session.commit()
    return jsonify(ok=True, status=row.status)


@app.route("/provider/<int:pid>/availability/clear", methods=["POST"])
@login_required()
def provider_availability_clear(pid):
    """Clear the whole month's free/busy marks."""
    p = db.get_or_404(Provider, pid)
    if p.user_id != g.user.id and not g.user.is_staff:
        abort(403)
    y = request.form.get("y", type=int)
    m = request.form.get("m", type=int)
    if y and m:
        p.days.filter(ProviderDay.date.like(f"{y:04d}-{m:02d}-%")).delete()
        db.session.commit()
        flash(f"Cleared all marks for {date(y, m, 1):%B %Y}.", "ok")
    return redirect(url_for("provider_availability", pid=pid, y=y, m=m))


@app.route("/dashboard")
@login_required()
def dashboard():
    if g.user.is_superadmin:
        return redirect(url_for("superadmin"))
    if g.user.is_staff:
        return redirect(url_for("admin"))
    notes = Notification.query.filter_by(user_id=g.user.id).order_by(Notification.id.desc()).limit(15).all()
    for n in notes:
        n.read = True
    db.session.commit()
    my_bookings = Booking.query.filter_by(customer_id=g.user.id).order_by(Booking.id.desc()).all()
    orders = Order.query.filter_by(user_id=g.user.id).order_by(Order.id.desc()).all()
    incoming = (Booking.query.filter_by(provider_id=g.user.provider.id)
                .order_by(Booking.id.desc()).all() if g.user.provider else [])
    # Booked-days calendar for the artist's own account page.
    booked_cells = None
    booked_month_name = None
    booked_prev = booked_next = None
    if g.user.provider:
        y, m = _month_args(request.args)
        # Active bookings (not cancelled or declined), grouped by date.
        day_bookings = {}
        for b in (incoming or []):
            if b.status in ("Cancelled", "Declined") or not b.date:
                continue
            day_bookings.setdefault(b.date, []).append(b)
        booked_cells = _build_month(y, m, {})  # cells without free/busy status
        # Annotate each cell with its bookings (for the booked-days calendar).
        for week in booked_cells:
            for cell in week:
                cell["bookings"] = day_bookings.get(cell["iso"], [])
        booked_month_name = date(y, m, 1).strftime("%B %Y")
        booked_prev = {"y": y - (m == 1), "m": 12 if m == 1 else m - 1}
        booked_next = {"y": y + (m == 12), "m": 1 if m == 12 else m + 1}
    return render_template("dashboard.html", notes=notes, my_bookings=my_bookings,
                           orders=orders, incoming=incoming,
                           booked_cells=booked_cells, booked_month_name=booked_month_name,
                           booked_prev=booked_prev, booked_next=booked_next)


@app.route("/booking/<int:bid>/<action>", methods=["POST"])
@login_required()
def booking_action(bid, action):
    b = db.get_or_404(Booking, bid)
    is_prov = g.user.provider and b.provider_id == g.user.provider.id
    is_cust = b.customer_id == g.user.id
    moves = {  # action: (new status, who, allowed from)
        "accept": ("Accepted", is_prov, ["Pending"]),
        "decline": ("Declined", is_prov, ["Pending"]),
        "confirm": ("Confirmed", is_cust, ["Accepted"]),
        "start": ("In Progress", is_prov, ["Confirmed"]),
        "complete": ("Completed", is_prov, ["In Progress", "Confirmed"]),
        "cancel": ("Cancelled", is_cust or is_prov, ["Pending", "Accepted", "Confirmed"]),
    }
    if action not in moves or not moves[action][1] or b.status not in moves[action][2]:
        abort(403)
    b.status = moves[action][0]
    other = b.customer_id if is_prov else b.provider.user_id
    notify(other, f"Booking #{b.id} is now {b.status}.")
    db.session.commit()
    return redirect(url_for("dashboard"))


def booking_for(bid):
    b = db.get_or_404(Booking, bid)
    if not (g.user.is_staff or b.customer_id == g.user.id or b.provider.user_id == g.user.id):
        abort(403)
    return b


@app.route("/booking/<int:bid>")
@login_required()
def booking_detail(bid):
    b = booking_for(bid)
    return render_template("booking.html", b=b, is_prov=b.provider.user_id == g.user.id)


@app.route("/booking/<int:bid>/message", methods=["POST"])
@login_required()
def booking_message(bid):
    b = booking_for(bid)
    text = request.form.get("text", "").strip()[:2000]
    if text:
        db.session.add(Message(booking_id=b.id, sender_id=g.user.id, text=text))
        notify(b.provider.user_id if g.user.id == b.customer_id else b.customer_id,
               f"New message on booking #{b.id}.")
        db.session.commit()
    return redirect(url_for("booking_detail", bid=bid))


@app.route("/booking/<int:bid>/quote", methods=["POST"])
@login_required()
def booking_quote(bid):
    b = booking_for(bid)
    amount = request.form.get("quote", type=int)
    if b.provider.user_id != g.user.id or b.status not in ("Pending", "Accepted") or not amount or amount < 1:
        abort(403)
    b.quote = amount
    notify(b.customer_id, f"Booking #{b.id}: quote of {amount:,} UGX.")
    db.session.commit()
    return redirect(url_for("booking_detail", bid=bid))


def charge(method, phone, amount, reference):
    """Return True when the payment succeeded.
    PAYMENT_MODE=demo (default): always succeeds, no real money moves.
    For live payments, call your MTN MoMo / Airtel / card gateway here."""
    if os.environ.get("PAYMENT_MODE", "demo") == "demo":
        return True
    raise NotImplementedError("Connect a payment gateway in charge().")


@app.route("/pay/<kind>/<int:oid>", methods=["GET", "POST"])
@login_required()
def pay(kind, oid):
    if kind == "order":
        obj = db.get_or_404(Order, oid)
        owner, amount, done = obj.user_id, obj.total, obj.status in ("Paid", "Shipped", "Delivered")
    elif kind == "booking":
        obj = db.get_or_404(Booking, oid)
        owner, amount, done = obj.customer_id, obj.quote, obj.paid
        if not amount or obj.status not in ("Accepted", "Confirmed", "In Progress", "Completed"):
            flash("Payment opens once the provider has accepted and set a quote.", "error")
            return redirect(url_for("booking_detail", bid=oid))
    else:
        abort(404)
    if owner != g.user.id:
        abort(403)
    if done:
        flash("This is already paid.", "ok")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        method, phone = request.form.get("method"), request.form.get("phone", "").strip()
        if method not in PAY_METHODS or (method.endswith("Money") and len(phone) < 9):
            flash("Choose a method and enter a valid mobile money number.", "error")
        else:
            rec = (obj.payment if kind == "order" else None) or Payment()
            rec.reference = f"MM-{kind[0].upper()}{oid:05d}-{secrets.token_hex(2).upper()}"
            rec.method, rec.amount = method, amount
            if kind == "order":
                rec.order_id = oid
            else:
                rec.booking_id = oid
            try:
                ok = charge(method, phone, amount, rec.reference)
            except NotImplementedError as exc:
                ok = False
                flash(str(exc), "error")
            rec.status = "Paid" if ok else "Pending"
            db.session.add(rec)
            if ok:
                if kind == "order":
                    obj.status = "Paid"
                else:
                    notify(obj.provider.user_id, f"Booking #{oid} has been paid.")
                notify(g.user.id, f"Payment received: {rec.reference}.")
                flash("Payment received. Thank you!", "ok")
            db.session.commit()
            if ok:
                return redirect(url_for("dashboard"))
    return render_template("pay.html", amount=amount, methods=PAY_METHODS,
                           demo=os.environ.get("PAYMENT_MODE", "demo") == "demo",
                           label=f"{kind.title()} #{oid}")


# ---------------------------------------------------------------- admin
@app.route("/admin")
@login_required("admin")
def admin():
    return render_template(
        "admin.html", users=User.query.count(),
        pending=Provider.query.filter_by(approved=False).all(),
        providers=Provider.query.filter_by(approved=True).all(),
        products=Product.query.all(), orders=Order.query.order_by(Order.id.desc()).all(),
        bookings=Booking.query.order_by(Booking.id.desc()).limit(30).all(),
        reviews=Review.query.order_by(Review.id.desc()).limit(30).all(),
        revenue=sum(o.total for o in Order.query.filter(Order.status.in_(["Paid", "Shipped", "Delivered"]))),
        commission=int(sum((b.budget or 0) for b in Booking.query.filter_by(status="Completed")) * COMMISSION),
        statuses=["Placed", "Paid", "Shipped", "Delivered", "Cancelled"])


@app.route("/admin/provider/<int:pid>/<action>", methods=["POST"])
@login_required("admin")
def admin_provider(pid, action):
    p = db.get_or_404(Provider, pid)
    if action == "approve":
        p.approved = True
        notify(p.user_id, "Your provider profile is approved and now public.")
    elif action == "reject":
        p.approved = False
    elif action == "verify":
        p.verified = not p.verified
    elif action == "feature":
        p.featured = not p.featured
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/product", methods=["POST"])
@login_required("admin")
def admin_product():
    f = request.form
    p = db.session.get(Product, f.get("id", type=int)) if f.get("id") else Product()
    for k in ("name", "category", "brand", "description", "specs", "warranty"):
        setattr(p, k, f.get(k))
    p.image = save_upload("image", IMG) or p.image
    p.price, p.stock = f.get("price", 0, type=int), f.get("stock", 0, type=int)
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/product/<int:pid>/delete", methods=["POST"])
@login_required("admin")
def admin_product_delete(pid):
    db.session.delete(db.get_or_404(Product, pid))
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/order/<int:oid>", methods=["POST"])
@login_required("admin")
def admin_order(oid):
    o = db.get_or_404(Order, oid)
    o.status = request.form["status"]
    if o.payment and o.status in ("Paid", "Shipped", "Delivered"):
        o.payment.status = "Paid"
    notify(o.user_id, f"Order #{o.id} is now {o.status}.")
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/review/<int:rid>", methods=["POST"])
@login_required("admin")
def admin_review(rid):
    r = db.get_or_404(Review, rid)
    r.approved = not r.approved
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/users")
@login_required("admin")
def admin_users():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(User.name.ilike(like), User.email.ilike(like)))
    if role in ROLES:
        query = query.filter_by(role=role)
    return render_template("users.html", users=query.order_by(User.id.desc()).limit(200).all(),
                           args=request.args, roles=ROLES, can_manage=can_manage)


@app.route("/admin/user/<int:uid>/suspend", methods=["POST"])
@login_required("admin")
def admin_user_suspend(uid):
    u = db.get_or_404(User, uid)
    if not can_manage(g.user, u):
        abort(403)
    u.suspended = not u.suspended
    db.session.commit()
    flash(f"{u.name} {'suspended' if u.suspended else 'restored'}.", "ok")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/superadmin")
@login_required("superadmin")
def superadmin():
    by_role = {r: User.query.filter_by(role=r).count() for r in ROLES}
    return render_template(
        "superadmin.html", by_role=by_role, roles=ROLES,
        staff=User.query.filter(User.role.in_(STAFF_ROLES)).order_by(User.id).all(),
        recent=User.query.order_by(User.id.desc()).limit(8).all(),
        suspended=User.query.filter_by(suspended=True).count(),
        pending=Provider.query.filter_by(approved=False).count(),
        bookings=Booking.query.count(), orders=Order.query.count(), products=Product.query.count())


@app.route("/superadmin/user/<int:uid>/role", methods=["POST"])
@login_required("superadmin")
def superadmin_user_role(uid):
    u = db.get_or_404(User, uid)
    role = request.form.get("role")
    if role not in ROLES:
        abort(400)
    if not can_manage(g.user, u):
        flash("You can't change your own role. Ask another super admin.", "error")
        return redirect(request.referrer or url_for("admin_users"))
    if u.provider and role == "customer":
        u.provider.approved = False  # a plain user can't keep a public artist page
    u.role = role
    notify(u.id, f"Your account type is now {ROLES[role]}.")
    db.session.commit()
    flash(f"{u.name} is now {ROLES[role]}.", "ok")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/superadmin/staff", methods=["POST"])
@login_required("superadmin")
def superadmin_staff():
    f = request.form
    email = f.get("email", "").strip().lower()
    if f.get("role") not in STAFF_ROLES or not f.get("name") or not email:
        abort(400)
    if User.query.filter_by(email=email).first():
        flash("That email already has an account. Change its role from the Users page.", "error")
    elif len(f.get("password", "")) < 8:
        flash("Use a password of at least 8 characters.", "error")
    else:
        db.session.add(User(name=f["name"], email=email, role=f["role"],
                            password_hash=generate_password_hash(f["password"])))
        db.session.commit()
        flash(f"{ROLES[f['role']]} account created for {email}.", "ok")
    return redirect(url_for("superadmin"))


# ---------------------------------------------------------------- seed
def seed():
    if User.query.first():
        return
    admin_pw = os.environ.get("ADMIN_PASSWORD", "admin12345")
    db.session.add(User(name="M MUSICS Admin", email="admin@mmusics.local",
                        password_hash=generate_password_hash(admin_pw), role="admin"))
    demo = [
        ("musicians", "Grace Nakato", "Piano", "Gospel, Jazz", "Kampala", 150000, 9, "Church and wedding pianist."),
        ("musicians", "Joel Okello", "Drum kit", "Afrobeat, Rock", "Entebbe", 120000, 6, "Live-band drummer."),
        ("composers", "Samuel Ssemakula", "Film scoring", "Orchestral", "Kampala", 400000, 12, "Scores for film and ads."),
        ("producers", "Beat Lab UG", "Mixing and mastering", "Afropop, Dancehall", "Kampala", 250000, 8, "Studio in Ntinda."),
        ("trainers", "Ruth Atim", "Vocal training", "Gospel, Classical", "Online", 60000, 10, "Voice coach for all levels."),
    ]
    for i, (cat, name, spec, gen, loc, rate, exp, bio) in enumerate(demo):
        u = User(name=name, email=f"demo{i}@mmusics.local", role="provider",
                 password_hash=generate_password_hash(os.urandom(8).hex()))
        db.session.add(u)
        db.session.flush()
        db.session.add(Provider(user_id=u.id, category=cat, display_name=name,
                                specialisation=spec, genres=gen, location=loc, rate=rate,
                                experience_years=exp, bio=bio, approved=True,
                                verified=i % 2 == 0, featured=i < 2,
                                instrument_family={"Piano": "Keyboard and piano", "Drum kit": "Percussion"}.get(spec),
                                availability="Weekends and evenings"))
    for n, c, b, pr, st in [
        ("61-key Digital Keyboard", "Keyboards", "Yamaha", 950000, 8),
        ("Acoustic Guitar Dreadnought", "Guitars", "Fender", 780000, 5),
        ("5-piece Drum Kit", "Drums", "Pearl", 2400000, 2),
        ("USB Studio Microphone", "Sound equipment", "Audio-Technica", 520000, 10),
        ("Guitar Strings (set)", "Accessories", "D'Addario", 45000, 40),
    ]:
        db.session.add(Product(name=n, category=c, brand=b, price=pr, stock=st,
                               description=f"{n} from {b}.", warranty="6 months"))
    db.session.commit()


def ensure_superadmin():
    """Every install needs at least one super admin; create or promote one if missing."""
    if User.query.filter_by(role="superadmin").first():
        return
    email = os.environ.get("SUPERADMIN_EMAIL", "developer@mmusics.local").lower()
    pw = os.environ.get("SUPERADMIN_PASSWORD", "super12345")
    u = User.query.filter_by(email=email).first()
    if u:
        u.role = "superadmin"
    else:
        db.session.add(User(name="Site Developer", email=email, role="superadmin",
                            password_hash=generate_password_hash(pw)))
    db.session.commit()


def ensure_columns():
    """Tiny migration: add columns introduced after an existing DB was created."""
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    q = db.engine.dialect.identifier_preparer.quote
    for model in (User, Provider, Product, Booking, Payment):
        have = {c["name"] for c in insp.get_columns(model.__tablename__)}
        for col in model.__table__.columns:
            if col.name not in have:
                db.session.execute(text(f"ALTER TABLE {q(model.__tablename__)} ADD COLUMN "
                                        f"{q(col.name)} {col.type.compile(db.engine.dialect)}"))
    db.session.commit()


def init_db():
    """Create tables and seed demo data. Safe to call on every cold start.

    On Vercel the filesystem under /tmp is ephemeral and per-instance, so the
    SQLite file (when DATABASE_URL is unset) is rebuilt on each cold start.
    In production, set DATABASE_URL to a managed Postgres so data persists.
    Wrapped so a read-only or unavailable DB never crashes the function import.
    """
    try:
        db.create_all()
        ensure_columns()
        seed()
        ensure_superadmin()
    except Exception as exc:  # noqa: BLE001 - keep the function importable
        # On Vercel a failed write should not break serving; log and continue.
        app.logger.warning("init_db skipped: %s", exc)


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
