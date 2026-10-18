import os, sqlite3, urllib.parse, json, re, datetime
from flask import Response, Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "frescu.db")
UP = os.path.join(BASE, "static", "uploads")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esto")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
WA = os.environ.get("WHATSAPP", "573016747447")
CATS = ["Aseo", "Cremas", "Productos de Belleza", "Productos de otras marcas"]
EXT = {"png", "jpg", "jpeg", "webp"}

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(_):
    d = g.pop("db", None)
    if d: d.close()

def init():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT, is_admin INT DEFAULT 0);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT, category TEXT, price INT, stock INT, description TEXT, images TEXT);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, user_id INT, items TEXT, total INT, name TEXT, address TEXT, phone TEXT, receipt TEXT, status TEXT DEFAULT 'Pendiente');
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS announcements(id INTEGER PRIMARY KEY, title TEXT, body TEXT, image TEXT, fuente TEXT, tamano INT, color TEXT, alineacion TEXT, created TEXT);
    CREATE TABLE IF NOT EXISTS likes(ann_id INT, user_id INT, UNIQUE(ann_id,user_id));
    CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, ann_id INT, username TEXT, text TEXT);
    """)
    if "etiqueta" not in [r[1] for r in c.execute("PRAGMA table_info(products)")]:
        c.execute("ALTER TABLE products ADD COLUMN etiqueta TEXT DEFAULT ''")
    if not c.execute("SELECT 1 FROM users WHERE is_admin=1").fetchone():
        u, p = os.environ.get("ADMIN_USER", "admin"), os.environ.get("ADMIN_PASS")
        if not p: raise SystemExit("Define ADMIN_PASS en las variables de entorno (.env).")
        c.execute("INSERT INTO users(username,pw,is_admin) VALUES(?,?,1)", (u, generate_password_hash(p)))
    if not c.execute("SELECT 1 FROM products").fetchone():
        seed = [("Crema para manos 250 ml", "Cremas", 15000, 10, "Nutrición intensa y alivio inmediato. Con aguacate, vitamina E, manzanilla y caléndula.", "crema250.png"),
                ("Crema para manos 125 ml", "Cremas", 10000, 10, "Crema de manos reparadora con aguacate, vitamina E, manzanilla y caléndula.", "crema125.png"),
                ("Ambientador de Carro Nuevo", "Aseo", 10000, 4, "Spray ambientador de larga duración, aroma a carro nuevo.", "carro.png"),
                ("Ambientador de Maracuyá", "Aseo", 10000, 2, "Spray ambientador de larga duración, aroma a maracuyá.", "maracuya.png")]
        c.executemany("INSERT INTO products(name,category,price,stock,description,images) VALUES(?,?,?,?,?,?)", seed)
    c.commit(); c.close()

def admin_only(f):
    from functools import wraps
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"): return redirect(url_for("admin_login"))
        return f(*a, **k)
    return w

def save_files(files):
    names = []
    for f in [x for x in files if x and x.filename][:5]:
        ext = f.filename.rsplit(".", 1)[-1].lower()
        if ext in EXT:
            n = os.urandom(6).hex() + "_" + secure_filename(f.filename); f.save(os.path.join(UP, n)); names.append(n)
    return names

def cart_items():
    items, total = [], 0
    for pid, q in session.get("cart", {}).items():
        p = db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if p:
            items.append((p, q)); total += p["price"] * q
    return items, total

@app.template_filter("cop")
def cop(v): return "${:,.0f}".format(v).replace(",", ".")

@app.route("/")
def index():
    cat = request.args.get("cat")
    q = "SELECT * FROM products" + (" WHERE category=?" if cat else "")
    prods = db().execute(q, (cat,) if cat else ()).fetchall()
    return render_template("index.html", prods=prods, cats=CATS, cat=cat)

@app.route("/producto/<int:pid>")
def producto(pid):
    p = db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone_or_404() if False else db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    return render_template("producto.html", p=p) if p else ("No existe", 404)

# ---- clientes ----
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE username=? AND is_admin=0", (request.form["username"],)).fetchone()
        if u and check_password_hash(u["pw"], request.form["password"]):
            session["uid"] = u["id"]; session["user"] = u["username"]; return redirect(url_for("index"))
        flash("Usuario o contraseña incorrectos")
    return render_template("login.html", admin=False)

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        try:
            db().execute("INSERT INTO users(username,pw) VALUES(?,?)", (request.form["username"].strip(), generate_password_hash(request.form["password"])))
            db().commit(); flash("Bienvenido, muchas gracias por ingresar a nuestro portal. Si quieres responder una pequeña encuesta, selecciona 'Responder encuesta'.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Ese usuario ya existe")
    return render_template("registro.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("index"))

# ---- carrito ----
@app.route("/carrito/agregar/<int:pid>", methods=["POST"])
def agregar(pid):
    c = session.get("cart", {}); c[str(pid)] = c.get(str(pid), 0) + max(1, int(request.form.get("qty", 1)))
    session["cart"] = c; return redirect(request.referrer or url_for("index"))

@app.route("/carrito/quitar/<int:pid>")
def quitar(pid):
    c = session.get("cart", {}); c.pop(str(pid), None); session["cart"] = c; return redirect(url_for("carrito"))

@app.route("/carrito")
def carrito():
    items, total = cart_items()
    msg = "Quiero comprar los siguientes productos:\n" + "\n".join(f"- {p['name']} x{q} = {cop(p['price']*q)}" for p, q in items) + f"\nTotal: {cop(total)}"
    return render_template("carrito.html", items=items, total=total, wa=f"https://wa.me/{WA}?text=" + urllib.parse.quote(msg))

@app.route("/delivery", methods=["GET", "POST"])
def delivery():
    items, total = cart_items()
    if request.method == "POST":
        if not session.get("uid"): flash("Inicia sesión para pedir delivery"); return redirect(url_for("login"))
        rec = save_files([request.files.get("receipt")])
        desc = "; ".join(f"{p['name']} x{q}" for p, q in items)
        db().execute("INSERT INTO orders(user_id,items,total,name,address,phone,receipt) VALUES(?,?,?,?,?,?,?)",
                     (session["uid"], desc, total, request.form["name"], request.form["address"], request.form["phone"], rec[0] if rec else None))
        db().commit(); session["cart"] = {}; flash("Pedido enviado. Verás 'Aprobado' cuando se confirme tu pago."); return redirect(url_for("perfil"))
    return render_template("delivery.html", total=total)

@app.route("/perfil")
def perfil():
    if not session.get("uid"): return redirect(url_for("login"))
    o = db().execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall()
    return render_template("perfil.html", orders=o)

# ---- administrador ----
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE username=? AND is_admin=1", (request.form["username"],)).fetchone()
        if u and check_password_hash(u["pw"], request.form["password"]):
            session["admin"] = True; return redirect(url_for("admin"))
        flash("Credenciales incorrectas")
    return render_template("login.html", admin=True)

@app.route("/admin")
@admin_only
def admin():
    return render_template("admin.html", prods=db().execute("SELECT * FROM products").fetchall(),
                           orders=db().execute("SELECT * FROM orders ORDER BY id DESC").fetchall(), cats=CATS)

@app.route("/admin/producto", methods=["POST"])
@admin_only
def admin_producto():
    f = request.form; imgs = ",".join(save_files(request.files.getlist("images")))
    if f.get("id"):
        db().execute("UPDATE products SET name=?,category=?,price=?,stock=?,description=? WHERE id=?",
                     (f["name"], f["category"], f["price"], f["stock"], f["description"], f["id"]))
        if imgs: db().execute("UPDATE products SET images=? WHERE id=?", (imgs, f["id"]))
    else:
        db().execute("INSERT INTO products(name,category,price,stock,description,images) VALUES(?,?,?,?,?,?)",
                     (f["name"], f["category"], f["price"], f["stock"], f["description"], imgs))
    pid = f.get("id") or db().execute("SELECT MAX(id) FROM products").fetchone()[0]
    db().execute("UPDATE products SET etiqueta=? WHERE id=?", (f.get("etiqueta", "").strip()[:30], pid))
    db().commit(); return redirect(url_for("admin"))

@app.route("/admin/aprobar/<int:oid>")
@admin_only
def aprobar(oid):
    db().execute("UPDATE orders SET status='Aprobado' WHERE id=?", (oid,)); db().commit(); return redirect(url_for("admin"))

@app.route("/admin/clave", methods=["POST"])
@admin_only
def clave():
    db().execute("UPDATE users SET pw=? WHERE is_admin=1", (generate_password_hash(request.form["new"]),)); db().commit()
    flash("Contraseña actualizada"); return redirect(url_for("admin"))

# ---------- TEMAS EDITABLES ----------
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
COLS = [("bg","Fondo general"),("fg","Texto general"),("titulo","Títulos"),("enlace","Enlaces"),("header_bg","Fondo del encabezado"),
        ("header_fg","Texto del encabezado"),("card","Fondo de tarjetas"),("card_fg","Texto de tarjetas"),("borde","Bordes"),
        ("btn","Botones"),("btn_fg","Texto de botones"),("precio","Precios"),("input_bg","Fondo de campos"),("input_fg","Texto de campos"),
        ("flash_bg","Fondo de avisos"),("flash_fg","Texto de avisos"),("login_c","Botón Inicio de Sesión"),("login_a","Botón Admin"),
        ("glow","Brillo neón"),("sombra","Sombras")]
NOMBRES = [("normal","Normal"),("arcade","Arcade"),("navidad","Navidad"),("neon","Neón")]
FUENTES = {"sans":"system-ui,sans-serif","serif":"Georgia,serif","mono":"'Courier New',monospace"}
_P = {"normal":"f4faf7 111111 111111 0f8f80 f4faf7 111111 ffffff 111111 000000 000000 ffffff 111111 ffffff 111111 fff3c4 333333 1e6fe0 8fdc9a 14b8a6 000000 0 sans",
      "arcade":"1a0033 ffe600 ff3df2 00e5ff 2b0a55 ffe600 2b0a55 ffe600 ff3df2 ff3df2 ffffff 00ff88 12002a ffe600 ffe600 1a0033 1e6fe0 8fdc9a ff3df2 000000 0 mono",
      "navidad":"fff5f5 12532d c1121f c1121f 12532d ffffff ffffff 12532d c1121f c1121f ffffff 12532d ffffff 12532d ffe8a3 333333 1e6fe0 8fdc9a ffd60a 000000 0 serif",
      "neon":"0a0a0f e8fff8 00ffd0 00ffd0 0a0a0f e8fff8 12121c e8fff8 00ffd0 00ffd0 0a0a0f ff2bd6 1a1a28 e8fff8 12121c 00ffd0 1e6fe0 8fdc9a 00ffd0 000000 1 sans"}
DEFAULTS = {n: {**{k: "#" + v for (k, _), v in zip(COLS, p.split())}, "neon": p.split()[20], "fuente": p.split()[21]} for n, p in _P.items()}

def get_setting(k, d=None):
    r = db().execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r[0] if r else d

def set_setting(k, v):
    db().execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v)); db().commit()

def get_theme(n):
    t = dict(DEFAULTS[n])
    try: t.update(json.loads(get_setting("tema_" + n, "{}")))
    except ValueError: pass
    return t

@app.context_processor
def inject():
    return {"tema_default": get_setting("tema_default", "normal")}

@app.route("/tema.css")
def tema_css():
    out = []
    for n in DEFAULTS:
        t = get_theme(n); s = f"body[data-tema={n}]"
        out.append(s + "{" + ";".join(f"--{k}:{t[k]}" for k, _ in COLS) + f";font-family:{FUENTES.get(t['fuente'], FUENTES['sans'])}" + "}")
        if t["neon"] == "1":
            out.append(f"{s} button,{s} .btn,{s} .card,{s} .box{{box-shadow:0 0 10px var(--glow),0 0 22px var(--glow)}}{s} h2,{s} h3{{text-shadow:0 0 8px var(--glow)}}")
    r = Response("\n".join(out), mimetype="text/css"); r.headers["Cache-Control"] = "no-cache"; return r

@app.route("/admin/tema", methods=["GET", "POST"])
@admin_only
def admin_tema():
    n = request.values.get("tema", "normal"); n = n if n in DEFAULTS else "normal"
    if request.method == "POST":
        if request.form.get("accion") == "reset":
            set_setting("tema_" + n, "{}")
        else:
            v = {k: request.form[k] for k, _ in COLS if HEX.match(request.form.get(k, ""))}
            v["neon"] = "1" if request.form.get("neon") else "0"
            v["fuente"] = request.form.get("fuente") if request.form.get("fuente") in FUENTES else "sans"
            set_setting("tema_" + n, json.dumps(v))
        if request.form.get("default"): set_setting("tema_default", n)
        flash("Tema actualizado"); return redirect(url_for("admin_tema", tema=n))
    return render_template("admin_tema.html", tema=n, t=get_theme(n), cols=COLS, nombres=NOMBRES, fuentes=FUENTES, default=get_setting("tema_default", "normal"))

# ---------- ANUNCIOS ----------
FONTS = {"Normal":"system-ui,sans-serif","Elegante":"Georgia,serif","Máquina":"'Courier New',monospace","Manuscrita":"'Segoe Script','Comic Sans MS',cursive","Impacto":"Impact,sans-serif"}

@app.template_filter("fs")
def fs(n): return FONTS.get(n, FONTS["Normal"])

@app.route("/anuncios")
def anuncios():
    d = db(); uid = session.get("uid"); out = []
    for a in d.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall():
        a = dict(a)
        a["likes"] = d.execute("SELECT COUNT(*) FROM likes WHERE ann_id=?", (a["id"],)).fetchone()[0]
        a["coms"] = d.execute("SELECT * FROM comments WHERE ann_id=? ORDER BY id", (a["id"],)).fetchall()
        out.append(a)
    mis = {r[0] for r in d.execute("SELECT ann_id FROM likes WHERE user_id=?", (uid,))} if uid else set()
    return render_template("anuncios.html", anuncios=out, mis=mis)

@app.route("/anuncios/<int:aid>/like", methods=["POST"])
def like(aid):
    if not session.get("uid"):
        flash("Inicia sesión para dar corazón"); return redirect(url_for("login"))
    d = db()
    if d.execute("DELETE FROM likes WHERE ann_id=? AND user_id=?", (aid, session["uid"])).rowcount == 0:
        d.execute("INSERT INTO likes(ann_id,user_id) VALUES(?,?)", (aid, session["uid"]))
    d.commit(); return redirect(url_for("anuncios") + f"#a{aid}")

@app.route("/anuncios/<int:aid>/comentar", methods=["POST"])
def comentar(aid):
    who = "Frescú Aroma" if session.get("admin") else session.get("user")
    if not who:
        flash("Inicia sesión para comentar"); return redirect(url_for("login"))
    t = request.form.get("text", "").strip()[:500]
    if t:
        db().execute("INSERT INTO comments(ann_id,username,text) VALUES(?,?,?)", (aid, who, t)); db().commit()
    return redirect(url_for("anuncios") + f"#a{aid}")

@app.route("/admin/anuncios", methods=["GET", "POST"])
@admin_only
def admin_anuncios():
    d = db()
    if request.method == "POST":
        f = request.form
        fuente = f.get("fuente") if f.get("fuente") in FONTS else "Normal"
        color = f.get("color") if HEX.match(f.get("color", "")) else "#1d3b2a"
        al = f.get("alineacion") if f.get("alineacion") in ("left", "center", "right") else "left"
        tam = min(48, max(12, int(f.get("tamano") or 16)))
        img = save_files([request.files.get("image")])
        if f.get("id"):
            d.execute("UPDATE announcements SET title=?,body=?,fuente=?,tamano=?,color=?,alineacion=? WHERE id=?", (f["title"], f["body"], fuente, tam, color, al, f["id"]))
            if img: d.execute("UPDATE announcements SET image=? WHERE id=?", (img[0], f["id"]))
        else:
            d.execute("INSERT INTO announcements(title,body,image,fuente,tamano,color,alineacion,created) VALUES(?,?,?,?,?,?,?,?)",
                      (f["title"], f["body"], img[0] if img else None, fuente, tam, color, al, datetime.date.today().strftime("%d/%m/%Y")))
        d.commit(); return redirect(url_for("admin_anuncios"))
    e = request.args.get("edit")
    edit = d.execute("SELECT * FROM announcements WHERE id=?", (e,)).fetchone() if e else None
    return render_template("admin_anuncios.html", edit=edit, lista=d.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall(), fonts=FONTS)

@app.route("/admin/anuncio/<int:aid>/borrar")
@admin_only
def borrar_anuncio(aid):
    d = db()
    for t in ("likes", "comments"): d.execute(f"DELETE FROM {t} WHERE ann_id=?", (aid,))
    d.execute("DELETE FROM announcements WHERE id=?", (aid,)); d.commit(); return redirect(url_for("admin_anuncios"))

@app.route("/admin/comentario/<int:cid>/borrar")
@admin_only
def borrar_comentario(cid):
    db().execute("DELETE FROM comments WHERE id=?", (cid,)); db().commit(); return redirect(url_for("anuncios"))

init()
if __name__ == "__main__":
    app.run(debug=False)
