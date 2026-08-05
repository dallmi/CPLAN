"""Portal schema, project registry, and SECURITY DEFINER user-management functions.

Runs once as an actual PostgreSQL superuser (like setup_roles), NOT by the
portal service, and NOT merely a CREATEROLE-holding "admin" role short of
superuser: apply_portal's grantor repair (_repair_grantor, below) issues
`GRANT ... GRANTED BY portal_owner`, and PostgreSQL only allows naming an
arbitrary grantor like that when the session role is a superuser, or is
itself a member of the named grantor -- a non-superuser CREATEROLE role
without that membership gets a plain permission-denied error (verified
against a real server), which aborts and rolls back the whole apply_portal
call rather than corrupting anything, but does mean this cannot be delegated
to a lesser admin role the way setup_roles' own DDL can.

The portal service connects as cplan_authenticator, SET ROLEs to the logged-in
user, and calls these functions; EXECUTE is granted only to cplan_admin, so the
membership check is Postgres's own privilege check performed against the real
caller before the SECURITY DEFINER switch. The functions do input validation and
identifier quoting (format %I/%L) as defence in depth. PostgreSQL only.

create_user and reset_password take a SCRAM-SHA-256 *verifier*, never a
cleartext password: the caller hashes it first (pipeline/api/scram.py), because
the DDL these functions build with `format(... %L)` is statement text, and
statement text is logged. They refuse anything that is not a verifier rather
than passing it on, so the leak cannot come back by way of a caller that
forgets -- and a forgetful caller gets a 422 instead of a silent disclosure.
"""

from __future__ import annotations

import argparse

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from pipeline.api.database import create_cplan_engine, database_url_from_environment
from pipeline.api.setup_roles import ASSIGNABLE_ROLES, AUTHENTICATOR, GROUP_ROLES

PORTAL_OWNER = "portal_owner"
PORTAL_RESERVED = frozenset(GROUP_ROLES) | {AUTHENTICATOR, PORTAL_OWNER}

# The four assignable-role suffixes, in the fixed order every FOREACH in this
# module's SQL functions already hardcodes (ASSIGNABLE_ROLES' own key order).
# Combined with a project's role_prefix this names its four group roles --
# used to extend portal_owner's authority to ANY registered project, not just
# CPLAN's (see _grant_admin_option/_repair_grantor below).
_ROLE_SUFFIXES = tuple(ASSIGNABLE_ROLES)

# The fifth, non-assignable suffix that also sits in a project's group-role
# hierarchy (GRANT <prefix>_editor TO <prefix>_sync) but is never something a
# real account holds. Combined with _ROLE_SUFFIXES this names every one of a
# project's own service/group roles -- used by _repair_grantor to exclude the
# hierarchy itself by NAME, the same shape _USERS_VIEW below already uses to
# separate real accounts from group/service roles (rolcanlogin cannot do this:
# it is the portal's own active/disabled flag, not "is this a real account").
_SERVICE_SUFFIXES = _ROLE_SUFFIXES + ("sync",)

# CPLAN seed for the project registry.
_CPLAN = {"slug": "cplan", "name": "CPLAN Studio", "url": "http://127.0.0.1:8780/", "role_prefix": "cplan"}

# The reserved-name array literal the functions guard against, built once here so
# it matches PORTAL_RESERVED exactly.
_RESERVED_SQL_ARRAY = "ARRAY[" + ",".join(f"'{name}'" for name in sorted(PORTAL_RESERVED)) + "]"

# NOTE: every literal '%' below is doubled ('%%') because these strings go
# through psycopg3's cursor.execute(), which always scans for placeholders
# (%s/%b/%t) even when no bind parameters are supplied — a bare '%' (as in
# plpgsql's RAISE '...%', arg or format()'s %I/%L/%s) raises psycopg's own
# ProgrammingError before the DDL ever reaches Postgres. Doubling yields a
# literal '%' once psycopg's client-side parser unescapes it.
#
# NOTE: RAISE EXCEPTION below intentionally does NOT set
# `USING ERRCODE = 'invalid_parameter_value'` (SQLSTATE 22023, class 22 "Data
# Exception"). psycopg/SQLAlchemy map class-22 errors to DataError, not
# ProgrammingError; callers (and the test suite) expect a uniform
# ProgrammingError for every rejected call to these functions, including the
# 42501 insufficient-privilege case. Plain `RAISE EXCEPTION` defaults to
# SQLSTATE P0001 ("raise_exception", class P0 PL/pgSQL Error), which psycopg
# maps to ProgrammingError — matching the 42501 case's exception type without
# changing what is validated or rejected.

# The one thing create_user and reset_password must refuse: a cleartext
# password. Everything they hand to `format(... %L)` becomes statement text,
# and statement text is written to the server log by `log_statement`,
# `log_min_duration_statement` or an audit extension -- so a password that
# arrives here in the clear is a password disclosed to every operator who can
# read a log file. Callers hash it first (pipeline/api/scram.py); this is what
# makes that a contract rather than a convention.
#
# The pattern is PostgreSQL's own storage format, checked structurally rather
# than by prefix alone, because a string that merely *starts* like a verifier
# but does not parse as one is classified PASSWORD_TYPE_PLAINTEXT and hashed as
# though it were the password -- an account with a password nobody knows, and
# no error anywhere. Written with the character classes [$] and [0-9] rather
# than backslash escapes so the pattern carries no backslash at all: the body
# is dollar-quoted, and a backslash's meaning inside a string literal there
# depends on `standard_conforming_strings`.
#
# The message deliberately quotes nothing back. A RAISE with the offending
# value in it would put the cleartext straight into the log this whole change
# exists to keep it out of.
_VERIFIER_PATTERN = "^SCRAM-SHA-256[$][0-9]+:[A-Za-z0-9+/]+=*[$][A-Za-z0-9+/]+=*:[A-Za-z0-9+/]+=*$"
_VERIFIER_GUARD = f"""  IF p_verifier IS NULL OR p_verifier !~ '{_VERIFIER_PATTERN}' THEN
    RAISE EXCEPTION 'password must be a SCRAM-SHA-256 verifier, not cleartext (see pipeline/api/scram.py)';
  END IF;"""

_CREATE_USER_FN = f"""
CREATE OR REPLACE FUNCTION portal.create_user(p_name text, p_verifier text, p_project text, p_role text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_prefix text; v_group text;
BEGIN
  IF p_role NOT IN ('viewer','contributor','editor','admin') THEN
    RAISE EXCEPTION 'unknown role %%', p_role;
  END IF;
  SELECT role_prefix INTO v_prefix FROM portal.projects WHERE slug = p_project;
  IF v_prefix IS NULL THEN
    RAISE EXCEPTION 'unknown project %%', p_project;
  END IF;
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'user %% already exists', p_name;
  END IF;
{_VERIFIER_GUARD}
  v_group := v_prefix || '_' || p_role;
  EXECUTE format('CREATE ROLE %%I LOGIN PASSWORD %%L', p_name, p_verifier);
  EXECUTE format('GRANT %%I TO %%I', v_group, p_name);
  EXECUTE format('GRANT %%I TO {AUTHENTICATOR}', p_name);
END; $fn$;
"""

# set_project_role and revoke_project_role both need to answer the same
# question -- "does p_name hold this project's admin group, and if so, would
# taking it away leave zero OTHER active admins?" -- over the identical
# two-step EXISTS+count query, so it lives once here rather than as two
# near-identical blocks that could quietly drift apart. Only the message each
# caller raises differs, so the predicate stays a boolean and the RAISE
# EXCEPTION stays at each call site rather than being parametrised into the
# helper too.
#
# A plain (non-SECURITY DEFINER) function is enough: both callers are
# themselves SECURITY DEFINER, so by the time either of them calls this, the
# active role is already portal_owner, and portal_owner -- as this function's
# owner -- may always execute it regardless of grants. It is deliberately
# never listed in _FUNCTIONS below, so cplan_admin is never GRANTed EXECUTE
# on it directly: it is an implementation detail shared between two API
# functions, not part of the API surface itself.
#
# set_active's own last-admin guard is NOT built on this helper, despite
# checking the same thing in spirit: it loops over every project a disabled
# account might administer (disabling a login is account-wide, not
# project-scoped, unlike a role change on one project) and it also carries
# its own self-caller check that has no equivalent here. Sharing would have
# meant reshaping set_active's cross-project loop around a single-project
# predicate, touching a function this task has no reason to change.
_LAST_ACTIVE_ADMIN_FN = """
CREATE OR REPLACE FUNCTION portal._is_last_active_admin(p_name text, p_admin_group text)
RETURNS boolean LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_other_active_admins int;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_auth_members m
    JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = p_admin_group
    JOIN pg_roles u ON u.oid = m.member AND u.rolname = p_name
  ) THEN
    RETURN false;
  END IF;
  SELECT count(*) INTO v_other_active_admins FROM pg_auth_members m
  JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = p_admin_group
  JOIN pg_roles u ON u.oid = m.member
  WHERE u.rolcanlogin AND u.rolname <> p_name;
  RETURN v_other_active_admins = 0;
END; $fn$;
"""

# Moving a project's last active admin to any non-admin role empties the
# admin group exactly as surely as revoke_project_role would -- reachable
# from the very next line of the same matrix popover -- so it is refused the
# same way. Re-granting admin to the sole admin (p_role = 'admin') is
# excluded from the guard: that leaves the admin group non-empty, so it must
# stay the no-op it already is.
_SET_ROLE_FN = f"""
CREATE OR REPLACE FUNCTION portal.set_project_role(p_name text, p_project text, p_role text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_prefix text; r text;
BEGIN
  IF p_role NOT IN ('viewer','contributor','editor','admin') THEN
    RAISE EXCEPTION 'unknown role %%', p_role;
  END IF;
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
  -- Serialise with every other function that can mutate this project's admin
  -- group (revoke_project_role, set_active) on the same key, so two concurrent
  -- "is there another admin left" reads under READ COMMITTED can never both
  -- see the pre-mutation count and both proceed. Held for the rest of the
  -- transaction (xact-scoped), released automatically at COMMIT/ROLLBACK.
  PERFORM pg_advisory_xact_lock(hashtext(v_prefix || '_admin'));
  IF p_role <> 'admin' AND portal._is_last_active_admin(p_name, v_prefix || '_admin') THEN
    RAISE EXCEPTION 'cannot demote %%: last active admin (%%)', p_name, v_prefix || '_admin';
  END IF;
  FOREACH r IN ARRAY ARRAY['viewer','contributor','editor','admin'] LOOP
    EXECUTE format('REVOKE %%I FROM %%I', v_prefix || '_' || r, p_name);
  END LOOP;
  EXECUTE format('GRANT %%I TO %%I', v_prefix || '_' || p_role, p_name);
END; $fn$;
"""

# Removing every assignable group role for one project drops the user out of
# portal.users for that project entirely -- which is what an emptied matrix
# cell means. The account itself and any access to OTHER projects are
# untouched. Revoking the project's last active admin has the same failure
# shape set_active's disable guard exists to prevent: nobody would be left
# who can grant access back through the portal for that project, and
# recovery would need the setup_roles CLI on the host machine, so that case
# is guarded the same way (mirroring set_active's rolcanlogin-scoped count,
# via the shared portal._is_last_active_admin above).
# Unlike set_active, this does NOT special-case the caller's own account:
# set_project_role already lets an admin demote themselves away from
# <prefix>_admin today with no such guard (it is revoke-then-grant), and a
# self-revoke while another admin remains is recoverable through that other
# admin -- it is the *last* admin leaving that the portal cannot undo, not
# *which* admin does the revoking.
_REVOKE_ROLE_FN = f"""
CREATE OR REPLACE FUNCTION portal.revoke_project_role(p_name text, p_project text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
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
  -- Same lock key as set_project_role/set_active (hashtext of this project's
  -- admin group name), so the three functions that can empty this project's
  -- admin group can never both race past their last-admin check.
  PERFORM pg_advisory_xact_lock(hashtext(v_prefix || '_admin'));
  IF portal._is_last_active_admin(p_name, v_prefix || '_admin') THEN
    RAISE EXCEPTION 'cannot revoke %%: last active admin (%%)', p_name, v_prefix || '_admin';
  END IF;
  FOREACH r IN ARRAY ARRAY['viewer','contributor','editor','admin'] LOOP
    EXECUTE format('REVOKE %%I FROM %%I', v_prefix || '_' || r, p_name);
  END LOOP;
END; $fn$;
"""

_RESET_PW_FN = f"""
CREATE OR REPLACE FUNCTION portal.reset_password(p_name text, p_verifier text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
{_VERIFIER_GUARD}
  EXECUTE format('ALTER ROLE %%I PASSWORD %%L', p_name, p_verifier);
END; $fn$;
"""

# p_caller's DEFAULT current_user is evaluated in the CALLER's context (before
# the SECURITY DEFINER switch), so it reliably names the SET ROLE'd admin who
# invoked the function -- the API always calls with two arguments. An admin
# passing an explicit third argument only bypasses the self-disable guard, and
# admins are trusted with worse; the guards protect against accidents, not
# malice. Lockout guards fire only when DISABLING:
#   - you cannot disable your own account (the session would outlive the lock
#     and the lockout would surface hours later, after logout);
#   - you cannot disable the last ACTIVE admin of any project (nobody could
#     re-enable anyone via the portal afterwards; recovery would require the
#     setup_roles CLI on the host machine).
_SET_ACTIVE_FN = f"""
CREATE OR REPLACE FUNCTION portal.set_active(p_name text, p_active boolean, p_caller text DEFAULT current_user)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_admin_group text; v_other_active_admins int;
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
  IF NOT p_active THEN
    IF p_name = p_caller THEN
      RAISE EXCEPTION 'you cannot disable your own account (%%)', p_name;
    END IF;
    -- ORDER BY makes lock acquisition order deterministic across projects:
    -- with a single registered project this loop can never deadlock, but
    -- once a second one exists, two concurrent set_active calls each
    -- disabling an admin of multiple projects must always take these
    -- per-project locks in the same relative order, or they could each hold
    -- one project's lock while waiting on the other's.
    FOR v_admin_group IN SELECT role_prefix || '_admin' FROM portal.projects ORDER BY role_prefix LOOP
      -- Same lock key as set_project_role/revoke_project_role for this
      -- project's admin group, taken before the membership/count check so
      -- disabling races with a concurrent demotion/revocation on the same
      -- project instead of both reading a stale "one other admin remains".
      PERFORM pg_advisory_xact_lock(hashtext(v_admin_group));
      IF EXISTS (
        SELECT 1 FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = v_admin_group
        JOIN pg_roles u ON u.oid = m.member AND u.rolname = p_name
      ) THEN
        SELECT count(*) INTO v_other_active_admins FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = v_admin_group
        JOIN pg_roles u ON u.oid = m.member
        WHERE u.rolcanlogin AND u.rolname <> p_name;
        IF v_other_active_admins = 0 THEN
          RAISE EXCEPTION 'cannot disable %%: last active admin (%%)', p_name, v_admin_group;
        END IF;
      END IF;
    END LOOP;
  END IF;
  EXECUTE format('ALTER ROLE %%I %%s', p_name, CASE WHEN p_active THEN 'LOGIN' ELSE 'NOLOGIN' END);
END; $fn$;
"""

# One row per (login user, project, role). LIKE prefix\_% would also match the
# service role cplan_sync, so the role is matched against the four assignable
# group roles explicitly and sync/authenticator/owner are excluded.
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

# Names are not secret — every signed-in user may read them, so a tile or a
# drawer can say "Andrea Keller" instead of "a.keller". Writes go through
# SECURITY DEFINER functions: set_display_name is admin-only, record_sign_in is
# called by the service identity on the login path, before any SET ROLE happens.
_SET_DISPLAY_NAME_FN = f"""
CREATE OR REPLACE FUNCTION portal.set_display_name(p_name text, p_display text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
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

_RECORD_SIGN_IN_FN = f"""
CREATE OR REPLACE FUNCTION portal.record_sign_in(p_name text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
BEGIN
  IF p_name = ANY ({_RESERVED_SQL_ARRAY}) THEN
    RAISE EXCEPTION 'reserved role %%', p_name;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_name) THEN
    RAISE EXCEPTION 'unknown user %%', p_name;
  END IF;
  INSERT INTO portal.user_profile (username, last_sign_in) VALUES (p_name, now())
  ON CONFLICT (username) DO UPDATE SET last_sign_in = now();
END; $fn$;
"""

# Failed-login throttling. The policy -- how many attempts, over what window --
# lives in pipeline/api/login_guard.py and arrives as parameters; these three
# functions are the shared store the counters are kept in, and they are also
# where the counting is made *atomic*, which is the part an application cannot
# do for itself: a login handler that reads a count, probes the credentials and
# then writes the count back admits every request that is already in flight,
# so the enforced ceiling becomes the server's concurrency rather than the
# limit. `begin_login_attempt` therefore reserves the attempt and reports the
# verdict in one statement per counter, under the row lock `INSERT ... ON
# CONFLICT DO UPDATE` takes; the handler calls `end_login_attempt` to give the
# reservation back when the attempt turns out not to have been a guess (a
# correct password, or a database that could not answer at all).
#
# Every window is measured against `now()` *inside* the database and never
# against a timestamp the caller passes in. The counters are shared by every
# portal and studio process in the deployment, and each of those runs on a
# workstation whose clock is not under this product's control: a caller-supplied
# clock lets one machine that is fifteen minutes fast reset a lockout that every
# other process still considers live -- or, set deliberately, clear its own.
# One clock for one shared counter is the only version of this that holds.
#
# None of them raises for an unknown username, unlike every function above.
# That is the point: an attempt against a name that does not exist has to be
# counted, blocked and answered exactly like an attempt against a real one, or
# the throttle itself becomes the account-enumeration oracle the login
# endpoint was careful not to be. They also build no dynamic SQL at all -- a
# username here is only ever a value compared against a text column, never an
# identifier -- so there is nothing for format %I/%L to quote.
#
# The three counter keys, in the fixed order every statement below locks them
# in (so two concurrent attempts can queue but never deadlock):
#
#   'username'  the name, across all addresses -- the backstop against a
#               distributed guessing run on one account.
#   'pair'      one address against one name -- the counter that actually stops
#               a sequential guesser, and the one that keeps a lockout off
#               everybody else: it cannot deny the owner, who signs in from
#               their own address, service.
#   'source'    one address, across all names -- the counter that sees password
#               spraying, which neither of the others can.
#
# The 'pair' key is length-prefixed (`7:alice203.0.113.1`) rather than joined
# with a separator, because the submitted username is arbitrary text: with a
# separator, a caller could submit a name that made its pair key collide with
# another address's.
_LOGIN_COUNTER_KEYS = """
  v_kinds text[] := ARRAY['username', 'pair', 'source'];
  v_keys text[] := ARRAY[
    p_username,
    length(p_username)::text || ':' || p_username || p_source,
    p_source];
"""

# Reserve one attempt against each counter and report whether it may proceed.
#
# Fixed windows, not sliding ones: a counter's window starts at its first
# attempt and ends `p_window_seconds` later, whatever happens in between. That
# is what makes a lockout release on its own under sustained attack. With a
# window that slid from the last counted attempt, every attempt that aged out
# admitted exactly one new one, which was counted and started the window again
# -- five wrong passwords plus continuous hammering denied a named account for
# as long as the attacker cared to keep typing.
#
# A blocked attempt gives its reservation straight back, so it neither spends
# budget nor is visible in the counters at all.
_BEGIN_LOGIN_ATTEMPT_FN = f"""
CREATE OR REPLACE FUNCTION portal.begin_login_attempt(
  p_username text, p_source text,
  p_username_limit integer, p_pair_limit integer, p_source_limit integer,
  p_window_seconds integer, p_count_source boolean)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE
  v_now timestamptz := now();
  v_window interval := make_interval(secs => p_window_seconds);
  v_floor timestamptz := v_now - v_window;
{_LOGIN_COUNTER_KEYS}
  v_limits integer[] := ARRAY[p_username_limit, p_pair_limit, p_source_limit];
  v_attempts integer;
  v_over boolean := false;
  i integer;
BEGIN
  -- Garbage collection, not policy: a counter two full windows past its start
  -- can no longer block anything (the reservation below resets it on sight),
  -- so dropping it only keeps the table at the size of one window's traffic.
  -- SKIP LOCKED keeps this out of the way of a concurrent attempt rather than
  -- queueing behind it.
  DELETE FROM portal.login_attempts
   WHERE ctid IN (SELECT ctid FROM portal.login_attempts
                   WHERE window_started_at < v_now - v_window - v_window
                   ORDER BY kind, key FOR UPDATE SKIP LOCKED);

  FOR i IN 1..3 LOOP
    CONTINUE WHEN i = 3 AND NOT p_count_source;
    INSERT INTO portal.login_attempts AS a (kind, key, attempts, window_started_at)
    VALUES (v_kinds[i], v_keys[i], 1, v_now)
    ON CONFLICT (kind, key) DO UPDATE
       SET attempts = CASE WHEN a.window_started_at <= v_floor THEN 1
                           ELSE a.attempts + 1 END,
           window_started_at = CASE WHEN a.window_started_at <= v_floor THEN v_now
                                    ELSE a.window_started_at END
    RETURNING a.attempts INTO v_attempts;
    IF v_attempts > v_limits[i] THEN
      v_over := true;
    END IF;
  END LOOP;

  IF v_over THEN
    PERFORM portal.end_login_attempt(p_username, p_source, p_count_source);
    RETURN false;
  END IF;
  RETURN true;
END; $fn$;
"""

# Hand a reservation back. Called for a correct password and for a credential
# check that could not be carried out at all -- neither is a guess, and only
# guesses may spend the budget. Also called by begin_login_attempt itself for
# the attempt it just refused.
_END_LOGIN_ATTEMPT_FN = f"""
CREATE OR REPLACE FUNCTION portal.end_login_attempt(
  p_username text, p_source text, p_count_source boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE
{_LOGIN_COUNTER_KEYS}
  i integer;
BEGIN
  FOR i IN 1..3 LOOP
    CONTINUE WHEN i = 3 AND NOT p_count_source;
    UPDATE portal.login_attempts SET attempts = attempts - 1
     WHERE kind = v_kinds[i] AND key = v_keys[i] AND attempts > 0;
    DELETE FROM portal.login_attempts
     WHERE kind = v_kinds[i] AND key = v_keys[i] AND attempts <= 0;
  END LOOP;
END; $fn$;
"""

# The operator's way out, for the case the counters cannot fix themselves: a
# name (or an address) that must be able to sign in NOW rather than at the end
# of the window. Deliberately not reachable from the portal -- the person who
# needs it is by definition the person the portal is refusing -- so it is run
# by the same admin/superuser identity that runs apply_portal, through
# `python -m pipeline.api.setup_portal --clear-login-block`.
_CLEAR_LOGIN_ATTEMPTS_FN = """
CREATE OR REPLACE FUNCTION portal.clear_login_attempts(p_key text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_removed bigint;
BEGIN
  IF p_key IS NULL THEN
    DELETE FROM portal.login_attempts;
  ELSE
    -- starts_with, not LIKE: a username may legitimately contain '_', which
    -- LIKE would read as a wildcard and use to clear a different name's
    -- counter.
    DELETE FROM portal.login_attempts
     WHERE key = p_key
        OR (kind = 'pair' AND starts_with(key, length(p_key)::text || ':' || p_key));
  END IF;
  GET DIAGNOSTICS v_removed = ROW_COUNT;
  RETURN v_removed;
END; $fn$;
"""

# Called on the login path, before the request has a SET ROLE'd identity --
# the same position record_sign_in occupies, and so granted to the service
# role rather than to cplan_admin (see the comment beside record_sign_in in
# apply_portal below for why that loop's blanket admin grant is wrong here).
LOGIN_GUARD_ENTRY_POINT = (
    "portal.begin_login_attempt(text, text, integer, integer, integer, integer, boolean)"
)
_CLEAR_SIGNATURE = "portal.clear_login_attempts(text)"
_LOGIN_GUARD_FUNCTIONS = (
    ("portal.end_login_attempt(text, text, boolean)", _END_LOGIN_ATTEMPT_FN),
    (LOGIN_GUARD_ENTRY_POINT, _BEGIN_LOGIN_ATTEMPT_FN),
)

# The two functions that take a verifier, named here rather than only inside
# _FUNCTIONS because a second module needs the exact signatures: the portal
# asks Postgres whether the caller may EXECUTE them *before* it spends any
# time hashing a password (pipeline/portal/app.py). A signature that drifted
# from the one actually created would make that question be about a function
# that does not exist, which raises 42883 rather than answering -- so the two
# uses read the same constant.
CREATE_USER_SIGNATURE = "portal.create_user(text, text, text, text)"
RESET_PASSWORD_SIGNATURE = "portal.reset_password(text, text)"

_FUNCTIONS = (
    (CREATE_USER_SIGNATURE, _CREATE_USER_FN),
    ("portal.set_project_role(text, text, text)", _SET_ROLE_FN),
    ("portal.revoke_project_role(text, text)", _REVOKE_ROLE_FN),
    (RESET_PASSWORD_SIGNATURE, _RESET_PW_FN),
    ("portal.set_active(text, boolean, text)", _SET_ACTIVE_FN),
    ("portal.set_display_name(text, text)", _SET_DISPLAY_NAME_FN),
)

# Superseded signatures that must be dropped before (re)creating the functions:
# CREATE OR REPLACE cannot change a signature -- it would ADD an overload, and
# the API's two-argument call would keep resolving to the old, guard-free
# variant that still carries its EXECUTE grant.
_LEGACY_SIGNATURES = ("portal.set_active(text, boolean)",)

# Same signature, renamed parameter: p_password became p_verifier when the
# argument stopped being a password. CREATE OR REPLACE refuses a rename
# outright ("cannot change name of input parameter"), so an installation
# created before that change cannot be upgraded without dropping these two
# first. Unlike _LEGACY_SIGNATURES they ARE recreated immediately afterwards,
# by the _FUNCTIONS loop below -- both the drops and every re-creation run
# inside apply_portal's single transaction, so a concurrent session either
# sees the old function or the new one, never a missing one, and a failure
# partway through leaves the database exactly as it was.
_RENAMED_PARAMETER_SIGNATURES = (CREATE_USER_SIGNATURE, RESET_PASSWORD_SIGNATURE)


def _existing_group_roles(connection: Connection, role_prefix: str) -> list[str]:
    """The subset of `<role_prefix>_{viewer,contributor,editor,admin}` that already exist as roles.

    A project can be registered (a row in `portal.projects`) before its group
    roles are created -- the README documents that as the normal two-step
    process for adding a project -- so every caller here must tolerate some
    or all of the four not existing yet, rather than erroring on a GRANT or
    REVOKE against a role that is not there.
    """
    names = [f"{role_prefix}_{suffix}" for suffix in _ROLE_SUFFIXES]
    existing = set(
        connection.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"), {"names": names}
        ).scalars()
    )
    return [name for name in names if name in existing]


def _grant_admin_option(connection: Connection, role_prefix: str) -> None:
    """Ensure portal_owner holds ADMIN OPTION on this project's assignable group roles.

    Needed for two things: the portal.* SECURITY DEFINER functions -- which
    execute as portal_owner -- can GRANT these roles at all only if
    portal_owner holds ADMIN OPTION on them; and portal_owner can be named as
    the GRANTED BY of a fresh grant (see _repair_grantor below) only because
    PostgreSQL requires the named grantor to already hold ADMIN OPTION on the
    role being granted.

    Originally this only ever ran for CPLAN's own four roles. A second
    registered project needs the identical extension on its own four roles,
    or every portal.create_user/set_project_role/revoke_project_role call
    against it fails Postgres's own privilege check with SQLSTATE 42501 --
    surfacing as a 403 that looks like the caller lacking permission rather
    than the installation being incomplete.

    Idempotent: re-granting ADMIN OPTION on a role portal_owner already holds
    it on is a no-op. Silently does nothing for a role that does not exist
    yet (see _existing_group_roles) -- apply_portal's per-project loop and a
    later register_project/apply_portal call are what pick it up once it does.
    """
    quote = connection.dialect.identifier_preparer.quote
    for group in _existing_group_roles(connection, role_prefix):
        connection.exec_driver_sql(f"GRANT {quote(group)} TO {quote(PORTAL_OWNER)} WITH ADMIN OPTION")


def _repair_grantor(connection: Connection, role_prefix: str) -> None:
    """Re-attribute this project's group-role memberships granted by someone other than portal_owner.

    The canonical case: `setup_roles.create_user` -- the command-line path
    that creates the very first admin, before the portal can be used at all
    -- issues its GRANT while connected as the superuser, so the superuser is
    the grantor. PostgreSQL's REVOKE honours the grantor, and every portal.*
    user-management function runs as portal_owner, so portal_owner cannot
    revoke a membership it did not grant -- that account would sit
    permanently outside the access administration the portal provides (and,
    worse, a REVOKE attempted by a grantor that does not match produces no
    error at all, just a silent warning and an unchanged membership -- so the
    failure is invisible until someone notices the account is still there).

    Fixing it means re-granting with portal_owner as the explicit GRANTED BY,
    which requires portal_owner to already hold ADMIN OPTION on the role --
    _grant_admin_option is always called first for every project in
    apply_portal, below, so that precondition holds by the time this runs.

    Excludes this project's own group/service roles by NAME (its four
    assignable roles plus `<prefix>_sync`, and the cluster-wide
    cplan_authenticator/portal_owner) -- the same shape _USERS_VIEW below
    already uses to separate real accounts from group/service roles.
    Deliberately NOT `u.rolcanlogin`: that column is `portal.set_active`'s own
    active/disabled flag (`_USERS_VIEW` exposes it as `active`), not "is this
    a real account" -- a disabled account is still a fully manageable portal
    account (neither set_project_role nor revoke_project_role checks whether
    it is active), and it is exactly the account most likely to need this
    repair: someone who left, disabled rather than deleted, is precisely who
    an operator would next try to strip of access. Filtering on rolcanlogin
    would silently skip it forever, since apply_portal is not a startup path
    that would come back around for it on its own.

    Safe to re-run: a membership already granted by portal_owner fails the
    `grantor <> portal_owner` filter and is never touched, so a database with
    nothing to repair does nothing here. The REVOKE and the re-GRANT run
    inside apply_portal's single enclosing transaction, so a failure partway
    through (the REVOKE lands, the GRANT does not) rolls the whole
    apply_portal call back rather than ever persisting a membership that was
    revoked but never re-granted.
    """
    quote = connection.dialect.identifier_preparer.quote
    excluded_names = [f"{role_prefix}_{suffix}" for suffix in _SERVICE_SUFFIXES] + [AUTHENTICATOR, PORTAL_OWNER]
    for group in _existing_group_roles(connection, role_prefix):
        members = connection.execute(
            text(
                "SELECT u.rolname FROM pg_auth_members m "
                "JOIN pg_roles g ON g.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member "
                "JOIN pg_roles gr ON gr.oid = m.grantor "
                "WHERE g.rolname = :group AND u.rolname <> ALL(:excluded) AND gr.rolname <> :owner"
            ),
            {"group": group, "excluded": excluded_names, "owner": PORTAL_OWNER},
        ).scalars().all()
        for member in members:
            q_member = quote(member)
            connection.exec_driver_sql(f"REVOKE {quote(group)} FROM {q_member}")
            connection.exec_driver_sql(f"GRANT {quote(group)} TO {q_member} GRANTED BY {quote(PORTAL_OWNER)}")


def apply_portal(engine: Engine) -> None:
    with engine.begin() as c:
        exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": PORTAL_OWNER}).first()
        if not exists:
            c.exec_driver_sql(f"CREATE ROLE {PORTAL_OWNER} NOLOGIN CREATEROLE")

        c.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS portal AUTHORIZATION portal_owner")
        c.exec_driver_sql("GRANT USAGE ON SCHEMA portal TO PUBLIC")
        c.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS portal.projects ("
            "slug text PRIMARY KEY, name text NOT NULL, url text NOT NULL, role_prefix text NOT NULL UNIQUE)"
        )
        # UNIQUE is load-bearing, not incidental: portal.users and the
        # create_user/set_project_role functions resolve a project's group
        # roles by SELECTing role_prefix from this table. Two rows sharing a
        # prefix would make a grant on one project silently apply to the
        # other, and portal.users would emit a duplicate row per shared user.
        # A previous revision of this function briefly dropped the
        # constraint on this branch to let a test reuse another project's
        # prefix; that was wrong and never reached a pushed commit or a
        # database older than this branch, so there is nothing to migrate.
        c.exec_driver_sql("GRANT SELECT ON portal.projects TO PUBLIC")
        # Registry & view are owned by portal_owner so the SECURITY DEFINER
        # functions (also owned by it) can read them under their own privileges.
        c.exec_driver_sql("ALTER TABLE portal.projects OWNER TO portal_owner")

        c.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS portal.user_profile ("
            "username text PRIMARY KEY, display_name text, last_sign_in timestamptz)"
        )
        c.exec_driver_sql("ALTER TABLE portal.user_profile OWNER TO portal_owner")
        # Nothing reads this table directly: portal.users (SELECT granted to
        # cplan_admin alone, below) joins it, and the SECURITY DEFINER
        # functions read/write it under their own owner privileges. A PUBLIC
        # grant here would let any cluster login role -- including a mere
        # cplan_viewer with psql -- read the full account roster and every
        # last-sign-in time, undoing portal.users' admin-only intent. The
        # explicit REVOKE (not just omitting the GRANT) is load-bearing: it
        # corrects installations that already ran the old GRANT on a prior
        # `apply_portal`, not only fresh ones.
        c.exec_driver_sql("REVOKE SELECT ON portal.user_profile FROM PUBLIC")

        # One row per live counter -- (kind, key) -> attempts in this window --
        # for the login throttle in pipeline/api/login_guard.py. It lives in
        # the database rather than in the portal process on purpose: the portal
        # and the studio are separate processes over this one cluster, and more
        # workers or a second host must not each get their own private
        # allowance of guesses. The primary key is what makes the counting
        # atomic: `INSERT ... ON CONFLICT DO UPDATE` locks the row, so two
        # attempts arriving at the same instant queue instead of both reading
        # the same stale count. Owned by portal_owner and readable by nobody
        # directly -- the SECURITY DEFINER functions below are the only access
        # path, so a signed-in cplan_viewer with psql cannot mine it for who
        # has been failing to log in.
        c.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS portal.login_attempts ("
            "kind text NOT NULL, key text NOT NULL, attempts integer NOT NULL, "
            "window_started_at timestamptz NOT NULL, PRIMARY KEY (kind, key))"
        )
        c.exec_driver_sql("ALTER TABLE portal.login_attempts OWNER TO portal_owner")
        c.exec_driver_sql("REVOKE ALL ON TABLE portal.login_attempts FROM PUBLIC")
        # The pruning DELETE is left to a sequential scan deliberately: the
        # same statement is what keeps the table at one window's worth of
        # counters, so there is never much to scan, and an index on
        # window_started_at would cost every reservation for nothing.

        # Seed CPLAN (idempotent upsert).
        c.execute(
            text(
                "INSERT INTO portal.projects (slug, name, url, role_prefix) "
                "VALUES (:slug, :name, :url, :role_prefix) "
                "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, "
                "role_prefix = EXCLUDED.role_prefix"
            ),
            _CPLAN,
        )

        # Extend portal_owner's authority to every registered project's group
        # roles -- CPLAN's own four (just seeded above, on a fresh database)
        # and any other project register_project has ever added -- and repair
        # any membership on them still attributed to the wrong grantor.
        # Reads portal.projects fresh here (after the CPLAN upsert), so this
        # covers a project registered by an earlier apply_portal run or by
        # register_project directly, exactly as it covers CPLAN itself on a
        # brand new database. Order matters: _grant_admin_option must run
        # before _repair_grantor, since the repair's re-GRANT needs
        # portal_owner to already hold ADMIN OPTION on the role it names
        # itself as GRANTED BY for.
        for role_prefix in c.execute(text("SELECT role_prefix FROM portal.projects")).scalars().all():
            _grant_admin_option(c, role_prefix)
            _repair_grantor(c, role_prefix)

        c.exec_driver_sql(_USERS_VIEW)
        c.exec_driver_sql("ALTER VIEW portal.users OWNER TO portal_owner")
        c.exec_driver_sql("GRANT SELECT ON portal.users TO cplan_admin")

        # Created and owned before _FUNCTIONS below: set_project_role and
        # revoke_project_role call it by name in their bodies, and plpgsql
        # resolves that call (and so requires the function to already exist)
        # when THEY are created, not only when they are later invoked. It is
        # intentionally not part of _FUNCTIONS -- see the comment on
        # _LAST_ACTIVE_ADMIN_FN -- so it gets no GRANT EXECUTE TO cplan_admin.
        c.exec_driver_sql(_LAST_ACTIVE_ADMIN_FN)
        c.exec_driver_sql("ALTER FUNCTION portal._is_last_active_admin(text, text) OWNER TO portal_owner")
        c.exec_driver_sql("REVOKE ALL ON FUNCTION portal._is_last_active_admin(text, text) FROM PUBLIC")

        for legacy in _LEGACY_SIGNATURES + _RENAMED_PARAMETER_SIGNATURES:
            c.exec_driver_sql(f"DROP FUNCTION IF EXISTS {legacy}")
        for signature, ddl in _FUNCTIONS:
            c.exec_driver_sql(ddl)
            c.exec_driver_sql(f"ALTER FUNCTION {signature} OWNER TO portal_owner")
            c.exec_driver_sql(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
            c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION {signature} TO cplan_admin")

        # Every other portal.* function is admin-only. record_sign_in is called
        # on the login path, before the request has a SET ROLE'd identity, so it
        # is granted to the service role instead. It writes one timestamp for the
        # name it is given and reveals nothing. Deliberately NOT part of
        # _FUNCTIONS above -- see the comment on _LAST_ACTIVE_ADMIN_FN for why
        # that loop's blanket `GRANT ... TO cplan_admin` is not what this
        # function needs: no admin-facing endpoint calls it, so a grant to
        # cplan_admin on top of the service-role grant would only be unused
        # attack surface (an admin could stamp an arbitrary username's
        # last_sign_in, or insert a profile row for a name of their choosing).
        c.exec_driver_sql(_RECORD_SIGN_IN_FN)
        c.exec_driver_sql("ALTER FUNCTION portal.record_sign_in(text) OWNER TO portal_owner")
        c.exec_driver_sql("REVOKE ALL ON FUNCTION portal.record_sign_in(text) FROM PUBLIC")
        # CREATE OR REPLACE FUNCTION preserves an existing function's ACL --
        # it does not reset it. A database that ran a previous apply_portal
        # (when record_sign_in was still part of the _FUNCTIONS loop above
        # and so received `GRANT EXECUTE ... TO cplan_admin`) keeps that grant
        # forever unless it is explicitly revoked here; `REVOKE ALL FROM
        # PUBLIC` only strips PUBLIC's own privileges, not a role's explicit
        # grant. This REVOKE is therefore load-bearing for upgrades, exactly
        # like the portal.user_profile REVOKE above, and must stay below
        # every statement that could re-grant cplan_admin here (there is
        # none) so a later apply_portal run can never quietly restore it.
        c.exec_driver_sql("REVOKE EXECUTE ON FUNCTION portal.record_sign_in(text) FROM cplan_admin")
        c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION portal.record_sign_in(text) TO {AUTHENTICATOR}")

        # The login counters sit in the same position as record_sign_in --
        # called by the service identity on the login path, before any SET
        # ROLE -- and get the same treatment: service-role EXECUTE only. An
        # admin grant would be worse than unused here: end_login_attempt would
        # let any admin hand a guessing run its budget back, and
        # begin_login_attempt would let one lock an account out by naming it.
        for signature, ddl in _LOGIN_GUARD_FUNCTIONS:
            c.exec_driver_sql(ddl)
            c.exec_driver_sql(f"ALTER FUNCTION {signature} OWNER TO portal_owner")
            c.exec_driver_sql(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
            c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION {signature} TO {AUTHENTICATOR}")

        # clear_login_attempts is the operator's override and is granted to
        # nobody at all -- not even the service role. It runs as the
        # admin/superuser identity that runs this module (which owns or
        # bypasses everything here anyway), because the person who needs a
        # lockout cleared is the person the portal is currently refusing, so a
        # grant on a portal-reachable role would be both useless and a way to
        # hand a guessing run its budget back.
        c.exec_driver_sql(_CLEAR_LOGIN_ATTEMPTS_FN)
        c.exec_driver_sql(f"ALTER FUNCTION {_CLEAR_SIGNATURE} OWNER TO portal_owner")
        c.exec_driver_sql(f"REVOKE ALL ON FUNCTION {_CLEAR_SIGNATURE} FROM PUBLIC")


def register_project(engine: Engine, slug: str, name: str, url: str, role_prefix: str) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO portal.projects (slug, name, url, role_prefix) "
                "VALUES (:slug, :name, :url, :role_prefix) "
                "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, "
                "role_prefix = EXCLUDED.role_prefix"
            ),
            {"slug": slug, "name": name, "url": url, "role_prefix": role_prefix},
        )
        # If this project's group roles already exist -- registering after
        # creating them is a valid order too -- extend portal_owner's ADMIN
        # OPTION to them immediately, so portal.create_user/set_project_role/
        # revoke_project_role work right away instead of needing a separate
        # apply_portal run. When the roles do not exist yet (the README's
        # documented order: register, then create the roles), this is a
        # no-op; apply_portal's own sweep over every registered project is
        # what closes the gap once they exist, and is also what covers a
        # project that was registered before this call existed at all.
        _grant_admin_option(c, role_prefix)


def _resolve_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    from_environment = database_url_from_environment()
    if from_environment:
        return str(from_environment)
    from pipeline.api.setup_backend import load_backend_config, resolve_backend_database_url

    return resolve_backend_database_url(load_backend_config())


def clear_login_block(engine: Engine, key: str | None) -> int:
    """Release a login lockout now instead of at the end of its window.

    `key` is a username or a source address; `None` clears every counter in
    the deployment. Runs as the same admin/superuser identity as
    `apply_portal` -- see `_CLEAR_LOGIN_ATTEMPTS_FN` for why this is not
    reachable from the portal itself.
    """
    with engine.begin() as c:
        return int(c.execute(text("SELECT portal.clear_login_attempts(:k)"), {"k": key}).scalar_one())


def main() -> None:
    parser = argparse.ArgumentParser(description="CPLAN portal schema, registry, and user-management functions")
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--clear-login-block",
        metavar="NAME_OR_ADDRESS",
        default=None,
        help=(
            "release the failed-login lockout on one username or source address "
            "(use --all for every counter) instead of applying the schema"
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="with --clear-login-block: clear every login counter in the deployment",
    )
    args = parser.parse_args()
    engine = create_cplan_engine(_resolve_url(args.database_url))
    try:
        if args.clear_login_block or args.all:
            removed = clear_login_block(engine, None if args.all else args.clear_login_block)
            print(f"Cleared {removed} login counter(s); sign-in is possible again immediately.")
            return
        apply_portal(engine)
        print("Portal schema, project registry, user-management functions and login throttle applied.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
