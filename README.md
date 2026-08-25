# Mombasa County ICT Help Desk

A Django-based IT help desk ticketing system built for Mombasa County government
offices, with role-based access control and a background automation engine that
handles ticket prioritization, assignment, escalation, and closure without human
intervention.

## Features

### Ticketing
- Requesters submit tickets with a category, department, location, contact
  phone, and an optional image attachment.
- Full lifecycle tracking: Open → In Progress → Resolved → Closed.
- Per-ticket audit trail — every automated or manual action is logged.

### Role-Based Access Control (RBAC)
Three roles, enforced via Django Groups (`Requesters`, `ICT Agents`,
`Administrators`) and centralized decorators in `tickets/decorators.py`:

| Role | Can do |
|---|---|
| **Requester** | Submit tickets, view their own tickets and notifications |
| **ICT Agent** | View/act on assigned + unassigned tickets, update status |
| **Administrator** | Everything an agent can, plus the reporting dashboard, CSV export, ticket reassignment, and appointing/managing users |

Admins appoint Requesters as Agents or Administrators — and assign each agent a
**specialty** (Network, Hardware, Software, Account/Access, Printer, Other) —
from the in-app **Manage Users** page. Self-service registration is
intentionally Requester-only; role escalation is never user-selectable.

### Automation Engine
A background thread (`tickets/automation.py`) starts automatically when Django
launches and runs a check cycle every 10 minutes — no cron or Task Scheduler
required. The same logic is also exposed as standalone management commands.

On **ticket creation** (`tickets/signals.py`):
1. **Auto-priority** — derived from the category's configured default priority,
   not left to the requester.
2. **Auto-assignment** — routed to the least-loaded ICT Agent; if any agent has
   a matching **specialty** for the ticket's category, specialists are tried
   first before falling back to the least-loaded agent overall.
3. **Auto-status** — set to `in_progress` immediately once assigned.
4. Notifications (in-app + email) sent to the assigned agent, all
   Administrators, and the requester.

On a **10-minute cycle** (`tickets/automation.py`):
1. **SLA warning** — a one-time warning once a ticket passes 80% of its
   priority's SLA window.
2. **Auto-escalation (Level 1)** — SLA-breached tickets are reassigned to an
   Administrator automatically.
3. **Auto-escalation (Level 2)** — tickets still open at 2x their SLA window
   trigger an urgent email to every Administrator.
4. **Auto-closure** — resolved tickets untouched for 48 hours are closed
   automatically.

Every automated action writes an `AuditLog` entry, and aggregate automation
stats (auto-assigned count, escalation counts, auto-closed count, agent
performance, category/location breakdowns) are visible on the Administrator
dashboard.

### Reporting Dashboard (Administrators)
- Total / overdue ticket counts, average resolution time.
- Charts (Chart.js): overdue tickets by category, requests by location, agent
  workload vs. resolution performance.
- Automation activity summary and a live audit log feed.
- Full CSV export of all tickets.

## Tech Stack

- **Backend**: Django 6
- **Database**: PostgreSQL
- **Frontend**: Django templates, vanilla CSS (no build step), Chart.js
- **Email**: SMTP (Gmail) for real notification delivery
- **Auth**: Django's built-in auth + Groups for RBAC

## Project Structure

```
helpdesk/                  # Django project settings
tickets/
    automation.py           # Background automation engine (SLA/escalation/closure)
    signals.py               # Auto-priority + auto-assignment on ticket creation
    decorators.py            # RBAC decorators (role_required, admin_required, ...)
    audit.py                  # AuditLog helper
    emails.py                 # Email notification senders
    models.py                  # Category, Priority, Department, Location, Profile, Ticket, AuditLog, Notification
    views.py                    # All view logic
    context_processors.py       # Injects unread notification count + role info into every template
    management/commands/
        seed_tickets.py           # Seeds demo categories, users, and tickets
        promote_admin.py           # CLI: add a user to the Administrators group
        auto_escalate.py            # CLI equivalent of the escalation checks
        auto_close.py                # CLI equivalent of the auto-closure check
    templates/tickets/            # All page templates (shared base.html layout)
    static/tickets/                # Logo, Chart.js bundle
```

## Setup

### Prerequisites
- Python 3.11+
- PostgreSQL running locally (or update `DATABASES` in `helpdesk/settings.py`)

### 1. Get the code and create a virtual environment
Either clone it:
```bash
git clone https://github.com/IanOtollo/helpdesk-ticketing-system.git
cd helpdesk-ticketing-system
```
...or download it as a ZIP from the green **Code** button on GitHub and
extract it, then open a terminal in the extracted folder.

Then set up the environment (the `venv/` folder is intentionally not part of
the repo — everyone creates their own):
```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure environment variables
Create a `.env` file in the project root:
```env
DB_PASSWORD=your_postgres_password
EMAIL_HOST_USER=your_gmail_address
EMAIL_HOST_PASSWORD=your_gmail_app_password

# Optional — only needed if your local Postgres setup differs from the
# defaults (database "helpdesk_db", user "postgres", localhost:5432)
# DB_NAME=helpdesk_db
# DB_USER=postgres
# DB_HOST=localhost
# DB_PORT=5432
```
`EMAIL_HOST_PASSWORD` must be a
[Gmail App Password](https://myaccount.google.com/apppasswords), not your
regular account password.

### 3. Create the database
```bash
createdb helpdesk_db
```
(or `createdb <your DB_NAME>` if you overrode it above — match whatever
Postgres user/database you actually have locally)

### 4. Run migrations and create a superuser
```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py promote_admin <your_username>
```

### 5. (Optional) Seed demo data
```bash
python manage.py seed_tickets
```
This creates demo categories, departments, locations, three requesters, two
ICT agents (all with password `demo12345`), and 25 sample tickets covering
every status.

### 6. Run the server
```bash
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` — Administrators land on the reporting
dashboard by default, everyone else on their ticket list.

## Management Commands

| Command | Purpose |
|---|---|
| `seed_tickets` | Populate demo categories, users, and tickets |
| `promote_admin <username>` | Add an existing user to the Administrators group |
| `auto_escalate` | Manually run the SLA-warning + escalation checks (also runs automatically every 10 min) |
| `auto_close` | Manually run the auto-closure check (also runs automatically every 10 min) |

## Credits

Built by [Ian Otollo](https://github.com/IanOtollo) and
[Joel Majaliwa](https://github.com/majaliwa-joel) as project partners.

## License

This project was built as a final-year academic project for Mombasa County's
ICT help desk workflow.
