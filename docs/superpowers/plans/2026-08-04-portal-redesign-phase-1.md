# Portal Redesign — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the portal's assembled-looking single page with the reviewed design — sign-in, project tiles, a users list and a user × project access matrix — plus the three backend additions that design needs.

**Architecture:** The frontend becomes a small ES-module single-page app served by the same FastAPI `StaticFiles` mount as today (no build step, no bundler, no framework). The access matrix is a client-side pivot of `portal.users`, which already returns one row per user × project × role — so it needs no new read endpoint. Three backend gaps are closed: the project's purpose (read from its `resources.json` manifest, not a new column) plus the caller's own role on the tiles endpoint, a `portal.revoke_project_role` function so a matrix cell can be emptied, and a `portal.user_profile` table so display names and last-sign-in have somewhere to live.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, PostgreSQL 16 (embedded via `pgserver`), plain ES modules, `unittest` + `pytest`.

## Global Constraints

- **No employer brand name anywhere in the repository** — not in code, identifiers, CSS classes, comments, docs, test data, or commit messages. Use generic terms: `--primary`, `.btn-primary`, "the organisation", "internal platform".
- **No absolute local paths in committed files.**
- **Corporate design system is binding** (`Arbeit/00-design-system/corporate-design-system.md`): white dominant, greys and pastels next, red and bronze as small accents only; solid colours only, no gradients, no tints of the brand red; no drop shadows, no rounded corners beyond the `--radius: 2px` token, no decorative elements; type is `"Frutiger 45 Light", "Frutiger", "Helvetica Neue", Arial, "Segoe UI", system-ui, sans-serif`; no ALL CAPS, no underlines, no coloured text for emphasis; left-aligned, never justified; RAG colours for data-driven status only.
- **Reference implementation:** the reviewed prototype in the Claude Design project `CPLAN Studio` (`e0b5307c-9db2-4773-9060-18895177240d`) under `portal/`. `portal/portal.css` and `portal/portal.js` there are the source of truth for the visual system and interaction behaviour. Fetch with `DesignSync get_file`; they are deliberately not in this repo.
- **Groups and the access audit log are out of scope for this plan.** They are future state, tracked as Phase 2 and Phase 3. Do not add group concepts, inheritance, or `role-inherited` markers in Phase 1 — with no groups, every grant in `portal.users` is a direct grant and the effective role is the stored role.
- **Access semantics (decided):** role membership is additive (PostgreSQL union). When groups arrive in Phase 2, effective access is the strongest grant from any source; a direct grant can never put someone below what a group gives. Do not design Phase 1 code that assumes override semantics.
- **Every new SQL function** follows the existing conventions in `pipeline/api/setup_portal.py`: `SECURITY DEFINER`, `SET search_path = pg_catalog, public`, identifier quoting via `format %I/%L`, plain `RAISE EXCEPTION` (SQLSTATE P0001, never a class-22 code), every literal `%` doubled to `%%`, owned by `portal_owner`, `REVOKE ALL ... FROM PUBLIC` then an explicit `GRANT EXECUTE`.
- **Tests run from the repository root** with `PYTHONPATH=.` and the repo venv: `PYTHONPATH=. .venv/bin/python -m pytest tests/<file> -v`. Postgres-backed tests are skipped automatically when `pgserver` is absent.

---

## File Structure

**Backend — modified:**
- `pipeline/api/setup_portal.py` — schema, registry, SECURITY DEFINER functions. Gains: the `portal.user_profile` table, and three new functions (`revoke_project_role`, `set_display_name`, `record_sign_in`).
- `pipeline/portal/app.py` — HTTP surface. Gains: richer `/api/portal/projects`, a revoke endpoint, a display-name endpoint, and a sign-in timestamp write on login.

**Frontend — replaced.** Today's `static/{index.html,styles.css,app.js}` become a module layout, one responsibility per file:
- `pipeline/portal/static/index.html` — markup shell for every screen (create, replacing current)
- `pipeline/portal/static/styles.css` — design-system implementation (create, replacing current)
- `pipeline/portal/static/js/api.js` — fetch wrappers, session, 401 handling
- `pipeline/portal/static/js/state.js` — in-memory model, role ordering, derived counts
- `pipeline/portal/static/js/ui.js` — shared render helpers: escaping, role chip, status cell, toast
- `pipeline/portal/static/js/home.js` — project tiles
- `pipeline/portal/static/js/users.js` — users table with search, filter, sort
- `pipeline/portal/static/js/matrix.js` — access matrix, role popover, CSV export
- `pipeline/portal/static/js/drawer.js` — person drawer
- `pipeline/portal/static/js/invite.js` — invite modal
- `pipeline/portal/static/js/app.js` — boot and navigation

**Frontend — restyled, not restructured.** The project-page feature landed after this plan was first written. These files keep their current structure and behaviour; they only inherit the new visual system, because they already share `styles.css` with the portal home:
- `pipeline/portal/static/project.html` — a project's own page (modify: chrome only)
- `pipeline/portal/static/project.js` — unchanged
- `pipeline/portal/static/document.css` — the rendered-manual/document stylesheet, checked for the same design-system rules

**Tests — modified/created:**
- `tests/test_portal_api.py` — extend for the new endpoints
- `tests/test_setup_portal.py` — extend for the new schema objects and functions
- `tests/test_portal_frontend.py` — rewrite the static markers for the new file layout

---

### Task 1: Project purpose and the caller's own role on the tiles endpoint

Today a home tile shows only the project name. Give it the project's one-line purpose and the role the caller holds on that project.

**This task was rewritten on 2026-08-05**, after the project-page feature landed. Its original form added a `purpose` column to `portal.projects`. That would now be a second source of truth: `pipeline/portal/projects/<slug>/resources.json` already carries `purpose`, the project page reads it from there, and `apply_portal`'s upsert would re-assert the seeded constant on every deploy — so editing the repository file would appear to work and then silently stop. The manifest wins: it versions with the manual and the document titles that live beside it, it needs no migration, and registering a second project already requires dropping that file.

**Files:**
- Modify: `pipeline/portal/app.py` (the `projects` endpoint only)
- Test: `tests/test_portal_api.py`
- `pipeline/api/setup_portal.py` is NOT touched. No column, no `ALTER TABLE`, no seed change, and `register_project` keeps its current signature.

**Interfaces:**
- Consumes: `load_manifest(slug, root=PROJECTS_ROOT) -> dict` and the module-level SQL fragments `PROJECT_VISIBLE` and `PROJECT_ROLE`, all already in the codebase.
- Produces: `GET /api/portal/projects` returns `{"projects": [{"slug": str, "name": str, "url": str, "purpose": str | None, "role": "admin"|"editor"|"contributor"|"viewer"}]}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_portal_api.py`:

```python
def test_projects_endpoint_returns_purpose_and_callers_role(portal):
    client = login(portal, "pa_admin")
    body = client.get("/api/portal/projects").json()
    cplan = next(p for p in body["projects"] if p["slug"] == "cplan")
    assert cplan["role"] == "admin"
    assert cplan["purpose"]

    viewer = login(portal, "pa_viewer")
    cplan_as_viewer = next(
        p for p in viewer.get("/api/portal/projects").json()["projects"] if p["slug"] == "cplan"
    )
    assert cplan_as_viewer["role"] == "viewer"
```

This asserts the payload, not the mechanism, so it is the acceptance criterion for this task however it is implemented.

- [ ] **Step 2: Run it to make sure it fails**

Run: `CPLAN_TEST_DATABASE_URL=... PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_api.py::test_projects_endpoint_returns_purpose_and_callers_role -v`
Expected: FAIL with `KeyError: 'role'`.

- [ ] **Step 3: Return purpose and the caller's role**

Replace the `projects` endpoint in `pipeline/portal/app.py`. Reuse `PROJECT_ROLE` and `PROJECT_VISIBLE` — they already resolve role names through `to_regrole`, and they exist precisely so this rule is written once:

```python
    @app.get("/api/portal/projects")
    def projects(session: Session = Depends(db_session)):
        rows = session.execute(
            text(
                "SELECT p.slug, p.name, p.url, "
                f"  {PROJECT_ROLE} AS role "
                "FROM portal.projects p "
                f"WHERE {PROJECT_VISIBLE} "
                "ORDER BY p.name"
            )
        ).all()
        return {
            "projects": [
                {
                    "slug": r.slug,
                    "name": r.name,
                    "url": r.url,
                    "purpose": load_manifest(r.slug, root=PROJECTS_ROOT).get("purpose"),
                    "role": r.role,
                }
                for r in rows
            ]
        }
```

Two things this must NOT do, both of them regressions of measured defects:

- **Do not write the four `pg_has_role` arms out by hand, and do not pass bare role names.** `pg_has_role` raises SQLSTATE 42704 for a name that is not a role, so one project registered before its group roles exist takes this endpoint — the landing page — down for every caller, cluster-wide. That was measured and fixed; `tests/test_portal_api.py::test_projects_list_survives_a_project_with_no_group_roles` guards it.
- **Do not add `ELSE 'viewer'` to the role CASE.** `PROJECT_ROLE` deliberately yields NULL when the caller holds no role, so "no access" cannot be laundered into "viewer". `PROJECT_VISIBLE` already excludes those rows here, so the NULL never reaches the payload.

The manifest read is one sub-kilobyte JSON parse per visible project, and `project_detail` already does exactly this per request. If it ever measures as a problem, memoise on file mtime — do not move the field into the database.

- [ ] **Step 4: Run the portal API tests**

Run: `CPLAN_TEST_DATABASE_URL=... PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_api.py -v`
Expected: PASS, including the two guard tests named above.

- [ ] **Step 5: Commit**

```bash
git add pipeline/portal/app.py tests/test_portal_api.py
git commit -m "Show what a project is for, and what you may do on it"
```
---

### Task 2: Revoke a project role

`portal.set_project_role` can only revoke-then-grant, so a matrix cell can be changed but never emptied. Add the missing operation.

**Files:**
- Modify: `pipeline/api/setup_portal.py` (new `_REVOKE_ROLE_FN`, add to `_FUNCTIONS`)
- Modify: `pipeline/portal/app.py` (new endpoint)
- Test: `tests/test_setup_portal.py`, `tests/test_portal_api.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `portal.revoke_project_role(p_name text, p_project text)` and `POST /api/portal/users/{username}/revoke` with body `{"project": str}`, returning `{"status": "ok"}`.

- [ ] **Step 1: Write the failing API test**

Add to `tests/test_portal_api.py`:

```python
def test_admin_can_revoke_a_project_role(portal):
    client = login(portal, "pa_admin")
    client.post(
        "/api/portal/users",
        json={"username": "pa_temp", "password": "pw-t", "project": "cplan", "role": "viewer"},
    )
    assert any(u["username"] == "pa_temp" for u in client.get("/api/portal/users").json()["users"])

    response = client.post("/api/portal/users/pa_temp/revoke", json={"project": "cplan"})
    assert response.status_code == 200
    assert not any(u["username"] == "pa_temp" for u in client.get("/api/portal/users").json()["users"])


def test_non_admin_cannot_revoke(portal):
    viewer = login(portal, "pa_viewer")
    response = viewer.post("/api/portal/users/pa_admin/revoke", json={"project": "cplan"})
    assert response.status_code == 403
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_api.py -k revoke -v`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Add the SQL function**

In `pipeline/api/setup_portal.py`, after `_SET_ROLE_FN`:

```python
# Removing every assignable group role for one project drops the user out of
# portal.users for that project entirely — which is what an emptied matrix cell
# means. The account itself and any access to OTHER projects are untouched.
_REVOKE_ROLE_FN = f"""
CREATE OR REPLACE FUNCTION portal.revoke_project_role(p_name text, p_project text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
DECLARE v_prefix text; r text;
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  SELECT role_prefix INTO v_prefix FROM portal.projects WHERE slug = p_project;
  IF v_prefix IS NULL THEN
    RAISE EXCEPTION 'unknown project %%', p_project;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
  FOREACH r IN ARRAY ARRAY['viewer','contributor','editor','admin'] LOOP
    EXECUTE format('REVOKE %%I FROM %%I', v_prefix || '_' || r, p_name);
  END LOOP;
END; $fn$;
"""
```

Register it in `_FUNCTIONS` so `apply_portal` creates it, sets its owner, and grants EXECUTE:

```python
_FUNCTIONS = (
    ("portal.create_user(text, text, text, text)", _CREATE_USER_FN),
    ("portal.set_project_role(text, text, text)", _SET_ROLE_FN),
    ("portal.revoke_project_role(text, text)", _REVOKE_ROLE_FN),
    ("portal.reset_password(text, text)", _RESET_PW_FN),
    ("portal.set_active(text, boolean, text)", _SET_ACTIVE_FN),
)
```

- [ ] **Step 4: Add the endpoint**

In `pipeline/portal/app.py`, add the payload model next to `RolePayload`:

```python
class RevokePayload(BaseModel):
    project: str = Field(min_length=1)
```

And the route, directly after `set_role_endpoint`:

```python
    @app.post("/api/portal/users/{username}/revoke")
    def revoke_role_endpoint(username: str, payload: RevokePayload, session: Session = Depends(db_session)):
        _call(session, "SELECT portal.revoke_project_role(:n, :proj)", {"n": username, "proj": payload.project})
        return {"status": "ok"}
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_api.py tests/test_setup_portal.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/api/setup_portal.py pipeline/portal/app.py tests/test_portal_api.py
git commit -m "feat(portal): allow an admin to revoke a user's role on one project"
```

---

### Task 3: Display names and last sign-in

Users are PostgreSQL roles, so there is nowhere to put a human name or a sign-in timestamp. Add the one table that fixes both.

**Files:**
- Modify: `pipeline/api/setup_portal.py` (new table, two functions, extended `_USERS_VIEW`)
- Modify: `pipeline/portal/app.py` (record on login, expose and set the display name)
- Test: `tests/test_setup_portal.py`, `tests/test_portal_api.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `GET /api/portal/users` rows gain `display_name: str | None` and `last_sign_in: str | None` (ISO-8601). `POST /api/portal/users/{username}/display-name` with body `{"display_name": str}`. `POST /api/portal/users` accepts an optional `display_name`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_portal_api.py`:

```python
def test_login_records_sign_in_and_display_name_round_trips(portal):
    client = login(portal, "pa_admin")
    client.post("/api/portal/users/pa_viewer/display-name", json={"display_name": "Vera Iewer"})

    row = next(u for u in client.get("/api/portal/users").json()["users"] if u["username"] == "pa_viewer")
    assert row["display_name"] == "Vera Iewer"

    login(portal, "pa_viewer")
    refreshed = next(u for u in client.get("/api/portal/users").json()["users"] if u["username"] == "pa_viewer")
    assert refreshed["last_sign_in"] is not None
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_api.py::test_login_records_sign_in_and_display_name_round_trips -v`
Expected: FAIL with 404 on the display-name route.

- [ ] **Step 3: Add the table and functions**

In `pipeline/api/setup_portal.py`, add after `_SET_ACTIVE_FN`:

```python
# Names are not secret — every signed-in user may read them, so a tile or a
# drawer can say "Andrea Keller" instead of "a.keller". Writes go through
# SECURITY DEFINER functions: set_display_name is admin-only, record_sign_in is
# called by the service identity on the login path, before any SET ROLE happens.
_SET_DISPLAY_NAME_FN = f"""
CREATE OR REPLACE FUNCTION portal.set_display_name(p_name text, p_display text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
  INSERT INTO portal.user_profile (username, display_name) VALUES (p_name, p_display)
  ON CONFLICT (username) DO UPDATE SET display_name = EXCLUDED.display_name;
END; $fn$;
"""

_RECORD_SIGN_IN_FN = """
CREATE OR REPLACE FUNCTION portal.record_sign_in(p_name text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
BEGIN
  INSERT INTO portal.user_profile (username, last_sign_in) VALUES (p_name, now())
  ON CONFLICT (username) DO UPDATE SET last_sign_in = now();
END; $fn$;
"""
```

Extend the users view to carry both columns — replace `_USERS_VIEW`'s `SELECT` list and add the join:

```python
_USERS_VIEW = """
CREATE OR REPLACE VIEW portal.users AS
SELECT u.rolname AS username,
       p.slug    AS project,
       CASE g.rolname
         WHEN p.role_prefix || '_admin'       THEN 'admin'
         WHEN p.role_prefix || '_editor'      THEN 'editor'
         WHEN p.role_prefix || '_contributor' THEN 'contributor'
         WHEN p.role_prefix || '_viewer'      THEN 'viewer'
       END AS role,
       u.rolcanlogin AS active,
       pr.display_name,
       pr.last_sign_in
FROM pg_roles u
JOIN pg_auth_members am ON am.member = u.oid
JOIN pg_roles g ON g.oid = am.roleid
JOIN portal.projects p ON g.rolname IN (
    p.role_prefix || '_viewer', p.role_prefix || '_contributor',
    p.role_prefix || '_editor', p.role_prefix || '_admin')
LEFT JOIN portal.user_profile pr ON pr.username = u.rolname
WHERE u.rolname NOT IN ('cplan_authenticator', 'portal_owner')
  -- Group and service roles are not accounts: the privilege hierarchy
  -- (GRANT <prefix>_viewer TO <prefix>_contributor TO ...) makes the group
  -- roles members of each other, so without this filter they would list as
  -- pseudo-users ("cplan_admin / editor / Disabled").
  AND u.rolname NOT IN (
      SELECT p2.role_prefix || suffix.s
      FROM portal.projects p2,
           (VALUES ('_viewer'), ('_contributor'), ('_editor'), ('_admin'), ('_sync')) AS suffix(s)
  );
"""
```

Add both functions to `_FUNCTIONS`:

```python
    ("portal.set_display_name(text, text)", _SET_DISPLAY_NAME_FN),
    ("portal.record_sign_in(text)", _RECORD_SIGN_IN_FN),
```

In `apply_portal`, create the table before the view is created (the view now depends on it) — put it directly after the `ALTER TABLE portal.projects OWNER TO portal_owner` line:

```python
        c.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS portal.user_profile ("
            "username text PRIMARY KEY, display_name text, last_sign_in timestamptz)"
        )
        c.exec_driver_sql("ALTER TABLE portal.user_profile OWNER TO portal_owner")
        c.exec_driver_sql("GRANT SELECT ON portal.user_profile TO PUBLIC")
```

`record_sign_in` runs on the login path as the service identity, not as an admin, so it needs its own grant. After the `for signature, ddl in _FUNCTIONS:` loop in `apply_portal`, add:

```python
        # Every other portal.* function is admin-only. record_sign_in is called
        # on the login path, before the request has a SET ROLE'd identity, so it
        # is granted to the service role instead. It writes one timestamp for the
        # name it is given and reveals nothing.
        c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION portal.record_sign_in(text) TO {AUTHENTICATOR}")
```

- [ ] **Step 4: Wire the endpoints**

In `pipeline/portal/app.py`, add the payload model:

```python
class DisplayNamePayload(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
```

Extend `CreateUserPayload` with an optional name:

```python
class CreateUserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=63)
    password: str = Field(min_length=1)
    project: str = Field(min_length=1)
    role: str = Field(min_length=1)
    display_name: str | None = Field(default=None, max_length=200)
```

Record the sign-in in `login`, after credentials verify and before the cookie is set. It runs on the engine, not a request session, because the request has no role identity yet:

```python
        with engine.begin() as connection:
            connection.execute(
                text("SELECT portal.record_sign_in(:n)"), {"n": payload.username}
            )
```

Surface both columns in `list_users`:

```python
    @app.get("/api/portal/users")
    def list_users(session: Session = Depends(db_session)):
        # SELECT on portal.users is granted only to cplan_admin -> 42501 -> 403 for others.
        rows = session.execute(
            text(
                "SELECT username, project, role, active, display_name, last_sign_in "
                "FROM portal.users ORDER BY username"
            )
        ).all()
        return {
            "users": [
                {
                    "username": r.username,
                    "project": r.project,
                    "role": r.role,
                    "active": r.active,
                    "display_name": r.display_name,
                    "last_sign_in": r.last_sign_in.isoformat() if r.last_sign_in else None,
                }
                for r in rows
            ]
        }
```

Add the display-name route after `set_active_endpoint`:

```python
    @app.post("/api/portal/users/{username}/display-name")
    def set_display_name_endpoint(
        username: str, payload: DisplayNamePayload, session: Session = Depends(db_session)
    ):
        _call(session, "SELECT portal.set_display_name(:n, :d)", {"n": username, "d": payload.display_name})
        return {"status": "ok"}
```

And set the name on creation, inside `create_user_endpoint` after the `portal.create_user` call:

```python
        if payload.display_name:
            _call(
                session,
                "SELECT portal.set_display_name(:n, :d)",
                {"n": payload.username, "d": payload.display_name},
            )
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_api.py tests/test_setup_portal.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/api/setup_portal.py pipeline/portal/app.py tests/test_portal_api.py tests/test_setup_portal.py
git commit -m "feat(portal): record display names and last sign-in per account"
```

---

### Task 4: The design-system stylesheet

Replace the 47-line stylesheet with the reviewed one. This also removes the `box-shadow` on panels, which the design system forbids.

**Files:**
- Create (replacing): `pipeline/portal/static/styles.css`
- Test: `tests/test_portal_frontend.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the class contract every later frontend task renders against — `.topbar`, `.main-nav`, `.nav-item`, `.content`, `.page`, `.page-title`, `.page-subtitle`, `.section-head`, `.section-heading`, `.footnote`, `.btn` (`.primary`, `.quiet`, `.danger`, `.sm`), `.tiles`, `.tile`, `.role` (`.role-admin`, `.role-editor`, `.role-contributor`, `.role-viewer`, `.role-none`), `.status` (`.active`, `.disabled`, `.pending`), `.status-dot`, `.toolbar`, `.result-count`, `.table-wrap`, `.matrix-wrap`, `table.matrix`, `.cell-btn`, `.popover`, `.popover-option`, `.drawer`, `.drawer-panel`, `.access-row`, `.modal-overlay`, `.modal-card`, `.field`, `.role-picker`, `.role-choice`, `.notice`, `.empty`, `.toast`, `.signin`.

- [ ] **Step 1: Write the failing test**

Replace `test_no_emoji_and_corporate_palette` in `tests/test_portal_frontend.py` with:

```python
    def test_stylesheet_follows_the_design_system(self):
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        self.assertIn("#E60000", css)                 # corporate red primary
        self.assertIn("#F7F7F5", css)                 # page background
        self.assertIn("Frutiger 45 Light", css)       # brand typeface, not system-ui
        self.assertIn("--radius: 2px", css)
        # Drop shadows are forbidden on layout surfaces; the shipped portal had
        # one on every panel. Overlay scrims are not shadows and stay allowed.
        for rule in ("box-shadow", "linear-gradient", "radial-gradient"):
            self.assertNotIn(rule, css, f"{rule} is forbidden by the design system")

    def test_role_ramp_and_status_classes_exist(self):
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        for cls in (".role-admin", ".role-editor", ".role-contributor", ".role-viewer", ".role-none"):
            self.assertIn(cls, css)
        for cls in (".status", ".status-dot", ".toast", ".popover", ".drawer-panel"):
            self.assertIn(cls, css)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -v`
Expected: FAIL — `Frutiger 45 Light` is absent and `box-shadow` is present.

- [ ] **Step 3: Install the reviewed stylesheet**

Fetch `portal/portal.css` from the Claude Design project and write it to `pipeline/portal/static/styles.css` verbatim:

```
DesignSync get_file
  projectId: e0b5307c-9db2-4773-9060-18895177240d
  path: portal/portal.css
```

It already carries the full token set, the type scale, the grey role ramp and the seam-grid tiles. Do not re-derive it. Confirm no `box-shadow` survives — the drawer uses `border-left` and the modal uses a border, both deliberate.

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -v`
Expected: the two new tests PASS. The markup tests still fail — Task 5 replaces the markup.

- [ ] **Step 5: Commit**

```bash
git add pipeline/portal/static/styles.css tests/test_portal_frontend.py
git commit -m "feat(portal): adopt the design-system stylesheet and drop the forbidden shadows"
```

---

### Task 5: Markup shell and navigation

**Files:**
- Create (replacing): `pipeline/portal/static/index.html`
- Create: `pipeline/portal/static/js/app.js`
- Modify: `pipeline/portal/static/project.html` (chrome only — see Step 4a)
- Test: `tests/test_portal_frontend.py`

**Interfaces:**
- Consumes: the class contract from Task 4.
- Produces: element IDs every later task renders into — `screen-signin`, `signin-form`, `si-user`, `si-pass`, `si-error`, `screen-app`, `sign-out`, `project-tiles`, `user-table`, `user-rows`, `user-search`, `user-filter-role`, `user-filter-status`, `user-count`, `user-empty`, `user-clear-filters`, `matrix-table`, `matrix-head`, `matrix-rows`, `matrix-search`, `matrix-filter-project`, `matrix-count`, `matrix-export`, `person-drawer`, `drawer-avatar`, `drawer-name`, `drawer-meta`, `drawer-body`, `invite-open`, `invite-modal`, `invite-form`, `iv-username`, `iv-password`, `iv-generate`, `iv-project`, `iv-roles`, `iv-error`, `toast`, `toast-text`, `toast-undo`. Also required by later tasks: `data-close-drawer` on the drawer backdrop and close button, `data-close-modal` on the invite Cancel button, and `th.sortable` with `data-sort="name"|"role"|"projects"` plus a `.sort-arrow` span in the users table head. Exports `show(page)` from `js/app.js`, where `page` is one of `home`, `users`, `matrix`.

- [ ] **Step 1: Write the failing test**

Replace the markup tests in `tests/test_portal_frontend.py`:

```python
    def test_shell_markup_has_every_screen(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for element_id in (
            "screen-signin", "screen-app", "project-tiles", "user-rows",
            "matrix-rows", "person-drawer", "invite-modal", "toast",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('type="module"', html)
        self.assertIsNone(EMOJI.search(html))

    def test_navigation_covers_the_three_pages(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for page in ("home", "users", "matrix"):
            self.assertIn(f'data-page="{page}"', html)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py::PortalFrontendTests::test_shell_markup_has_every_screen -v`
Expected: FAIL — `screen-signin` is absent.

- [ ] **Step 3: Install the markup**

Fetch `portal/portal-workbench.html` from the Design project, take everything between `<body>` and the closing `</body>` **except** the two trailing `<script>` blocks, and write it as the body of `pipeline/portal/static/index.html`. Drop the prototype-only pieces: the Groups and Activity-log `<section class="page">` blocks and their nav items (both are Phase 2/3), and the `notice` blocks inside them.

The head must be:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CPLAN Portal</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2024%2024'%3E%3Crect%20width='24'%20height='24'%20fill='%23FFFFFF'/%3E%3Crect%20x='9'%20width='6'%20height='24'%20fill='%23E60000'/%3E%3C/svg%3E">
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
```

and the closing:

```html
  <script type="module" src="js/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write the boot and navigation module**

Create `pipeline/portal/static/js/app.js`:

```javascript
/* Boot and navigation. Every render module owns one page and is called from here. */
import { getSession, signIn, signOut } from './api.js';
import { state } from './state.js';
import { renderHome, loadHome } from './home.js';
import { renderUsers, loadUsers, wireUsers } from './users.js';
import { renderMatrix, wireMatrix } from './matrix.js';
import { wireDrawer } from './drawer.js';
import { wireInvite } from './invite.js';

export function show(page) {
  state.page = page;
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === `page-${page}`));
  document.querySelectorAll('.popover').forEach((p) => p.remove());
}

async function enterApp() {
  document.getElementById('screen-signin').hidden = true;
  document.getElementById('screen-app').hidden = false;
  await Promise.all([loadHome(), loadUsers()]);
  renderHome();
  renderUsers();
  renderMatrix();
  show('home');
}

function showSignIn() {
  document.getElementById('screen-app').hidden = true;
  document.getElementById('screen-signin').hidden = false;
}

document.querySelectorAll('.nav-item').forEach((b) => { b.onclick = () => show(b.dataset.page); });

document.getElementById('signin-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const ok = await signIn(
    document.getElementById('si-user').value.trim(),
    document.getElementById('si-pass').value,
  );
  document.getElementById('si-error').hidden = ok;
  if (ok) await enterApp();
});

document.getElementById('sign-out').addEventListener('click', async () => {
  await signOut();
  window.location.reload();
});

wireUsers();
wireMatrix();
wireDrawer();
wireInvite();

const session = await getSession();
if (session) { await enterApp(); } else { showSignIn(); }
```

- [ ] **Step 4a: Bring the project page onto the same chrome**

`project.html` already loads `/styles.css`, so Task 4 restyled it for free — but its header markup is the *old* shell (`.brand`, `.user-chip` with a `.btn-ghost`), which the new stylesheet no longer defines the same way. Left alone, the portal home and a project page would drift apart again — the exact fault the studio review opened with.

Replace only the `<header>` in `pipeline/portal/static/project.html` with the shell from `index.html`:

```html
  <header class="topbar">
    <div class="brand-block">
      <span class="brand-mark"></span>
      <div>
        <h1>CPLAN Portal</h1>
        <p>Communication planning</p>
      </div>
    </div>
    <div class="top-actions">
      <div class="user-chip hidden" id="user-chip">
        <span class="avatar" aria-hidden="true" id="user-chip-avatar"></span>
        <span id="user-chip-name"></span>
      </div>
      <button class="btn quiet" id="user-chip-logout" type="button">Sign out</button>
    </div>
  </header>
```

`project.js` sets `#user-chip-name` and unhides `#user-chip` already; both IDs survive, so it needs no change. Set the avatar beside it — in `loadUserChip()`, after the existing `textContent` assignment:

```javascript
    document.getElementById('user-chip-avatar').textContent =
      user.username.split(/[\s.]+/).filter(Boolean).map((p) => p[0]).join('').slice(0, 2).toUpperCase();
```

Leave the breadcrumb, page head and tile grid alone — they are the project-page feature's own design and are out of scope here.

- [ ] **Step 4b: Hold `document.css` to the same rules**

Add to `tests/test_portal_frontend.py`:

```python
    def test_document_stylesheet_follows_the_design_system(self):
        css = (STATIC / "document.css").read_text(encoding="utf-8")
        for rule in ("box-shadow", "linear-gradient", "radial-gradient"):
            self.assertNotIn(rule, css, f"{rule} is forbidden by the design system")

    def test_project_page_uses_the_portal_shell(self):
        html = (STATIC / "project.html").read_text(encoding="utf-8")
        self.assertIn('class="topbar"', html)
        self.assertIn('class="brand-block"', html)
        self.assertIn('class="btn quiet"', html)
        self.assertNotIn("btn-ghost", html)   # superseded button class
```

Fix any violation `document.css` turns out to carry, the same way Task 4 did for `styles.css`.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -k "shell or navigation" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/portal/static/index.html pipeline/portal/static/js/app.js tests/test_portal_frontend.py
git commit -m "feat(portal): rebuild the markup shell with sign-in, home, users and matrix"
```

---

### Task 6: API client and state

**Files:**
- Create: `pipeline/portal/static/js/api.js`
- Create: `pipeline/portal/static/js/state.js`
- Create: `pipeline/portal/static/js/ui.js`
- Test: `tests/test_portal_frontend.py`

**Interfaces:**
- Consumes: the endpoints from Tasks 1–3.
- Produces:
  - `api.js` — `getSession()`, `signIn(u, p)`, `signOut()`, `fetchProjects()`, `fetchUsers()`, `setRole(username, project, role)`, `revokeRole(username, project)`, `resetPassword(username, password)`, `setActive(username, active)`, `createUser(payload)`, `setDisplayName(username, name)`. Every mutating call resolves to `{ok: true}` or `{ok: false, message: string}` — no throwing.
  - `state.js` — `state` (`{me, projects, users, page, userSort}`), `ROLES`, `ROLE_LABEL`, `ROLE_DESC`, `rank(role)`, `accountsFromRows(rows)`, `accessFor(account, slug)`, `projectCount(account)`, `highestRole(account)`.
  - `ui.js` — `esc(value)`, `initials(name)`, `roleChip(role)`, `statusCell(account)`, `toast(message, undo)`, `closePopover()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_portal_frontend.py`:

```python
JS = STATIC / "js"

    def test_api_module_covers_every_endpoint(self):
        api = (JS / "api.js").read_text(encoding="utf-8")
        for route in (
            "/api/me", "/api/login", "/api/logout", "/api/portal/projects",
            "/api/portal/users", "/role", "/revoke", "/password", "/active", "/display-name",
        ):
            self.assertIn(route, api)

    def test_state_pivots_rows_into_accounts(self):
        state = (JS / "state.js").read_text(encoding="utf-8")
        # portal.users returns one row per user x project x role; the UI needs
        # one object per person carrying a per-project map.
        self.assertIn("accountsFromRows", state)
        self.assertIn("export const ROLES", state)
        self.assertIn("highestRole", state)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -k "api_module or state_pivots" -v`
Expected: FAIL with `FileNotFoundError` for `js/api.js`.

- [ ] **Step 3: Write `api.js`**

```javascript
/* Every call is same-origin and cookie-authenticated. Mutations never throw:
   they resolve to {ok, message} so a caller can toast the server's own
   validation text (422 carries it) instead of inventing one. */

async function post(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.ok) return { ok: true };
  if (response.status === 401) { window.location.reload(); return { ok: false, message: 'Session expired.' }; }
  if (response.status === 403) return { ok: false, message: 'You do not have permission.' };
  if (response.status === 422) return { ok: false, message: await validationMessage(response) };
  return { ok: false, message: 'The change could not be saved.' };
}

/* 422 bodies carry the portal.* function's own RAISE EXCEPTION text, e.g.
   "user x already exists". Postgres appends a CONTEXT block — take line one. */
async function validationMessage(response) {
  try {
    const body = await response.json();
    const message = body?.detail?.message;
    if (typeof message === 'string' && message.trim()) {
      return message.split('\n')[0].replace(/^ERROR:\s*/i, '').trim();
    }
  } catch (_) { /* not JSON */ }
  return 'That input was rejected.';
}

export async function getSession() {
  const response = await fetch('/api/me');
  return response.ok ? response.json() : null;
}

export async function signIn(username, password) {
  return (await post('/api/login', { username, password })).ok;
}

export async function signOut() {
  await fetch('/api/logout', { method: 'POST' });
}

export async function fetchProjects() {
  const response = await fetch('/api/portal/projects');
  return response.ok ? (await response.json()).projects : [];
}

export async function fetchUsers() {
  const response = await fetch('/api/portal/users');
  return response.ok ? (await response.json()).users : [];
}

const encode = encodeURIComponent;
export const setRole = (username, project, role) => post(`/api/portal/users/${encode(username)}/role`, { project, role });
export const revokeRole = (username, project) => post(`/api/portal/users/${encode(username)}/revoke`, { project });
export const resetPassword = (username, password) => post(`/api/portal/users/${encode(username)}/password`, { password });
export const setActive = (username, active) => post(`/api/portal/users/${encode(username)}/active`, { active });
export const setDisplayName = (username, displayName) => post(`/api/portal/users/${encode(username)}/display-name`, { display_name: displayName });
export const createUser = (payload) => post('/api/portal/users', payload);
```

- [ ] **Step 4: Write `state.js`**

```javascript
/* portal.users returns one row per user x project x role. The UI thinks in
   people, so rows are pivoted into accounts carrying a per-project map. */

export const ROLES = ['viewer', 'contributor', 'editor', 'admin'];
export const ROLE_LABEL = { admin: 'Admin', editor: 'Editor', contributor: 'Contributor', viewer: 'Viewer' };
export const ROLE_DESC = {
  admin: 'Everything an editor can do, plus deleting activities and managing access.',
  editor: 'Create activities and edit any activity, including other people’s.',
  contributor: 'Create activities and edit only the ones they created.',
  viewer: 'Read everything. Change nothing.',
};

export const state = { me: null, projects: [], users: [], page: 'home', userSort: { key: 'name', dir: 1 } };

export const rank = (role) => (role ? ROLES.indexOf(role) : -1);
export const project = (slug) => state.projects.find((p) => p.slug === slug);

export function accountsFromRows(rows) {
  const byUser = new Map();
  rows.forEach((r) => {
    if (!byUser.has(r.username)) {
      byUser.set(r.username, {
        username: r.username,
        name: r.display_name || r.username,
        active: r.active,
        lastSignIn: r.last_sign_in,
        grants: {},
      });
    }
    const account = byUser.get(r.username);
    // Defensive: a user should hold one assignable role per project, but role
    // membership is additive, so keep the strongest if the data ever disagrees.
    if (rank(r.role) > rank(account.grants[r.project])) account.grants[r.project] = r.role;
  });
  return [...byUser.values()];
}

export const accessFor = (account, slug) => account.grants[slug] || null;
export const projectCount = (account) => Object.keys(account.grants).length;
export const highestRole = (account) =>
  Object.values(account.grants).reduce((best, r) => (rank(r) > rank(best) ? r : best), null);

export function statusOf(account) {
  if (!account.active) return 'disabled';
  return account.lastSignIn ? 'active' : 'pending';
}

export function formatSignIn(iso) {
  if (!iso) return 'Never';
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}
```

- [ ] **Step 5: Write `ui.js`**

```javascript
/* Shared render helpers. The role chip is a grey density ramp: the heavier the
   fill, the more the role can do, so the matrix reads without colour-coding
   text (which the design system forbids). */
import { ROLE_LABEL, statusOf, formatSignIn } from './state.js';

export const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const initials = (name) => name.split(/[\s.]+/).filter(Boolean).map((p) => p[0]).join('').slice(0, 2).toUpperCase();

export const roleChip = (role) =>
  role ? `<span class="role role-${role}">${ROLE_LABEL[role]}</span>` : '<span class="role role-none">—</span>';

export function statusCell(account) {
  const status = statusOf(account);
  const label = { active: 'Active', disabled: 'Disabled', pending: 'Never signed in' }[status];
  return `<span class="status ${status}"><span class="status-dot"></span>${label}</span>`;
}

export const signInLabel = formatSignIn;

export function closePopover() {
  document.querySelectorAll('.popover').forEach((p) => p.remove());
}

let toastTimer = null;
export function toast(message, undo) {
  const el = document.getElementById('toast');
  document.getElementById('toast-text').textContent = message;
  const undoButton = document.getElementById('toast-undo');
  undoButton.hidden = !undo;
  undoButton.onclick = () => { if (undo) undo(); el.classList.remove('show'); };
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
}
```

- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -v`
Expected: the two new tests PASS.

- [ ] **Step 7: Commit**

```bash
git add pipeline/portal/static/js/api.js pipeline/portal/static/js/state.js pipeline/portal/static/js/ui.js tests/test_portal_frontend.py
git commit -m "feat(portal): add the API client, pivot state and shared render helpers"
```

---

### Task 7: Project tiles

**Files:**
- Create: `pipeline/portal/static/js/home.js`
- Test: `tests/test_portal_frontend.py`

**Interfaces:**
- Consumes: `fetchProjects()` (Task 6), `state`, `roleChip`, `esc`.
- Produces: `loadHome()` (async, fills `state.projects`) and `renderHome()`, both called from `js/app.js`.

- [ ] **Step 1: Write the failing test**

```python
    def test_tiles_show_purpose_and_role_not_the_url(self):
        home = (JS / "home.js").read_text(encoding="utf-8")
        self.assertIn("purpose", home)
        self.assertIn("roleChip", home)
        self.assertIn('target="_blank"', home)
        self.assertIn('rel="noopener"', home)
        # The shipped portal printed the raw URL as the tile subtitle.
        self.assertNotIn("tile-url", home)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -k tiles_show -v`
Expected: FAIL with `FileNotFoundError` for `js/home.js`.

- [ ] **Step 3: Write `home.js`**

```javascript
/* Project tiles. target="_blank" so the workspace opens in its own tab and the
   portal stays put; rel="noopener" severs the reverse window handle. */
import { fetchProjects } from './api.js';
import { state } from './state.js';
import { esc, roleChip } from './ui.js';

export async function loadHome() {
  state.projects = await fetchProjects();
}

export function renderHome() {
  const tiles = document.getElementById('project-tiles');
  if (!state.projects.length) {
    tiles.innerHTML =
      '<div class="empty"><p class="empty-title">No projects yet.</p>' +
      '<p class="empty-text">You do not have access to any project. Ask a portal administrator.</p></div>';
    return;
  }
  tiles.innerHTML = state.projects.map((p) => `
    <a class="tile" href="${esc(p.url)}" target="_blank" rel="noopener">
      <div class="tile-name">${esc(p.name)}</div>
      <div class="tile-purpose">${esc(p.purpose || '')}</div>
      <div class="tile-foot">${roleChip(p.role)}<span class="tile-open">Open →</span></div>
    </a>`).join('');
}
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/portal/static/js/home.js tests/test_portal_frontend.py
git commit -m "feat(portal): tiles carry purpose and your role instead of a raw URL"
```

---

### Task 8: Users table with search, filter and sort

**Files:**
- Create: `pipeline/portal/static/js/users.js`
- Test: `tests/test_portal_frontend.py`

**Interfaces:**
- Consumes: `fetchUsers()`, `accountsFromRows`, `highestRole`, `projectCount`, `statusOf`, `roleChip`, `statusCell`, `signInLabel`, `openDrawer` (Task 10).
- Produces: `loadUsers()` (async, fills `state.users` with accounts), `renderUsers()`, `wireUsers()`.

- [ ] **Step 1: Write the failing test**

```python
    def test_users_table_can_search_filter_and_sort(self):
        users = (JS / "users.js").read_text(encoding="utf-8")
        for hook in ("user-search", "user-filter-role", "user-filter-status", "user-count", "user-empty"):
            self.assertIn(hook, users)
        self.assertIn("aria-sort", users)
        self.assertIn("openDrawer", users)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -k users_table -v`
Expected: FAIL with `FileNotFoundError` for `js/users.js`.

- [ ] **Step 3: Write `users.js`**

```javascript
/* The shipped portal had no search, no filter and no sort — fine at six users,
   unusable at sixty. Filtering is client-side: the endpoint deliberately
   returns the full set, matching the rest of this local-first deployment. */
import { fetchUsers } from './api.js';
import { state, accountsFromRows, highestRole, projectCount, statusOf, rank } from './state.js';
import { esc, roleChip, statusCell, signInLabel } from './ui.js';
import { openDrawer } from './drawer.js';

export async function loadUsers() {
  state.users = accountsFromRows(await fetchUsers());
}

function filtered() {
  const query = document.getElementById('user-search').value.trim().toLowerCase();
  const role = document.getElementById('user-filter-role').value;
  const status = document.getElementById('user-filter-status').value;
  const list = state.users.filter((u) => {
    if (query && !(u.name.toLowerCase().includes(query) || u.username.toLowerCase().includes(query))) return false;
    if (status && statusOf(u) !== status) return false;
    if (role && !Object.values(u.grants).includes(role)) return false;
    return true;
  });
  const { key, dir } = state.userSort;
  list.sort((a, b) => {
    if (key === 'projects') return (projectCount(a) - projectCount(b)) * dir;
    if (key === 'role') return (rank(highestRole(a)) - rank(highestRole(b))) * dir;
    return a.name.localeCompare(b.name) * dir;
  });
  return list;
}

export function renderUsers() {
  const list = filtered();
  document.getElementById('user-count').textContent = `${list.length} of ${state.users.length} users`;
  document.getElementById('user-empty').hidden = list.length > 0;
  document.getElementById('user-rows').innerHTML = list.map((u) => `
    <tr${u.active ? '' : ' class="is-disabled"'}>
      <td>
        <button class="name-btn" type="button" data-open="${esc(u.username)}">${esc(u.name)}</button>
        <div class="cell-sub">${esc(u.username)}</div>
      </td>
      <td>${roleChip(highestRole(u))}</td>
      <td class="num">${projectCount(u)}</td>
      <td>${statusCell(u)}</td>
      <td class="num">${esc(signInLabel(u.lastSignIn))}</td>
      <td class="cell-actions"><button class="btn sm" type="button" data-open="${esc(u.username)}">Manage</button></td>
    </tr>`).join('');
  document.querySelectorAll('#user-rows [data-open]').forEach((el) => {
    el.onclick = () => openDrawer(el.dataset.open);
  });
}

export function wireUsers() {
  ['user-search', 'user-filter-role', 'user-filter-status'].forEach((id) => {
    document.getElementById(id).oninput = renderUsers;
  });
  document.getElementById('user-clear-filters').onclick = () => {
    ['user-search', 'user-filter-role', 'user-filter-status'].forEach((id) => {
      document.getElementById(id).value = '';
    });
    renderUsers();
  };
  document.querySelectorAll('#user-table th.sortable').forEach((th) => {
    th.onclick = () => {
      const key = th.dataset.sort;
      state.userSort = { key, dir: state.userSort.key === key ? -state.userSort.dir : 1 };
      document.querySelectorAll('#user-table th').forEach((h) => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', state.userSort.dir === 1 ? 'ascending' : 'descending');
      th.querySelector('.sort-arrow').textContent = state.userSort.dir === 1 ? '↑' : '↓';
      renderUsers();
    };
  });
}
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/portal/static/js/users.js tests/test_portal_frontend.py
git commit -m "feat(portal): users table gains search, filters, sorting and a manage action"
```

---

### Task 9: Access matrix, role popover and CSV export

The headline screen — and the cheapest, because `portal.users` already returns exactly the rows it needs.

**Files:**
- Create: `pipeline/portal/static/js/matrix.js`
- Test: `tests/test_portal_frontend.py`

**Interfaces:**
- Consumes: `state.projects`, `state.users`, `setRole`, `revokeRole`, `accessFor`, `roleChip`, `toast`, `closePopover`, `openDrawer`.
- Produces: `renderMatrix()`, `wireMatrix()`.

- [ ] **Step 1: Write the failing test**

```python
    def test_matrix_pivots_and_offers_no_access(self):
        matrix = (JS / "matrix.js").read_text(encoding="utf-8")
        self.assertIn("matrix-rows", matrix)
        self.assertIn("matrix-head", matrix)
        self.assertIn("revokeRole", matrix)     # emptying a cell
        self.assertIn("setRole", matrix)
        self.assertIn("No access", matrix)
        self.assertIn("Export as CSV", matrix)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -k matrix_pivots -v`
Expected: FAIL with `FileNotFoundError` for `js/matrix.js`.

- [ ] **Step 3: Write `matrix.js`**

```javascript
/* User x project, one cell per grant. Needs no dedicated endpoint: portal.users
   already returns one row per user x project x role, so this is a pure pivot.
   The chip's fill weight encodes privilege — see the ramp in styles.css. */
import { setRole, revokeRole } from './api.js';
import { state, ROLES, ROLE_LABEL, accessFor, project } from './state.js';
import { esc, roleChip, toast, closePopover } from './ui.js';
import { openDrawer } from './drawer.js';
import { loadUsers } from './users.js';

function visible() {
  const query = document.getElementById('matrix-search').value.trim().toLowerCase();
  const only = document.getElementById('matrix-filter-project').value;
  return {
    columns: only ? state.projects.filter((p) => p.slug === only) : state.projects,
    rows: state.users.filter(
      (u) => !query || u.name.toLowerCase().includes(query) || u.username.toLowerCase().includes(query),
    ),
  };
}

export function renderMatrix() {
  const { columns, rows } = visible();
  document.getElementById('matrix-count').textContent =
    `${rows.length} users · ${columns.length} projects`;

  document.getElementById('matrix-head').innerHTML =
    '<th class="cell-user">User</th>' +
    columns.map((p) => {
      const withAccess = rows.filter((u) => accessFor(u, p.slug)).length;
      return `<th class="col-project">${esc(p.name)}<small>${withAccess} with access</small></th>`;
    }).join('');

  document.getElementById('matrix-rows').innerHTML = rows.map((u) => `
    <tr${u.active ? '' : ' class="is-disabled"'}>
      <td class="cell-user">
        <button class="name-btn" type="button" data-open="${esc(u.username)}">${esc(u.name)}</button>
        <div class="cell-sub">${esc(u.username)}${u.active ? '' : ' · disabled'}</div>
      </td>
      ${columns.map((p) => {
        const role = accessFor(u, p.slug);
        return `<td class="cell-role">
          <button class="cell-btn" type="button" data-cell="${esc(u.username)}:${esc(p.slug)}"
                  aria-label="${esc(u.name)} on ${esc(p.name)}: ${role ? ROLE_LABEL[role] : 'no access'}">
            ${roleChip(role)}
          </button></td>`;
      }).join('')}
    </tr>`).join('');

  document.querySelectorAll('#matrix-rows [data-open]').forEach((el) => {
    el.onclick = () => openDrawer(el.dataset.open);
  });
  document.querySelectorAll('#matrix-rows [data-cell]').forEach((el) => {
    el.onclick = (event) => { event.stopPropagation(); openRolePopover(el); };
  });
}

function openRolePopover(anchor) {
  closePopover();
  const [username, slug] = anchor.dataset.cell.split(':');
  const account = state.users.find((u) => u.username === username);
  const current = accessFor(account, slug);

  const popover = document.createElement('div');
  popover.className = 'popover';
  popover.innerHTML =
    `<div class="popover-title">${esc(project(slug).name)}</div>` +
    [...ROLES].reverse().map((r) =>
      `<button class="popover-option" type="button" role="menuitemradio" aria-checked="${current === r}" data-role="${r}">
         <span class="tick">${current === r ? '✓' : ''}</span>${ROLE_LABEL[r]}</button>`).join('') +
    '<div class="popover-sep"></div>' +
    `<button class="popover-option" type="button" role="menuitemradio" aria-checked="${!current}" data-role="">
       <span class="tick">${!current ? '✓' : ''}</span>No access</button>`;

  document.body.appendChild(popover);
  const box = anchor.getBoundingClientRect();
  popover.style.top = `${window.scrollY + box.bottom + 4}px`;
  popover.style.left = `${Math.min(
    window.scrollX + box.left,
    window.scrollX + document.documentElement.clientWidth - popover.offsetWidth - 12,
  )}px`;

  popover.querySelectorAll('[data-role]').forEach((option) => {
    option.onclick = async () => {
      const next = option.dataset.role;
      closePopover();
      const result = next
        ? await setRole(username, slug, next)
        : await revokeRole(username, slug);
      if (!result.ok) { toast(result.message); return; }
      await loadUsers();
      renderMatrix();
      toast(next
        ? `${account.name} is now ${ROLE_LABEL[next]} on ${project(slug).name}.`
        : `${account.name} lost access to ${project(slug).name}.`);
    };
  });
  popover.querySelector('.popover-option').focus();
}

function exportCsv() {
  const { columns, rows } = visible();
  const cell = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const lines = [['Username', 'Name', ...columns.map((p) => p.name)].map(cell).join(',')];
  rows.forEach((u) => {
    lines.push([u.username, u.name, ...columns.map((p) => accessFor(u, p.slug) || '')].map(cell).join(','));
  });
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'cplan-access-matrix.csv';
  link.click();
  URL.revokeObjectURL(url);
}

export function wireMatrix() {
  document.getElementById('matrix-filter-project').innerHTML =
    '<option value="">All projects</option>';
  ['matrix-search', 'matrix-filter-project'].forEach((id) => {
    document.getElementById(id).oninput = renderMatrix;
  });
  document.getElementById('matrix-export').onclick = exportCsv;   // labelled "Export as CSV"
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.popover') && !event.target.closest('[data-cell]')) closePopover();
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closePopover(); });
}
```

Note: `renderMatrix()` must also refresh the project filter's options once `state.projects` is loaded. Add this at the top of `renderMatrix`, before `visible()` is called:

```javascript
  const filter = document.getElementById('matrix-filter-project');
  if (filter.options.length <= 1 && state.projects.length) {
    filter.innerHTML = '<option value="">All projects</option>' +
      state.projects.map((p) => `<option value="${esc(p.slug)}">${esc(p.name)}</option>`).join('');
  }
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/portal/static/js/matrix.js tests/test_portal_frontend.py
git commit -m "feat(portal): add the user x project access matrix with inline role changes"
```

---

### Task 10: Person drawer

**Files:**
- Create: `pipeline/portal/static/js/drawer.js`
- Test: `tests/test_portal_frontend.py`

**Interfaces:**
- Consumes: `state.users`, `state.projects`, `resetPassword`, `setActive`, `revokeRole`, `accessFor`, `roleChip`, `statusCell`, `toast`.
- Produces: `openDrawer(username)`, `closeDrawer()`, `wireDrawer()`.

- [ ] **Step 1: Write the failing test**

```python
    def test_drawer_shows_access_and_guards_destructive_actions(self):
        drawer = (JS / "drawer.js").read_text(encoding="utf-8")
        self.assertIn("openDrawer", drawer)
        self.assertIn("resetPassword", drawer)
        self.assertIn("setActive", drawer)
        self.assertIn("window.confirm", drawer)   # destructive steps are confirmed
        self.assertIn("Danger zone", drawer)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -k drawer_shows -v`
Expected: FAIL with `FileNotFoundError` for `js/drawer.js`.

- [ ] **Step 3: Write `drawer.js`**

```javascript
/* One person's account and access in one place. Destructive steps confirm
   first: unlike a role change, disabling an account and removing every grant
   are not something a toast-undo should be the only guard for. */
import { resetPassword, setActive, revokeRole } from './api.js';
import { state, accessFor } from './state.js';
import { esc, initials, roleChip, statusCell, signInLabel, toast } from './ui.js';

function generatePassword() {
  const words = ['anchor', 'harbour', 'lantern', 'meadow', 'compass', 'basalt', 'willow', 'quarry'];
  const pick = () => words[Math.floor(Math.random() * words.length)];
  return `${pick()}-${pick()}-${Math.floor(10 + Math.random() * 89)}`;
}

export function openDrawer(username) {
  const account = state.users.find((u) => u.username === username);
  if (!account) return;

  document.getElementById('drawer-avatar').textContent = initials(account.name);
  document.getElementById('drawer-name').textContent = account.name;
  document.getElementById('drawer-meta').textContent =
    `${account.username} · last sign-in ${signInLabel(account.lastSignIn)}`;

  document.getElementById('drawer-body').innerHTML = `
    <div class="drawer-section">
      <h3>Account</h3>
      <div class="access-row">
        <div><div class="access-project">Status</div>
             <div class="access-note">${account.active ? 'Can sign in' : 'Cannot sign in'}</div></div>
        ${statusCell(account)}
      </div>
      <div class="access-row">
        <div><div class="access-project">Password</div>
             <div class="access-note">Set by an administrator</div></div>
        <button class="btn sm" type="button" data-act="reset">Reset password</button>
      </div>
    </div>

    <div class="drawer-section">
      <h3>Project access</h3>
      ${state.projects.map((p) => {
        const role = accessFor(account, p.slug);
        return `<div class="access-row">
          <div><div class="access-project">${esc(p.name)}</div>
               <div class="access-note">${role ? 'Direct grant' : 'No access'}</div></div>
          ${roleChip(role)}
        </div>`;
      }).join('')}
    </div>

    <div class="drawer-section">
      <h3>Danger zone</h3>
      <div class="drawer-danger">
        <button class="btn danger" type="button" data-act="${account.active ? 'disable' : 'enable'}">
          ${account.active ? 'Disable account' : 'Enable account'}</button>
        <button class="btn danger" type="button" data-act="remove">Remove all access</button>
      </div>
      <p class="footnote" style="margin-top:12px">Disabling keeps the account and its grants but blocks sign-in.
      Nothing this person created is deleted.</p>
    </div>`;

  document.getElementById('drawer-body').querySelectorAll('[data-act]').forEach((button) => {
    button.onclick = () => runAction(button.dataset.act, account);
  });
  document.getElementById('person-drawer').classList.add('open');
}

async function runAction(action, account) {
  const { loadUsers, renderUsers } = await import('./users.js');
  const { renderMatrix } = await import('./matrix.js');
  const refresh = async () => {
    await loadUsers();
    renderUsers();
    renderMatrix();
    openDrawer(account.username);
  };

  if (action === 'reset') {
    const password = generatePassword();
    if (!window.confirm(`Reset ${account.name}'s password to:\n\n${password}\n\nPass it on yourself — the portal sends no email.`)) return;
    const result = await resetPassword(account.username, password);
    toast(result.ok ? `Password reset for ${account.name}.` : result.message);
    return;
  }

  if (action === 'disable' || action === 'enable') {
    const disabling = action === 'disable';
    if (disabling && !window.confirm(`Disable ${account.name}? They will not be able to sign in.`)) return;
    const result = await setActive(account.username, !disabling);
    if (!result.ok) { toast(result.message); return; }
    await refresh();
    toast(`${account.name} ${disabling ? 'can no longer sign in' : 'can sign in again'}.`);
    return;
  }

  if (action === 'remove') {
    const slugs = Object.keys(account.grants);
    if (!slugs.length) { toast(`${account.name} has no access to remove.`); return; }
    if (!window.confirm(`Remove ${account.name} from all ${slugs.length} project(s)? The account itself stays.`)) return;
    for (const slug of slugs) {
      const result = await revokeRole(account.username, slug);
      if (!result.ok) { toast(result.message); return; }
    }
    await refresh();
    toast(`All access removed for ${account.name}.`);
  }
}

export function closeDrawer() {
  document.getElementById('person-drawer').classList.remove('open');
}

export function wireDrawer() {
  document.querySelectorAll('[data-close-drawer]').forEach((b) => { b.onclick = closeDrawer; });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDrawer(); });
}
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/portal/static/js/drawer.js tests/test_portal_frontend.py
git commit -m "feat(portal): add the person drawer with confirmed destructive actions"
```

---

### Task 11: Invite modal, and retire `window.prompt`

The shipped portal collects a new password through a browser `window.prompt`. Replace the whole creation flow with the designed modal.

**Files:**
- Create: `pipeline/portal/static/js/invite.js`
- Test: `tests/test_portal_frontend.py`
- Modify: `README.md`, `pipeline/api/README.md` (portal section)

**Interfaces:**
- Consumes: `createUser`, `state.projects`, `ROLES`, `ROLE_LABEL`, `ROLE_DESC`, `toast`.
- Produces: `openInvite()`, `closeInvite()`, `wireInvite()`.

- [ ] **Step 1: Write the failing test**

```python
    def test_invite_modal_replaces_the_browser_prompt(self):
        invite = (JS / "invite.js").read_text(encoding="utf-8")
        self.assertIn("createUser", invite)
        self.assertIn("ROLE_DESC", invite)      # each role explained in a sentence
        self.assertIn("iv-generate", invite)    # generated password
        for module in ("api.js", "state.js", "ui.js", "home.js", "users.js", "matrix.js", "drawer.js", "invite.js", "app.js"):
            source = (JS / module).read_text(encoding="utf-8")
            self.assertNotIn("window.prompt", source, f"{module} still collects input via window.prompt")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py -k invite_modal -v`
Expected: FAIL with `FileNotFoundError` for `js/invite.js`.

- [ ] **Step 3: Write `invite.js`**

```javascript
/* Account creation. The password is generated and shown once — the portal sends
   no email, so the admin passes it on. The role picker explains each role in a
   sentence rather than offering four bare words in a dropdown. */
import { createUser } from './api.js';
import { state, ROLES, ROLE_LABEL, ROLE_DESC, project } from './state.js';
import { esc, toast } from './ui.js';

function generatePassword() {
  const words = ['anchor', 'harbour', 'lantern', 'meadow', 'compass', 'basalt', 'willow', 'quarry'];
  const pick = () => words[Math.floor(Math.random() * words.length)];
  return `${pick()}-${pick()}-${Math.floor(10 + Math.random() * 89)}`;
}

export function openInvite() {
  document.getElementById('iv-username').value = '';
  document.getElementById('iv-password').value = generatePassword();
  document.getElementById('iv-error').hidden = true;
  document.getElementById('iv-project').innerHTML =
    state.projects.map((p) => `<option value="${esc(p.slug)}">${esc(p.name)}</option>`).join('');
  document.getElementById('iv-roles').innerHTML = [...ROLES].reverse().map((r, index) => `
    <label class="role-choice">
      <input type="radio" name="iv-role" value="${r}"${index === ROLES.length - 1 ? ' checked' : ''} />
      <span><span class="rc-name">${ROLE_LABEL[r]}</span><span class="rc-desc">${esc(ROLE_DESC[r])}</span></span>
    </label>`).join('');
  document.getElementById('invite-modal').classList.add('open');
  document.getElementById('iv-username').focus();
}

export function closeInvite() {
  document.getElementById('invite-modal').classList.remove('open');
}

export function wireInvite() {
  document.getElementById('invite-open').onclick = openInvite;
  document.getElementById('iv-generate').onclick = () => {
    document.getElementById('iv-password').value = generatePassword();
  };
  document.querySelectorAll('[data-close-modal]').forEach((b) => { b.onclick = closeInvite; });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeInvite(); });

  document.getElementById('invite-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const error = document.getElementById('iv-error');
    const username = document.getElementById('iv-username').value.trim();
    if (!username) {
      error.textContent = 'Choose a username.';
      error.hidden = false;
      return;
    }
    const slug = document.getElementById('iv-project').value;
    const role = document.querySelector('input[name="iv-role"]:checked').value;
    const result = await createUser({
      username,
      password: document.getElementById('iv-password').value,
      project: slug,
      role,
    });
    if (!result.ok) {
      error.textContent = result.message;
      error.hidden = false;
      return;
    }
    closeInvite();
    const { loadUsers, renderUsers } = await import('./users.js');
    const { renderMatrix } = await import('./matrix.js');
    await loadUsers();
    renderUsers();
    renderMatrix();
    toast(`${username} created as ${ROLE_LABEL[role]} on ${project(slug).name}.`);
  });
}
```

- [ ] **Step 4: Delete the superseded frontend**

The old single-file frontend is fully replaced. Per the non-destructive rule, move rather than delete:

```bash
mkdir -p pipeline/portal/_to_delete
git mv pipeline/portal/static/app.js pipeline/portal/_to_delete/app.js
```

`index.html` and `styles.css` were overwritten in Tasks 4–5; their previous contents remain in git history.

- [ ] **Step 5: Update the documentation**

In `pipeline/api/README.md`, in the `### Portal` section, replace the sentence beginning "**What the portal does:**" with:

```markdown
**What the portal does:** an admin manages users entirely in the browser — invite,
change role per project, reset password, enable/disable — without touching the CLI.
The access matrix shows every user against every registered project, and a cell can
be set to any role or emptied. The portal service itself holds no DDL rights; every
change is routed through the `portal.*` `SECURITY DEFINER` functions above, so a
non-admin caller is rejected by PostgreSQL's own privilege check (SQLSTATE `42501`)
before any change happens, surfaced to the browser as `403`.
```

In `README.md`, replace the portal line with:

```markdown
A portal (landing page with project tiles, a users list and a user × project access
matrix) is available — see [`pipeline/api/README.md`](pipeline/api/README.md#portal).
```

- [ ] **Step 6: Run the full portal test set**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_portal_frontend.py tests/test_portal_api.py tests/test_setup_portal.py tests/test_start_portal.py -v`
Expected: PASS.

- [ ] **Step 7: Verify in a browser**

```bash
PYTHONPATH=. .venv/bin/python pipeline/scripts/start_portal.py
```

Open <http://127.0.0.1:8781/> and confirm by hand: sign in; tiles show purpose and your role; the users table searches, filters and sorts; a matrix cell opens the popover, changes a role, and can be set to No access; the drawer opens from both tables; invite creates an account and it appears in both views; sign out returns to the sign-in screen.

- [ ] **Step 8: Check no brand name reached the repository**

```bash
# The literal is assembled at runtime so this plan does not itself become a hit.
BRAND=$(printf 'u%s' 'bs')
git grep -Inwi "$BRAND" -- . ':!*.lock' ':!pnpm-lock.yaml'
git log --oneline -12 | grep -iw "$BRAND"
```

Expected: no output from either.

- [ ] **Step 9: Commit**

```bash
git add -A pipeline/portal README.md pipeline/api/README.md tests/test_portal_frontend.py
git commit -m "feat(portal): replace the browser prompt with a designed invite flow"
```

---

## Out of scope — follow-up plans

- **Phase 2 — Groups.** Model a group as a PostgreSQL role granted the project group roles, with users granted the group role. Union semantics (decided): effective access is the strongest grant from any source, and a direct grant cannot undercut a group. Requires `portal.users` to distinguish direct from inherited, the pseudo-user filter in `_USERS_VIEW` to exclude group roles, and the `role-inherited` bronze strip in the matrix.
- **Phase 3 — Access audit log.** An append-only `portal.audit` table written inside each `portal.*` function, plus the Activity log screen.
- **Phase 4 — Per-project admin scoping.** `EXECUTE` on the user-management functions is granted to `cplan_admin` project-wide, so today every admin is a portal-wide admin. Each function would check the caller's admin membership against the target project.
- ~~**Security follow-up.** `portal.create_user` and `portal.reset_password` interpolate the password with `format(... %L)`. With statement logging enabled, the cleartext password reaches the PostgreSQL log. Worth closing before the portal is used on a shared instance.~~ **Closed 2026-08-05.** Both functions, and `setup_roles`' own `CREATE ROLE`/`ALTER ROLE` DDL, now receive a SCRAM-SHA-256 verifier computed in Python (`pipeline/api/scram.py`), so no cleartext password is ever part of a SQL statement; the two functions refuse anything that is not a verifier, so the leak cannot return through a caller that forgets. See "Passwords never reach the server log" in `pipeline/api/README.md` and `tests/test_scram.py`.

## Completed 2026-08-05 — open items found along the way

All eleven tasks are implemented, reviewed and on `main`. These surfaced during review and are deliberately not fixed here:

- **The bootstrap admin can never be revoked through the portal.** `setup_roles.create_user` (the CLI that creates the very first admin) grants the group role as the connecting superuser, not as `portal_owner`. PostgreSQL's `REVOKE` honours the grantor, so the `portal.*` functions — which run as `portal_owner` — cannot undo it. That account sits permanently outside the access administration the portal provides. Fix by having the bootstrap path grant as `portal_owner`, and add a one-off repair for existing installations.
- **The login has no rate limit and no lockout.** Nothing in `pipeline/portal/app.py` or `pipeline/api/auth.py` bounds failed attempts. This is what made the weak generated password a real risk rather than a theoretical one; the password is now ~44 bits, but the missing limit stands on its own.
- **`pg_has_role` is transitive, the guards are not.** Role reporting and PostgreSQL's own `EXECUTE` check use `pg_has_role`, while the last-admin guards and the revoke loops read `pg_auth_members` directly. With no groups this is unreachable. When Phase 2 adds groups, demoting a transitively-granted admin would report success without taking effect — fix the guards before groups land, not after.
- **`create_user` cannot be reached for a second project.** `portal_owner` holds `ADMIN OPTION` only on the roles `setup_roles` grants it, which today means one project. Registering a second project requires extending that grant, or every call against it fails with `42501` surfaced as `403`.
