# Portal grant authority: bootstrap admin manageability and second-project support

Closes the two open items recorded in
`docs/superpowers/plans/2026-08-04-portal-redesign-phase-1.md` ("Completed
2026-08-05 — open items found along the way").

## The gap

PostgreSQL's `REVOKE ROLE` honours the *grantor* recorded on the specific
membership row in `pg_auth_members`, not just "does the caller hold ADMIN
OPTION on the role" — a role can hold ADMIN OPTION and still be unable to
revoke a membership someone else granted. Every `portal.*` user-management
function (`create_user`, `set_project_role`, `revoke_project_role`,
`set_active`, …) is `SECURITY DEFINER` and executes as `portal_owner`.

`setup_roles.create_user` — the command-line path that creates the very
first admin, before the portal exists at all — issues its `GRANT` while
connected as the superuser. That superuser is therefore the grantor. The
result: `portal_owner` can never revoke, demote, or remove that account
through the portal. Confirmed directly against a real PostgreSQL 17 server
during this work: a role holding ADMIN OPTION on a group (but not the
grantor of a specific membership) does not even get an error on
`REVOKE … FROM …` — it produces a `WARNING` and silently changes nothing.
That is why the symptom is invisible until an operator tries to hand over
administration and finds the old admin cannot be stood down.

Separately: `apply_portal` only ever granted `portal_owner` `ADMIN OPTION`
on CPLAN's own four group roles (`_ASSIGNABLE_GROUPS`, keyed off
`setup_roles.ASSIGNABLE_ROLES`). `register_project` adds a row to
`portal.projects` but never extended that authority to the new project's
own four group roles, so every `portal.create_user` /
`set_project_role` / `revoke_project_role` call against a second project
failed Postgres's own privilege check (`42501`), surfacing through the API
as a 403 that looks like the caller lacking permission rather than the
installation being incomplete.

## Approach chosen, and what was rejected

Three options were on the table for making a membership's grantor correct:

1. **`GRANT … GRANTED BY portal_owner`** at the point `setup_roles.create_user`
   issues the grant.
2. **Create `portal_owner` earlier**, inside `setup_roles.apply_roles`, so it
   exists (and already holds ADMIN OPTION) by the time `create_user` runs.
3. **Have `apply_portal` repair** any membership it finds with the wrong
   grantor, on every run.

Option 1 alone doesn't work at all: `GRANT … GRANTED BY X` requires `X` to
already hold ADMIN OPTION on the role being granted (verified experimentally
— a superuser cannot simply declare an arbitrary grantor). That drags in
option 2 as a prerequisite. Option 2 was rejected because it inverts the
module layering: `setup_roles.py` today has no notion of `portal_owner` or
the portal at all — `setup_portal.py` is the layer built on top of it, not
the reverse. Teaching `setup_roles.py` about `portal_owner` (and duplicating
the "ensure it exists and holds ADMIN OPTION" logic that `apply_portal`
already needs for its own reasons) would only fix the *CPLAN* bootstrap
admin, not a second project's first admin created the same ad hoc way — a
generalized fix has to live in `setup_portal.py` regardless, since a
project's role names are only known at runtime through `role_prefix`.

**Chosen: option 3, generalized.** `apply_portal` already runs once, always
after `setup_roles` has created the first admin (the README's documented
bootstrap order), and it must already be idempotent and safe to re-run for
unrelated reasons (schema/function upgrades). Reusing exactly that mechanism
means points 1 and 2 of the task share one code path instead of two that
could drift apart: any membership on any registered project's assignable
group roles that isn't attributed to `portal_owner` — whether from the very
first bootstrap, a later `create_user` bootstrap for a second project, or an
old installation created before this fix shipped — gets corrected the same
way, every time `apply_portal` runs. No change to `setup_roles.py` was
needed at all.

## How the repair works

`pipeline/api/setup_portal.py` gained three helpers, all operating per
project (`role_prefix`), used from `apply_portal` and `register_project`:

- `_existing_group_roles(connection, role_prefix)` — the subset of
  `<prefix>_{viewer,contributor,editor,admin}` that actually exist. A
  project can be registered before its group roles are created (the
  documented two-step process), so every caller tolerates some or all of
  the four being absent rather than erroring.
- `_grant_admin_option(connection, role_prefix)` — `GRANT <group> TO
  portal_owner WITH ADMIN OPTION` for each role that exists. Idempotent
  (re-granting ADMIN OPTION already held is a no-op) and a no-op for roles
  that don't exist yet.
- `_repair_grantor(connection, role_prefix)` — for each existing group role,
  finds every member whose membership was granted by anyone other than
  `portal_owner`, and re-attributes it: `REVOKE <group> FROM <member>` then
  `GRANT <group> TO <member> GRANTED BY portal_owner`. Excludes the project's
  own group/service roles (its four assignable roles plus `<prefix>_sync`,
  and the cluster-wide `cplan_authenticator`/`portal_owner`) **by name**, so
  it never touches the viewer⊂contributor⊂editor⊂admin hierarchy itself.
  This is deliberately not a `u.rolcanlogin` filter: that column is
  `portal.set_active`'s own active/disabled flag, not "is this a real
  account" — a disabled account is still a fully manageable portal account,
  and typically the one most likely to need this repair (someone disabled
  rather than deleted after leaving). An earlier revision filtered on
  `rolcanlogin` and so silently skipped disabled accounts forever, since
  `apply_portal` is not a startup path that would come back around for them
  on its own; `tests/test_portal_grant_authority.py` covers that case
  directly.

`apply_portal` now loops over every row in `portal.projects` (after the
CPLAN seed upsert, so a fresh database includes CPLAN itself) and calls
`_grant_admin_option` then `_repair_grantor` for each — order matters, since
the repair's re-grant needs `portal_owner` to already hold ADMIN OPTION on
the role it names itself as `GRANTED BY`. This replaced the old hardcoded
loop over CPLAN's four roles.

**Safety of the repair itself:** both the REVOKE and the re-GRANT run inside
`apply_portal`'s single enclosing transaction (`with engine.begin() as c:`),
so a failure partway through — the REVOKE lands, the GRANT does not — rolls
the whole `apply_portal` call back rather than ever persisting a membership
that was revoked but never re-granted. A membership already correctly
attributed to `portal_owner` fails the `grantor <> portal_owner` filter and
is never touched, so running `apply_portal` against a database where nothing
needs repairing is a genuine no-op (verified: ran three times in a row
against a freshly bootstrapped database with no behavioural or state
change on the second and third runs).

`register_project` also calls `_grant_admin_option` directly (not the
repair — nothing could have gone wrong yet for a project just being
registered), so a project registered *after* its group roles already exist
works immediately, without waiting for a separate `apply_portal` run. When
the roles don't exist yet (the documented order: register, then create
roles), this is a no-op and `apply_portal`'s per-project sweep is what
closes the gap once they exist — which also covers a project that was
registered before this change existed at all.

## Verifying on an existing installation

Run (or re-run) the one-time setup step — it is safe to execute against a
database that has never needed any of this and against one that does:

```
PYTHONPATH=. .venv/bin/python -m pipeline.api.setup_portal
```

To confirm a specific account's grantor is correct:

```sql
SELECT g.rolname AS group, u.rolname AS member, gr.rolname AS grantor
FROM pg_auth_members m
JOIN pg_roles g  ON g.oid = m.roleid
JOIN pg_roles u  ON u.oid = m.member
JOIN pg_roles gr ON gr.oid = m.grantor
WHERE u.rolname = '<the account>';
```

`grantor` should read `portal_owner` for every row. If it doesn't, run
`setup_portal` again — nothing else is required.

## Testing

New file `tests/test_portal_grant_authority.py` (function-scoped fixture,
one fresh database per test, so each test controls the exact
create_user/apply_portal/register_project ordering it needs):

- `test_bootstrap_admin_can_be_demoted_and_revoked_through_the_portal` — the
  realistic end-to-end flow: bootstrap CLI creates the first admin,
  `apply_portal` runs once, a second admin (created normally through the
  portal) demotes and then revokes the bootstrap admin's role.
- `test_apply_portal_repairs_a_superuser_granted_membership` — the repair in
  isolation: an "existing installation" gets a superuser-granted membership,
  `apply_portal` runs, and the membership becomes directly revocable by
  `portal_owner`.
- `test_apply_portal_repairs_a_disabled_accounts_grantor` — the repair must
  reach a *disabled* account too: `rolcanlogin` is `portal.set_active`'s own
  active/disabled flag, not "is this a real account," and a disabled account
  is still fully manageable through the portal. Builds the same
  superuser-granted membership, disables it via the exact `ALTER ROLE ...
  NOLOGIN` statement `portal.set_active` issues (via
  `setup_roles.set_user_active`, not the `portal.set_active` RPC itself --
  that SECURITY DEFINER function's own `ALTER ROLE` always runs as
  `portal_owner`, which would additionally require `portal_owner` to hold
  ADMIN OPTION on the *login role itself*, a distinct PostgreSQL authority
  from the group-role membership this fix repairs, and one a
  superuser-bootstrapped account never grants it -- a real, separate gap
  this task did not set out to fix), runs `apply_portal`, and asserts the
  membership is genuinely revocable via `portal.revoke_project_role`
  afterwards.
- `test_apply_portal_repair_is_a_no_op_when_nothing_needs_repairing` —
  idempotency of the repair itself.
- `test_last_admin_guard_still_blocks_the_repaired_bootstrap_admin` and
  `test_set_active_guard_still_blocks_disabling_the_repaired_bootstrap_admin`
  — regression coverage: the existing last-admin guards
  (`portal._is_last_active_admin`, `set_active`'s own inline guard) still
  fire correctly once the membership they inspect is attributed to
  `portal_owner` instead of the superuser.
- `test_second_project_supports_full_user_lifecycle_via_the_portal` — a
  second project, registered after its group roles already exist, supports
  create / role change / revoke through the portal functions end to end.
- `test_a_project_registered_before_its_roles_exist_works_after_apply_portal`
  — the documented register-then-create-roles order, closed by
  `apply_portal`'s sweep.

All pre-existing portal/RBAC/session test modules
(`test_setup_roles.py`, `test_setup_portal.py`, `test_portal_api.py`,
`test_portal_project_page.py`, `test_portal_frontend.py`,
`test_rbac_matrix.py`, `test_session.py`, `test_api_auth.py`,
`test_views.py`) were re-run unmodified (bar one stale comment in
`test_portal_api.py` that referenced the now-removed
`_ASSIGNABLE_GROUPS` constant) and pass, alongside the full suite
(1420 passed, 5 skipped — pre-existing SQLite/`pgserver` platform gating,
unrelated to this change).

Tests ran against this repository's own `compose.yaml` Postgres service
(`postgres:17-alpine`), started with a throwaway password, `docker compose
up -d db`, `CPLAN_TEST_DATABASE_URL` pointed at it, then torn down with
`docker compose down -v` (volume and network included). `compose.yaml`
itself was not modified.
