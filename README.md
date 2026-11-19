# M MUSICS
Music services marketplace built with Flask.

## Run
    pip install -r requirements.txt
    python app.py        # http://127.0.0.1:5000
Demo data is seeded on first run. **Change these passwords before going live.**

| Role | Demo login |
|---|---|
| Super admin (developers, overseers) | `developer@mmusics.local` / `super12345` |
| Admin (site owner) | `admin@mmusics.local` / `admin12345` |

## User roles
| Role | Who | What they can do |
|---|---|---|
| **Super admin** | Developers and site overseers | Everything an admin can, plus change any user's role, create admin/super-admin accounts, remove staff access, see platform totals (`/superadmin`) |
| **Admin** | Site owner and administrator | Approve/verify/feature artists, manage shop products, orders and reviews, suspend or restore users and artists (`/admin`, `/admin/users`). Cannot touch staff accounts or change roles |
| **Artist** | People offering services | Create a profile (photo, audio, rates), receive and manage booking requests and quotes. Public after admin approval |
| **User** | Customers | Browse, book artists, message, pay, review, shop and order |

Rules enforced on the server: nobody can change their own role or suspend themselves, admins cannot suspend or modify staff, demoting an artist to user unpublishes their page, and suspended accounts are signed out immediately and cannot log in. People choose *User* or *Artist* when registering, and users can become artists later via "Offer your services".

## Settings (environment variables)
- `SECRET_KEY` (required in production), `ADMIN_PASSWORD` (before first run)
- `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD`: the first super admin, created automatically if none exists (existing databases are upgraded in place)
- `PAYMENT_MODE`: `demo` (default, payments always succeed) or `live` (implement `charge()` in app.py for MTN MoMo / Airtel / card)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`: enable email notifications
- `DATABASE_URL`: e.g. a PostgreSQL URL for production

## Features
Directories, profiles with photo and audio upload, bookings with quotes, messaging and payment,
reviews, shop with images, cart, orders and payment, notifications (site and email), CSRF protection,
login rate limiting, admin dashboard.

## Not yet built
Courses and student portal, instrument rental, password reset, payment gateway credentials,
cloud file storage (uploads go to `instance/uploads`), and published legal policies.

## Test
    python tests/smoke_test.py   # runs the full booking, payment, shop and upload flow on a temp database
