# Postgres-Native RBAC and Multi-Project Portal — Design

**Date:** 2026-07-23
**Status:** Approved by Michael (approach B — Postgres-native enforcement)
**Scope:** Central multi-user deployment of the CPLAN studio with role-based
access control enforced by PostgreSQL (roles + row level security), plus a
small portal application providing login, project tiles, and user
administration for CPLAN and future projects.

## Context

Today the studio (`pipeline/studio/`) talks to a local FastAPI
(`pipeline/api/app.py`) backed by embedded Postgres or SQLite. There is no
authentication and no authorization — deployment target was "local,
single-user". The next step is a central instance in the corp network serving
multiple users with distinct permission levels.

Decisions made during brainstorming:

- **Deployment:** one central server (API + PostgreSQL) in the corp network,
  users access via browser.
- **Identity:** app login with username + password. No corp SSO dependency.
- **Enforcement:** in PostgreSQL itself (approach B) — per-user database
  roles, GRANTs, and row level security. The API impersonates the logged-in
  user per request. Rationale: rights then also apply to direct pgAdmin
  access (already used for the analysis views), password handling is fully
  delegated to Postgres, and RLS expresses the "own rows" rule without app
  logic.
- **Portal:** built now, as the shared shell for multiple projects — landing
  page with login, project tiles, and centralized user administration. CPLAN
  is the first registered project.

## Role model

Two layers: **group roles** carry privileges (NOLOGIN), **user roles** are
real login roles (SCRAM password in Postgres) granted into group roles.

| Group role | Privileges |
|---|---|
| `cplan_viewer` | `SELECT` on all CPLAN tables and analysis views |
| `cplan_contributor` | viewer + `INSERT`; `UPDATE` restricted by RLS to own rows |
| `cplan_editor` | viewer + `INSERT` + `UPDATE` on all rows |
| `cplan_admin` | member of `cplan_editor`, plus `DELETE` on all rows, plus user administration (via portal SECURITY DEFINER functions) |
| `cplan_sync` | service role for `daily_refresh` / `sync_snapshot`; full write on mirrored rows |

- A user holds exactly one CPLAN group role. Future projects define their own
  group roles (`<project>_viewer`, …) in the same cluster; the user role is
  the shared identity, per-project rights are group memberships.
- Everyone may always edit their **own** entries: contributors get this via
  RLS; editors/admins can edit everything anyway. Viewers stay strictly
  read-only, including rows they might theoretically own.
- **Delete is admin-only.** There is currently no DELETE endpoint; it is
  added as part of this work and restricted to `cplan_admin`.

## Ownership and row level security

New column `activities.created_by TEXT NOT NULL DEFAULT current_user`
(backfill existing rows: mirrored/seeded rows → `'cplan_sync'`,
studio-created rows → the migrating admin or `'cplan_sync'` fallback).

RLS on `activities` (`ENABLE` + `FORCE ROW LEVEL SECURITY`):

```sql
CREATE POLICY read_all       ON activities FOR SELECT USING (true);

CREATE POLICY contrib_insert ON activities FOR INSERT TO cplan_contributor
  WITH CHECK (created_by = current_user);          -- no spoofing

CREATE POLICY contrib_update ON activities FOR UPDATE TO cplan_contributor
  USING (created_by = current_user);

CREATE POLICY editor_write   ON activities FOR ALL TO cplan_editor, cplan_sync
  USING (true) WITH CHECK (true);

CREATE POLICY admin_delete   ON activities FOR DELETE TO cplan_admin
  USING (true);
```

Mirrored SharePoint rows carry `created_by = 'cplan_sync'` and are therefore
"foreign" to every contributor — only editors/admins may modify them, which
matches the sync policy (source wins; studio edits to mirrored rows are an
editor decision).

`activity_changes` gets `INSERT` for all writing roles and `SELECT` for all
roles. The `actor` column now records `current_user` (the real user) instead
of the fixed `'studio'`; `'sync'` and `'seed'` remain for service writes.
Deletes append a `change_type = 'deleted'` row (snapshot of the deleted
activity's key fields in `old_value`) — the audit trail outlives the row, and
`activity_changes` deliberately has no FK to `activities`, so history is
preserved. Sequences used by writing roles get `GRANT USAGE`.

## Connection model: authenticator + SET LOCAL ROLE

PostgREST pattern. The API pools **one** connection identity,
`cplan_authenticator` (LOGIN, zero privileges), and switches identity per
request:

```
Login:    POST /api/login {username, password}
          → API opens a throwaway Postgres connection with those credentials
          → success ⇒ signed session token (contains username + role), cookie
          → password verification is 100% delegated to Postgres (SCRAM)

Request:  validate token → begin transaction → SET LOCAL ROLE <username>
          → handler queries run with that user's privileges and current_user
          → transaction end resets the role automatically
```

- Every user role is granted to `cplan_authenticator`
  (`GRANT <user> TO cplan_authenticator`) so `SET ROLE` is permitted — this
  grant is part of user creation.
- Token: signed (itsdangerous or PyJWT, HS256, server-side secret), short
  TTL with sliding renewal. The token is a session pointer, not the
  authority — even a forged role claim only changes UI rendering; Postgres
  rejects unauthorized statements with `42501`.
- API surface: `POST /api/login`, `POST /api/logout`, `GET /api/me`
  (username + resolved role for UI gating). All `/api/*` data endpoints
  require the session; unauthenticated ⇒ `401`.
- A FastAPI dependency wraps "session per request + SET LOCAL ROLE"; handlers
  keep their current shape.

## Portal

Separate small service (`portal/` — FastAPI + static frontend in the studio's
corporate style), same Postgres cluster, own schema `portal`:

- **Landing page:** login → tiles for the projects where the user holds a
  group role (derived from `pg_auth_members`), each linking to the project
  URL. Session is shared with project APIs via the same signed cookie
  (same secret, same domain).
- **User administration** (visible to `cplan_admin` only): create user,
  deactivate (`ALTER ROLE ... NOLOGIN`), reset password, assign/change the
  group role per project. Implemented as `SECURITY DEFINER` functions owned
  by a dedicated `portal_owner` role — the portal service itself runs
  unprivileged and can execute exactly these operations, nothing else:
  - `portal.create_user(name, password, project, role)`
  - `portal.set_project_role(name, project, role)`
  - `portal.reset_password(name, password)`
  - `portal.set_active(name, active)`
  Functions validate inputs against `portal.projects` and the known role
  suffixes before interpolating into DDL (identifier quoting via `format()`
  with `%I`).
- **Project registry:** `portal.projects (slug, name, url, role_prefix)` —
  CPLAN is the first row; a future project registers itself with one insert
  and its own group roles.

## Studio changes

- Login redirect: unauthenticated studio loads redirect to the portal login;
  after login the portal links back.
- Role-aware UI (comfort, not security): viewers see no "New
  activity"/edit/pack-drawer affordances; contributors see edit only on own
  rows (`created_by == me` from `GET /api/me`); admins additionally see
  Delete (with confirm dialog). The server remains the authority — a
  manipulated UI gets `403` (mapped from Postgres `42501`).
- `PATCH`/`DELETE` handlers map `insufficient_privilege` and RLS row
  invisibility to clean `403`/`404` API errors.

## Consequences and limits

- **SQLite fallback:** remains for local solo development only, without
  roles/auth (documented in `pipeline/api/README.md`). The central server
  requires PostgreSQL.
- **Batch endpoint & tracking IDs:** unchanged — they need SELECT + INSERT,
  which contributor+ has. Tracking-ID uniqueness still enforced by the
  existing unique constraint.
- **pgAdmin:** viewer users may safely receive direct read access to the
  analysis views — identical rights as in the studio.
- **Embedded pgserver:** stays the corp-quick-start backend; the role/RLS
  DDL runs identically there, so the full rights model is testable locally.
- **Migration:** an idempotent setup script (extends
  `pipeline/api/setup_backend.py` or a new `setup_roles.py`) creates group
  roles, authenticator, portal schema/functions, RLS policies, and the
  `created_by` column. First admin user is created by the script.

## Testing

- **Rights matrix (pytest, embedded Postgres):** every group role × every
  operation (SELECT / INSERT / UPDATE own / UPDATE foreign / DELETE own /
  DELETE foreign) — asserting both the allowed path and the `42501`/RLS
  denial. Includes `cplan_sync` against mirrored vs. studio-created rows.
- **Auth flow:** login success/failure, token expiry, `SET LOCAL ROLE`
  isolation across requests (no identity bleed in the pool), deactivated
  user (`NOLOGIN`) rejected at login.
- **Portal functions:** SECURITY DEFINER functions reject unknown projects/
  roles and SQL-injection-shaped identifiers.
- **Existing suites** (`tests/`, incl. `test_views.py`) keep passing when run
  as `cplan_admin`.
