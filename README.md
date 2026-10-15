# EAP Backend — Employee Approval Platform

A REST API where employees submit requests (a laptop, software access, a training budget),
an approver approves or rejects them, and every step is recorded in an audit trail
that an admin can filter, report on and export.

Built by a team of developers over six two-week sprints, from an OpenAPI contract,
and deployed with CI/CD to a Linux server behind Nginx.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-361%20passing-brightgreen)

---

## What it does

| Role | Can do |
|---|---|
| **Requester** | Submit a request, follow its status, comment while it is pending, cancel it, mark it completed, export their own history |
| **Approver** | Work through an approval queue with five status tabs, approve or reject with a reason, export their own decisions. Approvers can submit requests too, but can never approve their own |
| **Admin** | Manage users and roles, add or retire request types without a code change, view the request statistics report, search and export the audit log |

Everyone gets in-app notifications when one of their requests changes status.

## Tech stack

| | |
|---|---|
| API | FastAPI, Pydantic v2 |
| Database | PostgreSQL 15, SQLAlchemy 2.0, Alembic (23 migrations) |
| Auth | JWT (python-jose), bcrypt password hashing, role-based access control |
| Security | Login rate limiting (slowapi), deactivated users rejected on every request |
| Testing | pytest, FastAPI TestClient — 361 tests |
| Delivery | Docker, Docker Compose, GitHub Actions |

---

## Architecture

Every request travels through three layers. Routes speak HTTP, services hold the
business rules and never see HTTP, models describe the tables.

```mermaid
flowchart TD
    Client[Frontend / Swagger UI] -->|JSON over HTTP + Bearer token| Routes
    subgraph app
        Routes["api/routes<br/>auth, role check, status codes"]
        Services["services<br/>business rules, transactions, audit"]
        Models["models<br/>SQLAlchemy tables"]
        Schemas["schemas<br/>Pydantic input / output"]
    end
    Routes --> Services
    Routes -.validates with.-> Schemas
    Services --> Models
    Models --> DB[(PostgreSQL)]
```

Keeping the rules in `services/` is what makes them testable without a web server
or a database: the unit tests call the services directly with a mocked session.

```
app/
├── main.py          app factory: routers, CORS, rate-limit handler
├── database.py      engine, session, get_db()
├── core/            config, JWT, password hashing, permission map
├── api/
│   ├── dependencies.py   get_current_user — re-reads the user on every request
│   └── routes/           auth · requests · approver · admin · request_types
│                         reports · audit_log · notifications · rbac
├── models/          users · requests · request_types · comments · notifications · audit_log
├── schemas/         request and response shapes
└── services/        the business logic
alembic/versions/    schema history
scripts/             seed users and request types
tests/unit/          361 tests
```

## Data model

```mermaid
erDiagram
    users ||--o{ requests : submits
    users ||--o{ requests : "is assigned to approve"
    request_types ||--o{ requests : categorises
    requests ||--o{ comments : has
    users ||--o{ comments : writes
    users ||--o{ notifications : receives
    users |o--o{ audit_log : performs

    users {
        int id PK
        string email UK
        string name
        string hashed_password
        enum role "requester | approver | admin"
        bool is_active
    }
    requests {
        int id PK
        string request_number UK "HD-001"
        int user_id FK
        int approver_id FK
        int request_type_id FK
        string title
        enum status
        datetime decision_date
        datetime completion_date
        datetime cancellation_date
    }
    request_types {
        int id PK
        string slug UK "hardware_devices"
        string name UK
        string prefix UK "HD"
        int counter
        bool is_active
    }
    comments {
        int id PK
        int request_id FK
        int author_id FK
        text content
    }
    notifications {
        int id PK
        int user_id FK
        string request_id
        string status
        bool is_read
    }
    audit_log {
        int id PK
        int user_id FK
        string action
        string resource_type
        int resource_id
        string old_status
        string new_status
        datetime timestamp
    }
```

### Request lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending: requester submits
    pending --> approved: approver approves
    pending --> rejected: approver rejects (reason required)
    pending --> cancelled: requester cancels
    approved --> completed: requester marks done
    rejected --> [*]
    cancelled --> [*]
    completed --> [*]
```

Each transition stamps its own date column and writes one `audit_log` row holding
the old and the new status, so the full history of any request can be rebuilt
from the log alone.

---

## Design decisions worth a look

**An audit row can never describe something that didn't happen.**
The audit entry is added in the *same transaction* as the change it records
(`flush()` → add audit row → one `commit()`). If saving the request fails,
its log line is rolled back with it.
→ `services/request_service.py`, `services/user_service.py`

**Notifications are the opposite, on purpose.**
They are sent *after* the commit and never raise. By then the approval is final;
a failed notification must not turn a successful approval into a 500.
→ `notify_status_change()` in `services/notification_service.py`

**Unique request numbers under concurrency.**
`HD-001`, `HD-002`… come from a per-type counter. The counter row is read with
`SELECT … FOR UPDATE`, so two people submitting at the same moment can't get the
same number.
→ `_get_request_type_by_slug()` in `services/request_service.py`

**"Only your own data" is enforced by absence, not by a check.**
The personal export endpoints take the user id from the token and have *no*
parameter that could point at someone else. There is nothing to bypass.
→ `GET /api/requests/export`, `GET /api/approver/requests/export`

**Role changes take effect immediately.**
`get_current_user` reloads the user from the database on every request instead
of trusting the role inside the token, so a demoted or deactivated user loses
access on their very next call — no waiting for the token to expire.
→ `api/dependencies.py`

**Request types are data, not code.**
The seven categories used to be a hard-coded Python dict. They now live in the
`request_types` table, so an admin can add one from the UI and it is usable
seconds later. A deactivated type disappears from the form but old requests keep it.
→ `services/request_type_service.py`

**Correct numbers on the report.**
Approval rate counts only *decided* requests, and a completed request counts as
approved (it was approved before it was completed):
`approval_rate = (approved + completed) / (approved + completed + rejected)`.
→ `services/report_service.py`

**No N+1 queries on exports.**
The requester export used to run one comment query per row and timed out on large
histories. Comments are now loaded in a single `IN (…)` query and grouped in Python.

---

## Run it locally

You need Docker Desktop.

```bash
git clone <this-repo-url> eap-backend
cd eap-backend
cp .env.example .env          # then change SECRET_KEY and the password

docker compose up --build -d
docker compose exec backend alembic upgrade head
docker compose exec backend python -m scripts.seed               # demo users
docker compose exec backend python -m scripts.seed_request_type  # 7 request types
```

Open **http://localhost:8000/docs** for the interactive Swagger UI.

Demo accounts created by the seed script (local use only):

| Role | Email | Password |
|---|---|---|
| Admin | admin@company.com | Admin123! |
| Approver | approver@company.com | Approver123! |
| Requester | requester@company.com | Requester123! |

## Run the tests

The unit tests mock the database, so no Postgres is needed.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# config.py needs these two to exist; the tests never connect.
export DATABASE_URL=postgresql://test:test@localhost:5432/test
export SECRET_KEY=test
python -m pytest tests/unit -q
```

```
361 passed
```

---

## API overview

All endpoints are under `/api`. Full request/response schemas are in Swagger at `/docs`.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login` · `POST /auth/refresh` |
| Requests | `POST /requests` · `GET /requests` · `GET /requests/{id}` · `GET/POST /requests/{id}/comments` · `PATCH /requests/{id}/cancel` · `PATCH /requests/{id}/complete` · `GET /requests/export` |
| Approvals | `GET /approver/requests?status=` · `GET /approver/requests/{id}` · `PATCH …/approve` · `PATCH …/reject` · `GET /approver/requests/export` |
| Request types | `GET /request-types` · `GET/POST /admin/request-types` · `PATCH /admin/request-types/{id}` · `PATCH …/activate` · `PATCH …/deactivate` |
| Users | `GET/POST /admin/users` · `PATCH /admin/users/{id}` · `PATCH …/role` · `PATCH …/activate` · `PATCH …/deactivate` |
| Reports | `GET /reports/requests` · `GET /reports/requests/export` |
| Audit log | `GET /audit-logs` (search, date range, user, request, action filters) · `GET /audit-logs/export` |
| Notifications | `GET /notifications` · `PATCH /notifications/{id}/read` |

## Known limitations

Honest notes on what I would improve next:

- Access control is done two ways: a permission map (`core/permission.py`) in some
  routes and inline role checks in others. One mechanism would be easier to audit.
- `datetime.utcnow()` is used in a few places; it is deprecated from Python 3.12.
- Integration tests against a real Postgres are not in this repository yet — the
  suite is unit tests with a mocked session.
- `core/jwt.py` still declares an unused `ACCESS_TOKEN_EXPIRE_MINUTES = 30`
  constant; the real value comes from `config.py`.

---

## Team and my contributions

This was a team project built during an IT traineeship. The backend was written mainly
by three developers; the rest of the team worked on the other parts of the system. Code in this repository
belongs to its authors; this copy is shared as a portfolio piece.

**What I built** (Nasrin Babaei):

- **User and role management** — create, edit, change role, activate / deactivate,
  each action audit-logged in the same transaction, with guardrails against an
  admin locking themselves out
- **Approve / reject flow** — including the rule that approvers can submit their own
  requests but never decide on them
- **Audit log** — the admin endpoint, audit writes for request and comment creation,
  and the filtered CSV export (IP addresses deliberately excluded for GDPR)
- **Request types** — moved them from hard-coded Python into the database
  (`slug`, boolean `is_active`), the list and create endpoints
- **Personal data export** for requesters
- **Request numbering**, request details, the login endpoint and the first RBAC permission map
- **Schema drift diagnosis** — found why the dev server had UUID keys while every local
  database had integers (two migrations had been edited after they were applied),
  and planned the rebuild that fixed it

Teammates: Yasin Sinan · mithatp · ABDULRAHMANhadda01 · Betulmotopp ·
samanehnoori · Zeki Tazegul
