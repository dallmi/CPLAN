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
import json
import os
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
        return val

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


def _extract_sp_value(obj):
    """Extract the most useful value from a single SP lookup object."""
    # Person field
    if "DisplayName" in obj:
        return obj["DisplayName"]
    # Standard lookup / taxonomy
    if "Value" in obj:
        return str(obj["Value"])
    # Fallback to Label (taxonomy)
    if "Label" in obj:
        return obj["Label"]
    return ""


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
COLUMN_MAP = {
    "Tracking_x0020_ID":                             "tracking_id",
    "Title":                                         "title",
    "Activity_x0020_":                               "activity",
    "Target_x0020_audience":                         "target_audience",
    "Extended_x0020_audience_x0020_":                "extended_audience",
    "Business_x0020_Division_x0020_x_0":             "business_division",
    "Business_x0020_Area_x0020_x_0002":              "business_area",
    "Region_x0020_x0021_x0020_Local":                "region",
    "Channel":                                       "channel",
    "Lead":                                          "lead",
    "Lead_x0020_Team":                               "lead_team",
    "Start_x0020_date_x0020_x0028_p":                "start_date",
    "End_x0020_date":                                "end_date",
    "News_x0020_digest":                             "news_digest",
    "Priority":                                      "priority",
    "Strategic_x0020_Objectives":                    "strategic_objectives",
    "Communication_x0020_x0028_s":                   "communication_ref",
    "Communication_x0020_pack_x0020_x":              "communication_pack",
    "Created":                                       "created",
    "Modified":                                      "modified",
    "Author":                                        "author",
    "Audience":                                      "audience",
}

# Columns that contain SP lookup JSON and need Value extraction
SP_LOOKUP_COLUMNS = {
    "target_audience", "extended_audience", "business_division",
    "business_area", "region", "channel", "lead", "lead_team",
    "priority", "strategic_objectives", "communication_ref",
    "communication_pack", "author", "audience",
}

# Columns where we also want to extract the email from Claims
SP_PERSON_COLUMNS = {"lead", "author"}

# Date columns (DD.MM.YYYY HH:MM format from SharePoint)
DATE_COLUMNS = {"start_date", "end_date", "created", "modified"}


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def _find_column(df_columns, partial_name):
    """Find a DataFrame column that starts with the given partial name.

    SharePoint column names in Power Automate exports can be truncated
    or have varying suffixes. This does a prefix match.
    """
    for col in df_columns:
        if col.startswith(partial_name) or col == partial_name:
            return col
    return None


def transform(df, source_type):
    """Apply transformations to a raw DataFrame.

    1. Decode SP-encoded column names
    2. Map to clean column names via prefix matching
    3. Extract values from SP lookup JSON fields
    4. Parse dates
    5. Tag with source type
    """
    # Strip whitespace from column names
    df.columns = [c.strip() for c in df.columns]

    log(f"  Raw columns: {list(df.columns)}")

    # Build renamed DataFrame with clean column names
    rename_map = {}
    for sp_name, clean_name in COLUMN_MAP.items():
        matched_col = _find_column(df.columns, sp_name)
        if matched_col:
            rename_map[matched_col] = clean_name

    df = df.rename(columns=rename_map)

    # Keep only mapped columns + source_type, drop everything else
    keep = [c for c in rename_map.values() if c in df.columns]
    df = df[keep]

    log(f"  Mapped columns: {list(df.columns)}")

    # Extract person emails BEFORE lookup parsing (which replaces JSON with display names)
    for col in SP_PERSON_COLUMNS:
        if col in df.columns:
            df[f"{col}_email"] = df[col].apply(parse_sp_person_email)

    # Parse SP lookup JSON fields -> extract Value / DisplayName
    for col in SP_LOOKUP_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(parse_sp_lookup)

    # Parse dates — keep full datetime (date + time)
    # Formats seen: "DD.MM.YYYY HH:MM", "DD.MM.YYYY HH:MM:SS", ISO 8601
    for col in DATE_COLUMNS:
        if col in df.columns:
            raw = df[col].copy()
            # Try DD.MM.YYYY HH:MM first
            df[col] = pd.to_datetime(raw, format="%d.%m.%Y %H:%M", errors="coerce")
            # Retry with seconds
            mask = df[col].isna() & raw.notna()
            if mask.any():
                df.loc[mask, col] = pd.to_datetime(
                    raw[mask], format="%d.%m.%Y %H:%M:%S", errors="coerce"
                )
            # Fallback: let pandas infer (catches ISO 8601 etc.)
            mask = df[col].isna() & raw.notna()
            if mask.any():
                df.loc[mask, col] = pd.to_datetime(raw[mask], errors="coerce")

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

def write_outputs(df, full_refresh=False):
    """Write combined DataFrame to DuckDB and Parquet."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Parquet
    parquet_path = OUTPUT_DIR / "communications.parquet"
    df.to_parquet(parquet_path, index=False)
    log(f"Wrote {len(df)} rows to {parquet_path}")

    # DuckDB
    if full_refresh and DB_PATH.exists():
        DB_PATH.unlink()
        log("Deleted existing database (full refresh)")

    con = duckdb.connect(str(DB_PATH))
    try:
        if full_refresh:
            con.execute("DROP TABLE IF EXISTS communications")

        con.execute("""
            CREATE TABLE IF NOT EXISTS communications AS
            SELECT * FROM read_parquet(?)
        """, [str(parquet_path)])

        # If table already existed and we're not doing full refresh,
        # replace the data
        if not full_refresh:
            con.execute("DELETE FROM communications")
            con.execute("""
                INSERT INTO communications
                SELECT * FROM read_parquet(?)
            """, [str(parquet_path)])

        row_count = con.execute("SELECT COUNT(*) FROM communications").fetchone()[0]
        log(f"DuckDB: {row_count} rows in communications table")

        # Print schema
        schema = con.execute("DESCRIBE communications").fetchall()
        log("Schema:")
        for col_name, col_type, *_ in schema:
            log(f"  {col_name:<40} {col_type}")
    finally:
        con.close()

    # JSON for HTML dashboard
    json_path = OUTPUT_DIR / "communications.json"
    # Convert timestamps/dates to strings for JSON serialization
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

    # Read and transform each file
    frames = []
    for key, path in files.items():
        df = read_csv_auto(path)
        log(f"  {key}: {len(df)} rows, {len(df.columns)} columns")
        log(f"  Columns: {list(df.columns)}")
        df = transform(df, source_type=key)
        frames.append(df)

    # Combine
    combined = pd.concat(frames, ignore_index=True)
    log(f"Combined: {len(combined)} rows")

    if preview:
        log("\n--- Preview (first 20 rows) ---")
        print(combined.head(20).to_string(index=False))
        return

    # Write outputs
    write_outputs(combined, full_refresh=full_refresh)

    log("Done.")


if __name__ == "__main__":
    main()
