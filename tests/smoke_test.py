import os, io, re
os.environ["DATABASE_URL"] = "sqlite:////tmp/smoke.db"
if os.path.exists("/tmp/smoke.db"): os.remove("/tmp/smoke.db")
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, db, Provider, Booking, Order, Product, User
def client():
    c = app.test_client(); c.get("/"); return c
def post(c, url, data=None, **kw):
    with c.session_transaction() as s: tok = s["csrf"]
    d = dict(data or {}); d["csrf"] = tok
    return c.post(url, data=d, follow_redirects=True, **kw)
def ok(label, cond): print(("PASS " if cond else "FAIL ") + label); 
cust, prov, adm = client(), client(), client()
for u in ["/", "/services", "/hire/musicians", "/hire/trainers", "/shop", "/search?q=piano", "/product/1", "/login", "/register"]:
    ok("GET "+u, client().get(u).status_code == 200)
ok("POST without csrf blocked", client().post("/login", data={"email":"a","password":"b"}).status_code == 400)
post(cust, "/register", {"name":"Cathy Customer","email":"c@x.com","password":"password1","phone":"0770000000"})
post(prov, "/register", {"name":"Paul Provider","email":"p@x.com","password":"password1"})
png = (io.BytesIO(b"\x89PNG\r\n\x1a\n"+b"0"*20), "me.png")
r = post(prov, "/become-provider", {"category":"musicians","display_name":"Paul P","specialisation":"Violin","instrument_family":"Strings","rate":"100000","photo":png,"audio":(io.BytesIO(b"x"),"s.mp3")}, content_type="multipart/form-data")
ok("provider profile saved", b"awaiting" in r.data.lower() or b"Awaiting" in r.data)
bad = post(prov, "/become-provider", {"category":"musicians","instrument_family":"Strings","display_name":"Paul P","specialisation":"Violin","photo":(io.BytesIO(b"<script>"),"x.html")}, content_type="multipart/form-data")
ok("html upload rejected", b"Unsupported" in bad.data)
with app.app_context(): pid = Provider.query.filter_by(display_name="Paul P").first().id
ok("unapproved hidden", client().get(f"/provider/{pid}").status_code == 404)
post(adm, "/login", {"email":"admin@mmusics.local","password":"admin12345"})
post(adm, f"/admin/provider/{pid}/approve")
r = client().get(f"/provider/{pid}"); ok("approved visible + audio", r.status_code == 200 and b"<audio" in r.data)
ok("photo served", client().get(re.search(rb'/media/[\w.]+\.png', r.data).group().decode()).status_code == 200)
post(cust, f"/provider/{pid}/book", {"event_type":"Wedding","date":"2027-01-10","budget":"300000"})
with app.app_context(): bid = Booking.query.first().id
ok("pay before quote refused", b"once the provider" in post(cust, f"/pay/booking/{bid}").data)
post(prov, f"/booking/{bid}/quote", {"quote":"250000"})
post(prov, f"/booking/{bid}/accept"); post(cust, f"/booking/{bid}/confirm")
post(cust, f"/booking/{bid}/message", {"text":"Hello!"})
ok("message visible", b"Hello!" in prov.get(f"/booking/{bid}").data)
r = post(cust, f"/pay/booking/{bid}", {"method":"MTN Mobile Money","phone":"0771234567"}); ok("booking paid", b"Payment received" in r.data)
post(prov, f"/booking/{bid}/start"); post(prov, f"/booking/{bid}/complete")
r = post(cust, f"/provider/{pid}/review", {"stars":"5","comment":"Great"}); ok("review posted", b"Review posted" in r.data)
post(cust, "/cart/add/1", {"qty":"2"}); r = post(cust, "/checkout", {"address":"Kampala"}); ok("checkout -> pay page", b"Pay UGX" in r.data)
r = post(cust, "/pay/order/1", {"method":"Airtel Money","phone":"0751234567"}); ok("order paid", b"Payment received" in r.data)
with app.app_context(): ok("order status Paid + stock reduced", Order.query.first().status=="Paid" and db.session.get(Product,1).stock==6)
ok("other user can't pay my order", post(prov, "/pay/order/1").status_code == 403)
post(adm, "/admin/product", {"name":"Test Horn","price":"1000","stock":"3","image":(io.BytesIO(b"\x89PNG"+b"0"*9),"h.png")}, content_type="multipart/form-data")
ok("admin + dashboards", all(x.get(u).status_code==200 for x,u in [(adm,"/admin"),(cust,"/dashboard"),(prov,"/dashboard")]))
ok("logout needs POST", client().get("/logout").status_code == 405)

# ---------------------------------------------------------------- four roles
print("--- roles ---")
sup, art = client(), client()
post(sup, "/login", {"email": "developer@mmusics.local", "password": "super12345"})
ok("super admin dashboard redirects to /superadmin", b"Super admin" in sup.get("/dashboard", follow_redirects=True).data)
ok("super admin can open admin area too", sup.get("/admin").status_code == 200)
ok("admin can open /admin/users", adm.get("/admin/users").status_code == 200)
ok("admin blocked from /superadmin", adm.get("/superadmin").status_code == 403)
ok("customer blocked from /admin", cust.get("/admin").status_code == 403)
ok("customer blocked from /superadmin", cust.get("/superadmin").status_code == 403)
ok("artist blocked from /admin/users", prov.get("/admin/users").status_code == 403)
ok("anonymous redirected to login", client().get("/superadmin").status_code == 302)

# artist sign-up path goes straight to the artist profile form
r = post(art, "/register", {"name": "Amy Artist", "email": "amy@x.com", "password": "password1", "account_type": "artist"})
ok("artist registration -> profile form", b"artist profile" in r.data.lower() or b"specialisation" in r.data.lower())

with app.app_context():
    ids = {u.email: u.id for u in User.query.all()}
    dev_id, admin_id, cust_id = ids["developer@mmusics.local"], ids["admin@mmusics.local"], ids["c@x.com"]

# admin may suspend users, but not staff, and cannot change roles
ok("admin cannot suspend super admin", post(adm, f"/admin/user/{dev_id}/suspend").status_code == 403)
ok("admin cannot suspend another admin/self", post(adm, f"/admin/user/{admin_id}/suspend").status_code == 403)
ok("admin cannot change roles", post(adm, f"/superadmin/user/{cust_id}/role", {"role": "admin"}).status_code == 403)
victim = client(); post(victim, "/register", {"name": "Vic", "email": "vic@x.com", "password": "password1"})
with app.app_context(): vic_id = User.query.filter_by(email="vic@x.com").first().id
post(adm, f"/admin/user/{vic_id}/suspend")
ok("suspended user is signed out", victim.get("/dashboard").status_code == 302)
ok("suspended user cannot log back in", b"suspended" in post(client(), "/login", {"email": "vic@x.com", "password": "password1"}).data.lower())
post(adm, f"/admin/user/{vic_id}/suspend")
ok("restored user can log in", b"Hello, Vic" in post(client(), "/login", {"email": "vic@x.com", "password": "password1"}).data)

# super admin powers
post(sup, f"/superadmin/user/{vic_id}/role", {"role": "admin"})
with app.app_context(): ok("super admin promotes user to admin", db.session.get(User, vic_id).role == "admin")
ok("new admin reaches /admin", (lambda c: (post(c, "/login", {"email": "vic@x.com", "password": "password1"}), c.get("/admin").status_code)[1])(client()) == 200)
ok("super admin can't change own role", b"own role" in post(sup, f"/superadmin/user/{dev_id}/role", {"role": "customer"}).data)
post(sup, "/superadmin/staff", {"name": "New Admin", "email": "na@x.com", "password": "password1", "role": "admin"})
with app.app_context(): ok("super admin creates staff account", User.query.filter_by(email="na@x.com", role="admin").count() == 1)
ok("invalid role rejected", post(sup, f"/superadmin/user/{vic_id}/role", {"role": "god"}).status_code == 400)
post(sup, f"/superadmin/user/{pid and ids['p@x.com']}/role", {"role": "customer"})
ok("demoting an artist unpublishes their page", client().get(f"/provider/{pid}").status_code == 404)
ok("users page filters by role", b"Paul Provider" not in sup.get("/admin/users?role=admin").data)
