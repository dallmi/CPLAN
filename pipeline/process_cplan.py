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
    "internal_archive": "InternalCommunicationActivitiesArchive*.csv",
    "external_archive": "ExternalCommunicationActivitiesArchive*.csv",
    "packs": "CommunicationPacks*.csv",
    "internal_channels": "InternalChannels*.csv",
    "external_channels": "ExternalChannels*.csv",
    "clusters": "TrackingCluster*.csv",
}


def log(message):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"  {timestamp}  {message}")


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def _box_top(width):
    return "┌" + "─" * width + "┐"

def _box_mid(width):
    return "├" + "─" * width + "┤"

def _box_bot(width):
    return "└" + "─" * width + "┘"

def _box_row(text, width):
    return "│" + text.ljust(width) + "│"

def _box_sep(widths, left="├", mid="┬", right="┤", fill="─"):
    return left + mid.join(fill * w for w in widths) + right

def print_banner(title):
    """Print a boxed banner."""
    w = 60
    print()
    print(_box_top(w))
    print(_box_row(f"  {title}", w))
    print(_box_bot(w))
    print()

def print_table(title, headers, rows, col_widths=None):
    """Print a clean formatted table with box-drawing characters."""
    if not rows:
        print(f"  {title}: (empty)")
        return

    # Auto-calculate widths
    if col_widths is None:
        col_widths = []
        for i, h in enumerate(headers):
            max_w = len(str(h))
            for row in rows:
                if i < len(row):
                    max_w = max(max_w, len(str(row[i])))
            col_widths.append(min(max_w + 2, 42))

    total_w = sum(col_widths) + len(col_widths) - 1

    print(f"  {title}")
    print("  " + _box_sep(col_widths, "┌", "┬", "┐"))

    # Header
    header_str = ""
    for i, h in enumerate(headers):
        header_str += str(h).center(col_widths[i])
        if i < len(headers) - 1:
            header_str += "│"
    print("  │" + header_str + "│")
    print("  " + _box_sep(col_widths, "├", "┼", "┤"))

    # Rows
    for row in rows:
        row_str = ""
        for i, val in enumerate(row):
            s = str(val)
            w = col_widths[i] if i < len(col_widths) else 20
            if len(s) > w - 2:
                s = s[:w - 3] + "…"
            row_str += f" {s}".ljust(w)
            if i < len(row) - 1:
                row_str += "│"
        print("  │" + row_str + "│")

    print("  " + _box_sep(col_widths, "└", "┴", "┘"))
    print()

def print_kv(pairs, indent=2):
    """Print key-value pairs aligned."""
    if not pairs:
        return
    max_k = max(len(str(k)) for k, v in pairs)
    for k, v in pairs:
        print(" " * indent + f"  {str(k).ljust(max_k)}  {v}")


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
    table_rows = []
    for key, pattern in INPUT_FILES.items():
        matches = list(input_dir.glob(pattern))
        matches = [f for f in matches if not f.name.startswith("~$")]
        if matches:
            newest = max(matches, key=lambda f: f.stat().st_mtime)
            found[key] = newest
            size_kb = newest.stat().st_size / 1024
            table_rows.append((key, newest.name, f"{size_kb:.0f} KB", "found"))
        else:
            table_rows.append((key, pattern, "—", "missing"))

    print_table("Input Files",
                ["Source", "File", "Size", "Status"],
                table_rows,
                col_widths=[22, 42, 10, 10])
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
    if not isinstance(val, str):
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

    log(f"  {len(df.columns)} columns after cleanup")

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
                decoded_upper = decoded.upper()
                if decoded_upper.startswith(prefix.upper()) and suffix.upper() in decoded_upper:
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

    log(f"  {len(df.columns)} columns mapped to output schema")

    # Strip HTML from rich text fields
    for col in ("activity_description", "bod_geb"):
        if col in df.columns:
            df[col] = df[col].apply(_strip_html)

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

    # Parse tracking_id into components
    # Format: CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL
    # e.g.    QRREP-0000058-240709-0000060-EMI
    if "tracking_id" in df.columns:
        parts = df["tracking_id"].str.split("-", expand=True)
        if parts.shape[1] >= 5:
            df["tracking_cluster_id"] = parts[0]
            df["tracking_pack_number"] = parts[1]
            df["tracking_pub_date"] = parts[2]
            df["tracking_activity_number"] = parts[3]
            df["tracking_channel_abbr"] = parts[4]
            # Communication pack ID = cluster + pack number
            df["tracking_pack_id"] = parts[0] + "-" + parts[1]
        elif parts.shape[1] >= 1:
            # Partial tracking IDs — extract what we can
            df["tracking_cluster_id"] = parts[0]
            if parts.shape[1] >= 2:
                df["tracking_pack_number"] = parts[1]
                df["tracking_pack_id"] = parts[0] + "-" + parts[1]
            if parts.shape[1] >= 5:
                df["tracking_channel_abbr"] = parts[4]

    # Computed columns for executive dashboard
    if "start_date" in df.columns and "created" in df.columns:
        df["planning_lead_days"] = (
            df["start_date"] - df["created"]
        ).dt.total_seconds() / 86400
        df["planning_lead_days"] = df["planning_lead_days"].round(0).astype("Int64")

    if "start_date" in df.columns and "end_date" in df.columns:
        df["activity_duration_days"] = (
            df["end_date"] - df["start_date"]
        ).dt.total_seconds() / 86400
        df["activity_duration_days"] = df["activity_duration_days"].round(0).astype("Int64")

    if "start_date" in df.columns:
        valid = df["start_date"].notna()
        df.loc[valid, "quarter"] = (
            df.loc[valid, "start_date"].dt.year.astype(str)
            + "-Q"
            + df.loc[valid, "start_date"].dt.quarter.astype(str)
        )
        df.loc[valid, "year_month"] = df.loc[valid, "start_date"].dt.strftime("%Y-%m")

    return df


# ---------------------------------------------------------------------------
# DuckDB + Parquet output
# ---------------------------------------------------------------------------

def write_table(df, table_name, parquet_name, full_refresh=False):
    """Write a DataFrame to Parquet, DuckDB table, and JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Parquet — delete stale file first to avoid "bad file descriptor" on Windows
    # (DuckDB or OneDrive sync can hold the old file open)
    parquet_path = OUTPUT_DIR / f"{parquet_name}.parquet"
    if parquet_path.exists():
        try:
            parquet_path.unlink()
        except OSError:
            import time, gc
            gc.collect()
            time.sleep(0.5)
            parquet_path.unlink()
    df.to_parquet(parquet_path, index=False)

    # DuckDB
    if full_refresh and DB_PATH.exists():
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
        schema = con.execute(f"DESCRIBE {table_name}").fetchall()
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

    # Summary output
    parquet_kb = parquet_path.stat().st_size / 1024
    json_kb = json_path.stat().st_size / 1024

    print_table(
        f"Output: {table_name} ({row_count} rows, {len(schema)} columns)",
        ["Column", "Type", "Non-Null", "Sample"],
        [
            (
                col_name,
                col_type,
                str(df[col_name].notna().sum()) if col_name in df.columns else "—",
                str(df[col_name].dropna().iloc[0])[:30]
                    if col_name in df.columns and df[col_name].notna().any() else "—",
            )
            for col_name, col_type, *_ in schema
        ],
        col_widths=[30, 16, 10, 32],
    )
    print_kv([
        ("Parquet", f"{parquet_path.name}  ({parquet_kb:.0f} KB)"),
        ("JSON", f"{json_path.name}  ({json_kb:.0f} KB)"),
        ("DuckDB", f"{DB_PATH.name} → {table_name}"),
    ])


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

    log(f"  {len(df.columns)} columns after cleanup")

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

    log(f"  {len(df.columns)} columns mapped to output schema")

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


def transform_channels(df):
    """Transform InternalChannels CSV.

    Keeps: ID -> channel_id, Title -> channel_name, field_1 -> channel_abbr.
    The channel_abbr matches the suffix after the last '-' in tracking_id.
    """
    df.columns = [c.strip() for c in df.columns]

    rename = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower == "id":
            rename[col] = "channel_id"
        elif lower == "title":
            rename[col] = "channel_name"
        elif lower == "field_1" or lower == "field 1":
            rename[col] = "channel_abbr"

    df = df.rename(columns=rename)
    keep = [c for c in ("channel_id", "channel_name", "channel_abbr") if c in df.columns]
    df = df[keep]

    log(f"  Channels: {len(df)} rows, columns: {list(df.columns)}")
    return df


def transform_clusters(df):
    """Transform TrackingCluster CSV.

    Keeps: ID -> cluster_id, Title -> cluster_name, Abbreviation -> cluster_abbr.
    The cluster_abbr matches tracking_cluster_id (e.g. QRREP).
    """
    df.columns = [c.strip() for c in df.columns]

    rename = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower == "id":
            rename[col] = "cluster_id"
        elif lower == "title":
            rename[col] = "cluster_name"
        elif lower == "abbreviation":
            rename[col] = "cluster_abbreviation"

    df = df.rename(columns=rename)
    keep = [c for c in ("cluster_id", "cluster_name", "cluster_abbreviation") if c in df.columns]
    df = df[keep]

    log(f"  Clusters: {len(df)} rows, columns: {list(df.columns)}")
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
                    decoded_upper = decoded.upper()
                    if decoded_upper.startswith(prefix.upper()) and suffix.upper() in decoded_upper:
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

    # Build table rows
    table_rows = []
    mapped_count = 0
    unmapped_count = 0

    for key in sorted_cols:
        row = all_rows[key]
        clean = row["clean"] or ""

        presence = []
        for src in sources:
            presence.append("\u2713" if src in row["sources"] else "\u2014")

        if clean:
            mapped_count += 1
        else:
            unmapped_count += 1

        table_rows.append((key, clean, *presence))

    # Shorter display labels for readability
    display_labels = {
        "internal":         "INT",
        "external":         "EXT",
        "internal_archive": "INT arch",
        "external_archive": "EXT arch",
    }
    headers = ["Column", "Mapped To"] + [display_labels.get(s, s) for s in sources]
    col_widths = [28, 24] + [10] * len(sources)
    print_table("Column Comparison", headers, table_rows, col_widths)

    # Summary
    in_both = sum(1 for k in sorted_cols if len(all_rows[k]["sources"]) == len(sources))
    summary_pairs = [
        ("Total columns", str(len(sorted_cols))),
        ("In all files", str(in_both)),
    ]
    for src in sources:
        only = sum(1 for k in sorted_cols if set(all_rows[k]["sources"].keys()) == {src})
        total = sum(1 for k in sorted_cols if src in all_rows[k]["sources"])
        summary_pairs.append((f"{src} only", f"{only}  (total: {total})"))
    summary_pairs.append(("Mapped", str(mapped_count)))
    summary_pairs.append(("Unmapped (dropped)", str(unmapped_count)))
    print_kv(summary_pairs)
    print()


def print_data_preview(df, max_rows=20, title="DATA"):
    """Print a pretty preview of the transformed data."""
    # Per-column width overrides for schema sample values
    SAMPLE_WIDTHS = {
        "lead": 42, "lead_team": 42, "lead_email": 42,
        "activity_name": 42, "channel": 32,
        "start_date": 22, "end_date": 22, "launch_date": 22,
        "short_description": 42,
    }

    # Schema table
    schema_rows = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        non_null = df[col].notna().sum()
        sample_w = SAMPLE_WIDTHS.get(col, 30)
        sample = ""
        first_valid = df[col].dropna().head(1)
        if not first_valid.empty:
            sample = str(first_valid.iloc[0])[:sample_w]
        schema_rows.append((col, dtype, str(non_null), sample))

    max_sample = max(len(r[3]) for r in schema_rows) + 2 if schema_rows else 32
    print_table(
        f"{title} Schema ({len(df)} rows, {len(df.columns)} columns)",
        ["Column", "Type", "Non-Null", "Sample"],
        schema_rows,
        col_widths=[30, 16, 10, max(32, min(max_sample, 44))],
    )

    # Per-column width overrides for data sample
    DATA_COL_WIDTHS = {
        "activity_name": 30, "channel": 22,
        "start_date": 22, "end_date": 22,
        "lead": 28, "lead_team": 28,
    }

    # Sample rows table
    display_cols = [c for c in df.columns if c != "source_type"][:6]
    if "source_type" in df.columns:
        display_cols.append("source_type")

    sample_rows = []
    col_widths = []
    for c in display_cols:
        w = DATA_COL_WIDTHS.get(c, min(20, max(len(c) + 2, 10)))
        col_widths.append(w)

    for _, row in df.head(max_rows).iterrows():
        sample_rows.append(tuple(
            str(row.get(c, ""))[:col_widths[i] - 2]
            for i, c in enumerate(display_cols)
        ))

    if sample_rows:
        print_table(
            f"{title} Sample (first {min(max_rows, len(df))} rows)",
            display_cols,
            sample_rows,
            col_widths=col_widths,
        )
    if len(df) > max_rows:
        log(f"  ... and {len(df) - max_rows} more rows")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    preview = "--preview" in sys.argv
    full_refresh = "--full-refresh" in sys.argv

    print_banner("CPLAN Data Pipeline")

    mode = "preview" if preview else ("full refresh" if full_refresh else "incremental")
    log(f"Mode: {mode}")

    # Find input
    input_dir = find_input_dir()
    files = find_input_files(input_dir)

    if not files:
        print()
        log("ERROR: No input files found.")
        print_kv([
            ("Input dir", str(input_dir)),
            ("Expected", ", ".join(INPUT_FILES.values())),
        ])
        print()
        sys.exit(1)

    if full_refresh and DB_PATH.exists():
        DB_PATH.unlink()
        wal_path = DB_PATH.with_suffix(".db.wal")
        if wal_path.exists():
            wal_path.unlink()
        log("Deleted existing database (full refresh)")

    # --- Communication activities (internal + external, active + archive) ---
    ACTIVITY_KEYS = {
        "internal":         ("internal", False),
        "external":         ("external", False),
        "internal_archive": ("internal", True),
        "external_archive": ("external", True),
    }
    activity_files = {k: v for k, v in files.items() if k in ACTIVITY_KEYS}
    frames = []
    raw_columns = {}
    for key, path in activity_files.items():
        source_type, is_archived = ACTIVITY_KEYS[key]
        log(f"Reading {path.name}...")
        df = read_csv_auto(path)
        log(f"  {key}: {len(df)} rows, {len(df.columns)} columns")
        raw_columns[key] = [c.strip() for c in df.columns]
        df = transform(df, source_type=source_type)
        df["is_archived"] = is_archived
        frames.append(df)

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        log(f"Combined activities: {len(combined)} rows")

        # Deduplicate: active + archive lists can overlap.
        # Keep the most recently modified row per tracking_id.
        if "tracking_id" in combined.columns:
            before = len(combined)
            sort_col = "modified" if "modified" in combined.columns else None
            if sort_col:
                combined = combined.sort_values(sort_col, ascending=False, na_position="last")
            combined = combined.drop_duplicates(subset=["tracking_id"], keep="first")
            combined = combined.reset_index(drop=True)
            dupes = before - len(combined)
            if dupes:
                log(f"  Removed {dupes} duplicate rows (by tracking_id)")

        if preview:
            print_column_comparison(raw_columns, activity_files)
            print_data_preview(combined)
        else:
            write_table(combined, "communications", "communications", full_refresh=full_refresh)

    # --- Communication packs ---
    if "packs" in files:
        log(f"Reading {files['packs'].name}...")
        packs_df = read_csv_auto(files["packs"])
        log(f"  packs: {len(packs_df)} rows, {len(packs_df.columns)} columns")
        packs_df = transform_packs(packs_df)

        if preview:
            print_data_preview(packs_df, title="PACKS")
        else:
            write_table(packs_df, "packs", "packs", full_refresh=full_refresh)

    # --- Channels lookup (internal + external) ---
    channel_frames = []
    for key in ("internal_channels", "external_channels"):
        if key in files:
            source = key.replace("_channels", "")
            log(f"Reading {files[key].name}...")
            ch_df = read_csv_auto(files[key])
            log(f"  {key}: {len(ch_df)} rows, {len(ch_df.columns)} columns")
            ch_df = transform_channels(ch_df)
            ch_df["source_type"] = source
            channel_frames.append(ch_df)

    if channel_frames:
        channels_df = pd.concat(channel_frames, ignore_index=True)
        log(f"Combined channels: {len(channels_df)} rows")

        if preview:
            print_data_preview(channels_df, title="CHANNELS")
        else:
            write_table(channels_df, "channels", "channels", full_refresh=full_refresh)

    # --- Tracking clusters lookup ---
    if "clusters" in files:
        log(f"Reading {files['clusters'].name}...")
        clusters_df = read_csv_auto(files["clusters"])
        log(f"  clusters: {len(clusters_df)} rows, {len(clusters_df.columns)} columns")
        clusters_df = transform_clusters(clusters_df)

        if preview:
            print_data_preview(clusters_df, title="CLUSTERS")
        else:
            write_table(clusters_df, "clusters", "clusters", full_refresh=full_refresh)

    # --- Final summary ---
    if not preview:
        outputs = []
        for name in ("communications", "packs", "channels", "clusters"):
            p = OUTPUT_DIR / f"{name}.parquet"
            if p.exists():
                kb = p.stat().st_size / 1024
                outputs.append((name, f"{kb:.0f} KB"))
        db_kb = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0

        print()
        print_table("Pipeline Complete",
                    ["Output", "Size"],
                    outputs + [("cplan.db", f"{db_kb:.0f} KB")],
                    col_widths=[24, 14])
        log("Done.")


if __name__ == "__main__":
    main()
