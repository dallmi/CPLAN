#!/usr/bin/env python3
"""
CPLAN Data Pipeline — CSV → DuckDB + Parquet → HTML Dashboard

Reads communication activity CSVs exported by Power Automate from SharePoint
Lists into a OneDrive sync folder, transforms and joins them, and writes a
DuckDB database plus Parquet files for the HTML dashboard.

Input priority:
  1. OneDrive sync folder: <OneDrive>/Projekte/CPLAN/Input/*.csv
  2. Local fallback:       pipeline/input/*.csv

Known input files:
  - InternalCommunicationActivities*.csv
  - ExternalCommunicationActivities*.csv

Usage:
    python process_cplan.py                # process all input files
    python process_cplan.py --preview      # read and print without saving
    python process_cplan.py --full-refresh # delete DB and reprocess everything

Output:
    - data/cplan.db                        (DuckDB database)
    - output/communications.parquet        (combined + transformed data)

Prerequisites:
    pip install pandas duckdb pyarrow
"""

import csv
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_INPUT_DIR = SCRIPT_DIR / "input"
OUTPUT_DIR = SCRIPT_DIR / "output"
DB_PATH = SCRIPT_DIR / "data" / "cplan.db"

# Relative path inside OneDrive to the Power Automate output folder
ONEDRIVE_INPUT_DIR = Path("Projekte") / "CPLAN" / "Input"

# Known input files and their glob patterns
INPUT_FILES = {
    "internal": "InternalCommunicationActivities*.csv",
    "external": "ExternalCommunicationActivities*.csv",
    "packs": "CommunicationPacks*.csv",
}


def log(message):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


# ---------------------------------------------------------------------------
# OneDrive discovery (reused from CampaignWe)
# ---------------------------------------------------------------------------

def find_onedrive_root():
    """Auto-detect the corporate OneDrive sync folder."""
    if sys.platform == "win32":
        home = Path.home()
        candidates = sorted(home.glob("OneDrive - *"), key=lambda p: p.name)
        if candidates:
            return candidates[0]
    else:
        # macOS / Linux: ~/Library/CloudStorage/OneDrive-*
        cloud = Path.home() / "Library" / "CloudStorage"
        if cloud.exists():
            candidates = sorted(cloud.glob("OneDrive-*"), key=lambda p: p.name)
            corp = [c for c in candidates if "person" not in c.name.lower()
                    and "persönlich" not in c.name.lower()]
            if corp:
                return corp[0]
            if candidates:
                return candidates[0]

    env_path = os.environ.get("OneDriveCommercial") or os.environ.get("OneDrive")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    return None


def find_input_dir():
    """Return the input directory: OneDrive first, then local fallback."""
    onedrive_root = find_onedrive_root()
    if onedrive_root:
        onedrive_dir = onedrive_root / ONEDRIVE_INPUT_DIR
        if onedrive_dir.exists():
            log(f"Using OneDrive input: {onedrive_dir}")
            return onedrive_dir
        else:
            log(f"OneDrive root found ({onedrive_root}) but {ONEDRIVE_INPUT_DIR} does not exist")

    LOCAL_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Using local fallback: {LOCAL_INPUT_DIR}")
    return LOCAL_INPUT_DIR


def find_input_files(input_dir):
    """Find all known input CSVs in the input directory.

    Returns dict: { "internal": Path, "external": Path, ... }
    Only includes files that actually exist. Picks the newest match per pattern.
    """
    found = {}
    for key, pattern in INPUT_FILES.items():
        matches = list(input_dir.glob(pattern))
        matches = [f for f in matches if not f.name.startswith("~$")]
        if matches:
            newest = max(matches, key=lambda f: f.stat().st_mtime)
            found[key] = newest
            log(f"  {key}: {newest.name}")
        else:
            log(f"  {key}: not found (pattern: {pattern})")
    return found


# ---------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------

def read_csv_auto(path):
    """Read a CSV file, auto-detecting the delimiter."""
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        sample = f.read(8192)
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample, delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        sep = ","
    log(f"  Reading {path.name} (delimiter={repr(sep)})")
    return pd.read_csv(path, sep=sep)


# ---------------------------------------------------------------------------
# SharePoint field parsing
# ---------------------------------------------------------------------------

def decode_sp_column_name(name):
    """Decode SharePoint-encoded column names.

    SharePoint encodes special characters in internal column names:
      _x0020_ = space, _x0028_ = (, _x0029_ = ), _x0021_ = !,
      _x002f_ = /, _x002e_ = .
    """
    import re
    def _replace(m):
        return chr(int(m.group(1), 16))
    return re.sub(r"_x([0-9a-fA-F]{4})_", _replace, name)


def _strip_html(val):
    """Strip HTML tags and decode entities, returning plain text."""
    if pd.isna(val) or not isinstance(val, str):
        return val
    text = re.sub(r"</p>", "\n", val)     # paragraph breaks → newline
    text = re.sub(r"<br\s*/?>", "\n", text)  # <br> → newline
    text = re.sub(r"<[^>]+>", "", text)  # strip remaining tags
    text = html.unescape(text)           # decode &amp; &nbsp; etc.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_sp_lookup(val):
    """Extract the Value from a SharePoint lookup/taxonomy JSON field.

    SharePoint Power Automate exports lookup columns as JSON:
      {"@odata.type": "...", "Id": 2, "Value": "Global Wealth"}
    or arrays of lookups:
      [{"Id": 1, "Value": "Email"}, {"Id": 2, "Value": "Intranet"}]
    or person fields with Claims identity:
      {"Claims": "i:0#.f|membership|john@corp.com", "DisplayName": "John"}

    Returns the extracted value(s) as a string, or the original value if
    not a JSON lookup.
    """
    if pd.isna(val) or val == "":
        return ""
    if not isinstance(val, str):
        return str(val)

    # Quick check — skip if it doesn't look like JSON
    stripped = val.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return _strip_taxonomy_guid(stripped)

    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return val

    if isinstance(parsed, list):
        values = []
        for item in parsed:
            if isinstance(item, dict):
                values.append(_extract_sp_value(item))
            elif isinstance(item, str) and item.strip():
                values.append(item.strip())
        return ", ".join(v for v in values if v)

    if isinstance(parsed, dict):
        return _extract_sp_value(parsed)

    return val


def _strip_taxonomy_guid(val):
    """Remove pipe-delimited GUIDs from SharePoint taxonomy values.

    Taxonomy fields often return "Label|<GUID>" e.g.:
      "FFEM - GWM EMEA|a686bf48-e358-4756-b907-..."
      "All|98cdf24c-ab69-472e-ada6-166e99a93a8d"
    """
    if "|" not in val:
        return val
    # GUID pattern: 8-4-4-4-12 hex chars
    parts = val.rsplit("|", 1)
    if len(parts) == 2 and re.match(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        parts[1].strip()
    ):
        return parts[0].strip()
    return val


def _extract_sp_value(obj):
    """Extract the most useful value from a single SP lookup object."""
    raw = ""
    # Person field
    if "DisplayName" in obj:
        raw = obj["DisplayName"]
    # Standard lookup / taxonomy
    elif "Value" in obj:
        raw = str(obj["Value"])
    # Fallback to Label (taxonomy)
    elif "Label" in obj:
        raw = obj["Label"]
    return _strip_taxonomy_guid(raw) if raw else ""


def parse_sp_person_email(val):
    """Extract email from a SharePoint person/Claims field.

    Claims format: "i:0#.f|membership|john@corp.com"
    """
    if pd.isna(val) or val == "":
        return ""
    if not isinstance(val, str):
        return ""

    stripped = val.strip()
    if not stripped.startswith("{") and not stripped.startswith("["):
        return ""

    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return ""

    if isinstance(parsed, dict):
        # Try Email field first
        if "Email" in parsed:
            return parsed["Email"]
        # Extract from Claims string
        claims = parsed.get("Claims", "")
        if "|membership|" in claims:
            return claims.split("|membership|")[-1]
    return ""


# ---------------------------------------------------------------------------
# Column mapping: SharePoint internal name -> clean output name
# ---------------------------------------------------------------------------

# Maps raw (SP-encoded) column names to clean output names.
# The values will be extracted via parse_sp_lookup where appropriate.
# Maps a decoded (human-readable) column label to a clean output name.
# Matching logic (in transform()):
#   1. Exact match on raw CSV column name
#   2. Exact match on decoded (SP hex → readable) column name
#   3. Decoded name starts with the label (handles SP suffixes like
#      "Business Division (some extra text)")
# Each CSV column maps to at most one output (first match wins,
# longest labels are tried first to keep it 1:1).
COLUMN_MAP = {
    "ID":                       "sp_id",
    "Tracking ID":              "tracking_id",
    "Tacking ID":               "tracking_id",
    "Title":                    "activity_name",
    "Activity":                 "activity_description",
    "Target audience":          "target_audience",
    "Extended audience":        "extended_audience",
    "Business Division":        "business_division",
    "Business Area":            "business_area",
    "Region":                   "region",
    "Channel":                  "channel",
    "Partner Team":             "partner_team",
    "Lead Team":                "lead_team",
    "Lead":                     "lead",
    "Start date":               "start_date",
    "End date":                 "end_date",
    "News digest":              "news_digest",
    "Priority":                 "priority",
    "Strategic Objectives":     "strategic_objectives",
    "Campaign":                 "campaign",
    "Campaign*LTID":            "campaign_ltid",
    "Communication pack:C":     "communication_pack_cpid",
    "BOD*GEB":                  "bod_geb",
    "Communication pack":       "communication_pack",
    "Communication":            "communication_ref",
    "Created":                  "created",
    "Modified":                 "modified",
    "Author":                   "author",
    "Audience":                 "audience",
}

# Columns that contain SP lookup JSON and need Value extraction
SP_LOOKUP_COLUMNS = {
    "target_audience", "extended_audience", "business_division",
    "business_area", "region", "channel", "lead", "lead_team",
    "partner_team", "priority", "strategic_objectives",
    "campaign", "campaign_ltid", "communication_pack_cpid", "bod_geb",
    "communication_ref", "communication_pack", "author", "audience",
}

# Columns where we also want to extract the email from Claims
SP_PERSON_COLUMNS = {"lead", "author"}

# Date columns (DD.MM.YYYY HH:MM format from SharePoint)
DATE_COLUMNS = {"start_date", "end_date", "created", "modified"}


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df, source_type):
    """Apply transformations to a raw DataFrame.

    1. Exact-match column names against COLUMN_MAP (raw + decoded variants)
    2. Extract values from SP lookup JSON fields
    3. Parse dates
    4. Tag with source type
    """
    # Strip whitespace from column names
    df.columns = [c.strip() for c in df.columns]

    # Drop noise columns before matching to reduce false positives
    drop_cols = [c for c in df.columns if _is_noise_col(c)]
    if drop_cols:
        df = df.drop(columns=drop_cols)
        log(f"  Dropped {len(drop_cols)} noise columns")

    log(f"  Columns after cleanup: {list(df.columns)}")

    # Build rename map — each CSV column maps to at most one output.
    # Try longest labels first so "Lead Team" matches before "Lead",
    # "Communication pack" before "Communication", etc.
    labels_sorted = sorted(COLUMN_MAP.keys(), key=len, reverse=True)
    rename_map = {}
    claimed_labels = set()  # labels already matched

    for col in df.columns:
        decoded = decode_sp_column_name(col).strip()
        for label in labels_sorted:
            if label in claimed_labels:
                continue
            # 1) Wildcard label "PREFIX*SUFFIX" — decoded must start with PREFIX
            #    and contain SUFFIX (e.g. "BOD*GEB")
            # 2) Exact match on raw name
            # 3) Exact match on decoded name
            # 4) Decoded name starts with label (handles SP suffixes)
            if "*" in label:
                prefix, suffix = label.split("*", 1)
                if decoded.startswith(prefix) and suffix in decoded:
                    rename_map[col] = COLUMN_MAP[label]
                    claimed_labels.add(label)
                    break
                continue
            if col == label or decoded == label or decoded.startswith(label):
                rename_map[col] = COLUMN_MAP[label]
                claimed_labels.add(label)
                break

    df = df.rename(columns=rename_map)

    # Keep only mapped columns + source_type, drop everything else
    keep = [c for c in rename_map.values() if c in df.columns]
    df = df[keep]

    log(f"  Mapped columns: {list(df.columns)}")

    # Strip HTML from rich text fields (e.g. activity)
    if "activity_description" in df.columns:
        df["activity_description"] = df["activity_description"].apply(_strip_html)

    # Extract person emails BEFORE lookup parsing (which replaces JSON with display names)
    for col in SP_PERSON_COLUMNS:
        if col in df.columns:
            df[f"{col}_email"] = df[col].apply(parse_sp_person_email)

    # Parse SP lookup JSON fields -> extract Value / DisplayName
    for col in SP_LOOKUP_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(parse_sp_lookup)

    # Parse dates — keep full datetime (date + time), convert to CET
    # Formats seen: "DD.MM.YYYY HH:MM", ISO 8601 with tz ("2025-05-06 08:00:00+00:00")
    CET = "Europe/Zurich"
    for col in DATE_COLUMNS:
        if col in df.columns:
            raw = df[col].copy()

            # Parse each value individually to handle mixed formats cleanly
            def _parse_date(val):
                if pd.isna(val) or not isinstance(val, str) or not val.strip():
                    return pd.NaT
                s = val.strip()
                # Try DD.MM.YYYY HH:MM(:SS)
                for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
                    try:
                        dt = pd.Timestamp(datetime.strptime(s, fmt))
                        # Naive → assume CET
                        return dt.tz_localize(CET)
                    except ValueError:
                        continue
                # Fallback: let pandas infer (ISO 8601 etc.)
                try:
                    dt = pd.Timestamp(s)
                    if dt.tz is not None:
                        return dt.tz_convert(CET)
                    else:
                        return dt.tz_localize(CET)
                except Exception:
                    return pd.NaT

            df[col] = raw.apply(_parse_date)

    # Boolean columns
    if "news_digest" in df.columns:
        df["news_digest"] = df["news_digest"].astype(str).str.upper().map(
            {"TRUE": True, "FALSE": False, "1": True, "0": False}
        )

    # Tag source
    df["source_type"] = source_type

    return df


# ---------------------------------------------------------------------------
# DuckDB + Parquet output
# ---------------------------------------------------------------------------

def write_table(df, table_name, parquet_name, full_refresh=False):
    """Write a DataFrame to Parquet, DuckDB table, and JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Parquet
    parquet_path = OUTPUT_DIR / f"{parquet_name}.parquet"
    df.to_parquet(parquet_path, index=False)
    log(f"Wrote {len(df)} rows to {parquet_path}")

    # DuckDB
    if full_refresh and DB_PATH.exists():
        # Only delete once (caller responsibility), but safe to call
        pass

    con = duckdb.connect(str(DB_PATH))
    try:
        if full_refresh:
            con.execute(f"DROP TABLE IF EXISTS {table_name}")

        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} AS
            SELECT * FROM read_parquet(?)
        """, [str(parquet_path)])

        if not full_refresh:
            con.execute(f"DELETE FROM {table_name}")
            con.execute(f"""
                INSERT INTO {table_name}
                SELECT * FROM read_parquet(?)
            """, [str(parquet_path)])

        row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        log(f"DuckDB: {row_count} rows in {table_name} table")

        schema = con.execute(f"DESCRIBE {table_name}").fetchall()
        log(f"Schema ({table_name}):")
        for col_name, col_type, *_ in schema:
            log(f"  {col_name:<40} {col_type}")
    finally:
        con.close()

    # JSON for HTML dashboard
    json_path = OUTPUT_DIR / f"{parquet_name}.json"
    json_df = df.copy()
    for col in json_df.select_dtypes(include=["datetime64", "datetimetz"]).columns:
        json_df[col] = json_df[col].astype(str)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "row_count": len(json_df),
        "columns": list(json_df.columns),
        "rows": json_df.to_dict(orient="records"),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=str)
    log(f"Wrote dashboard JSON to {json_path}")


PACKS_COLUMN_MAP = {
    "LTID":                     "cpid",
    "Business Division":        "business_division",
    "Region":                   "region",
    "Campaing":                 "lead",
    "Campaign":                 "lead",
    "Lead Team":                "lead_team",
    "Lead team":                "lead_team",
    "Objective":                "strategic_objective",
    "Start date":               "start_date",
    "Date of launch":           "launch_date",
    "Long Term":                "communication_pack_lookup",
    "Brief":                    "short_description",
    "Partner team":             "partner_team",
    "Partner Team":             "partner_team",
    "Created":                  "created",
    "Modified":                 "modified",
}

PACKS_LOOKUP_COLUMNS = {
    "business_division", "region", "lead", "lead_team",
    "strategic_objective", "communication_pack_lookup",
    "partner_team",
}

PACKS_PERSON_COLUMNS = {"lead"}

PACKS_DATE_COLUMNS = {"start_date", "launch_date", "created", "modified"}

PACKS_HTML_COLUMNS = {"short_description"}


def transform_packs(df):
    """Transform CommunicationPacks CSV with explicit column mapping."""
    df.columns = [c.strip() for c in df.columns]

    # Drop noise columns
    drop_cols = [c for c in df.columns if _is_noise_col(c)]
    if drop_cols:
        df = df.drop(columns=drop_cols)
        log(f"  Dropped {len(drop_cols)} noise columns")

    log(f"  Columns after cleanup: {list(df.columns)}")

    # Same matching logic as activities: decode, then longest-label-first
    labels_sorted = sorted(PACKS_COLUMN_MAP.keys(), key=len, reverse=True)
    rename_map = {}
    claimed_labels = set()

    for col in df.columns:
        decoded = decode_sp_column_name(col).strip()
        for label in labels_sorted:
            if label in claimed_labels:
                continue
            if col == label or decoded == label or decoded.startswith(label):
                rename_map[col] = PACKS_COLUMN_MAP[label]
                claimed_labels.add(label)
                break

    df = df.rename(columns=rename_map)

    # Keep only mapped columns
    keep = [c for c in rename_map.values() if c in df.columns]
    df = df[keep]

    log(f"  Mapped columns: {list(df.columns)}")

    # Extract person emails before lookup parsing
    for col in PACKS_PERSON_COLUMNS:
        if col in df.columns:
            df[f"{col}_email"] = df[col].apply(parse_sp_person_email)

    # Parse SP lookup JSON fields
    for col in PACKS_LOOKUP_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(parse_sp_lookup)

    # Strip HTML from rich text fields
    for col in PACKS_HTML_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(_strip_html)

    # Parse dates with CET conversion
    CET = "Europe/Zurich"
    for col in PACKS_DATE_COLUMNS:
        if col in df.columns:
            raw = df[col].copy()

            def _parse_date(val):
                if pd.isna(val) or not isinstance(val, str) or not val.strip():
                    return pd.NaT
                s = val.strip()
                for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
                    try:
                        dt = pd.Timestamp(datetime.strptime(s, fmt))
                        return dt.tz_localize(CET)
                    except ValueError:
                        continue
                try:
                    dt = pd.Timestamp(s)
                    if dt.tz is not None:
                        return dt.tz_convert(CET)
                    else:
                        return dt.tz_localize(CET)
                except Exception:
                    return pd.NaT

            df[col] = raw.apply(_parse_date)

    return df


# ---------------------------------------------------------------------------
# Pretty-print helpers for --preview
# ---------------------------------------------------------------------------

def _is_noise_col(col):
    """Check if a column should be dropped as noise (used by both transform and comparison)."""
    decoded = decode_sp_column_name(col).strip()
    return (
        "@odata.type" in col or "@odata.type" in decoded
        or col.endswith("#WssId") or decoded.endswith("#WssId")
        or col.endswith("#Id") or decoded.endswith("#Id")
        or col.endswith("#Claims") or decoded.endswith("#Claims")
    )


def print_column_comparison(raw_columns, files):
    """Print a comparison table of raw columns across input files."""
    sources = list(raw_columns.keys())

    # Filter noise columns (same logic as transform)
    clean_columns = {
        src: [c for c in cols if not _is_noise_col(c)]
        for src, cols in raw_columns.items()
    }

    # Match columns per source (same logic as transform)
    labels_sorted = sorted(COLUMN_MAP.keys(), key=len, reverse=True)
    # src -> { raw_col: clean_name or None }
    col_mapping = {}
    for src, cols in clean_columns.items():
        col_mapping[src] = {}
        claimed = set()
        for col in cols:
            decoded = decode_sp_column_name(col).strip()
            matched = None
            for label in labels_sorted:
                if label in claimed:
                    continue
                if "*" in label:
                    prefix, suffix = label.split("*", 1)
                    if decoded.startswith(prefix) and suffix in decoded:
                        matched = COLUMN_MAP[label]
                        claimed.add(label)
                        break
                    continue
                if col == label or decoded == label or decoded.startswith(label):
                    matched = COLUMN_MAP[label]
                    claimed.add(label)
                    break
            col_mapping[src][col] = matched

    # Build display rows grouped by output name (mapped) or decoded name (unmapped).
    # This merges typo variants (e.g. "Tracking ID" / "Tacking ID") into one row.
    all_rows = {}  # display_key -> { "clean": str|None, sources: {src: raw_col} }
    for src, mappings in col_mapping.items():
        for col, clean in mappings.items():
            decoded = decode_sp_column_name(col).strip()
            key = clean if clean else decoded  # group by output name if mapped
            if key not in all_rows:
                all_rows[key] = {"clean": clean, "sources": {}}
            all_rows[key]["sources"][src] = col
            if clean:
                all_rows[key]["clean"] = clean

    # Sort: mapped columns first, then unmapped
    def sort_key(key):
        mapped = all_rows[key]["clean"] is not None
        return (0 if mapped else 1, key.lower())

    sorted_cols = sorted(all_rows.keys(), key=sort_key)

    # Calculate column widths
    w_name = max(len("Column"), max(len(k) for k in sorted_cols))
    w_mapped = max(len("Mapped To"), max(
        (len(r["clean"] or "") for r in all_rows.values()), default=0
    ))
    w_mapped = max(w_mapped, 9)

    # Header
    print()
    print("=" * 80)
    print("  COLUMN COMPARISON")
    print("=" * 80)
    print()

    header = f"  {'Column':<{w_name}}  {'Mapped To':<{w_mapped}}"
    for src in sources:
        header += f"  {src:^10}"
    print(header)
    print(f"  {'─' * w_name}  {'─' * w_mapped}" + f"  {'─' * 10}" * len(sources))

    mapped_count = 0
    unmapped_count = 0

    for key in sorted_cols:
        row = all_rows[key]
        clean = row["clean"] or ""

        presence = ""
        for src in sources:
            if src in row["sources"]:
                presence += f"  {'  ✓':^10}"
            else:
                presence += f"  {'  ✗':^10}"

        if clean:
            mapped_count += 1
        else:
            unmapped_count += 1

        display_name = key[:w_name] if len(key) > w_name else key
        print(f"  {display_name:<{w_name}}  {clean:<{w_mapped}}{presence}")

    # Summary
    in_both = sum(1 for k in sorted_cols if len(all_rows[k]["sources"]) == len(sources))
    print()
    print(f"  Total unique columns: {len(sorted_cols)}")
    print(f"  In all files:         {in_both}")
    for src in sources:
        only = sum(1 for k in sorted_cols if set(all_rows[k]["sources"].keys()) == {src})
        total = sum(1 for k in sorted_cols if src in all_rows[k]["sources"])
        print(f"  {src + ' only:':<22} {only}   (total: {total})")
    print(f"  Mapped to output:     {mapped_count}")
    print(f"  Unmapped (dropped):   {unmapped_count}")
    print()


def print_data_preview(df, max_rows=20):
    """Print a pretty preview of the transformed data."""
    print("=" * 80)
    print(f"  DATA PREVIEW  ({len(df)} rows, {len(df.columns)} columns)")
    print("=" * 80)
    print()

    # Show column types
    print(f"  {'Column':<30} {'Type':<15} {'Non-null':<10} {'Sample'}")
    print(f"  {'─' * 30} {'─' * 15} {'─' * 10} {'─' * 40}")
    for col in df.columns:
        dtype = str(df[col].dtype)
        non_null = df[col].notna().sum()
        sample = ""
        first_valid = df[col].dropna().head(1)
        if not first_valid.empty:
            sample = str(first_valid.iloc[0])[:40]
        print(f"  {col:<30} {dtype:<15} {non_null:<10} {sample}")

    # Show first N rows
    print()
    print(f"  First {min(max_rows, len(df))} rows:")
    print(f"  {'─' * 76}")
    # Use a subset of columns that fit the terminal
    display_cols = [c for c in df.columns if c != "source_type"][:6]
    display_cols.append("source_type")

    # Header
    header = "  "
    for col in display_cols:
        w = min(20, max(len(col), 8))
        header += f"{col:<{w}}  "
    print(header)
    print("  " + "─" * len(header))

    for _, row in df.head(max_rows).iterrows():
        line = "  "
        for col in display_cols:
            w = min(20, max(len(col), 8))
            val = str(row.get(col, ""))[:w]
            line += f"{val:<{w}}  "
        print(line)

    if len(df) > max_rows:
        print(f"  ... and {len(df) - max_rows} more rows")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    preview = "--preview" in sys.argv
    full_refresh = "--full-refresh" in sys.argv

    log("=" * 60)
    log("CPLAN Data Pipeline")
    log("=" * 60)

    # Find input
    log("Looking for input files...")
    input_dir = find_input_dir()
    files = find_input_files(input_dir)

    if not files:
        log("ERROR: No input files found.")
        log(f"  Place CSV files in: {input_dir}/")
        log(f"  Expected patterns: {list(INPUT_FILES.values())}")
        sys.exit(1)

    if full_refresh and DB_PATH.exists():
        DB_PATH.unlink()
        log("Deleted existing database (full refresh)")

    # --- Communication activities (internal + external) ---
    activity_files = {k: v for k, v in files.items() if k in ("internal", "external")}
    frames = []
    raw_columns = {}
    for key, path in activity_files.items():
        df = read_csv_auto(path)
        log(f"  {key}: {len(df)} rows, {len(df.columns)} columns")
        raw_columns[key] = [c.strip() for c in df.columns]
        df = transform(df, source_type=key)
        frames.append(df)

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        log(f"Combined activities: {len(combined)} rows")

        if preview:
            print_column_comparison(raw_columns, activity_files)
            print_data_preview(combined)
        else:
            write_table(combined, "communications", "communications", full_refresh=full_refresh)

    # --- Communication packs ---
    if "packs" in files:
        log("Processing CommunicationPacks...")
        packs_df = read_csv_auto(files["packs"])
        log(f"  packs: {len(packs_df)} rows, {len(packs_df.columns)} columns")
        packs_df = transform_packs(packs_df)

        if preview:
            print()
            print("=" * 80)
            print(f"  PACKS PREVIEW  ({len(packs_df)} rows, {len(packs_df.columns)} columns)")
            print("=" * 80)
            print()
            for col in packs_df.columns:
                dtype = str(packs_df[col].dtype)
                non_null = packs_df[col].notna().sum()
                sample = ""
                first_valid = packs_df[col].dropna().head(1)
                if not first_valid.empty:
                    sample = str(first_valid.iloc[0])[:40]
                print(f"  {col:<30} {dtype:<15} {non_null:<10} {sample}")
        else:
            write_table(packs_df, "packs", "packs", full_refresh=full_refresh)

    if not preview:
        log("Done.")


if __name__ == "__main__":
    main()
