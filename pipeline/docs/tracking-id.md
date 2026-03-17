# Tracking ID Structure

The tracking ID is a unique, system-generated identifier assigned to every communication activity (email, article, banner, event, etc.) entered in CPlan. It consists of 32 characters and encodes the full hierarchy.

## Format

```
QRREP-0000058-240709-0000060-EMI
  |       |       |       |     |
  |       |       |       |     +-- Communication channel (abbreviation)
  |       |       |       +-------- Communication activity number
  |       |       +---------------- Publication date (YYMMDD)
  |       +------------------------ Communication pack unique number
  +-------------------------------- Tracking cluster ID (abbreviation)
  |_______________|
   Communication pack ID
```

## Components

| Segment | Column | Example | Description |
|---------|--------|---------|-------------|
| 1st | `tracking_cluster_id` | `QRREP` | Tracking cluster abbreviation |
| 2nd | `tracking_pack_number` | `0000058` | Communication pack sequence number |
| 3rd | `tracking_pub_date` | `240709` | Publication date in YYMMDD format |
| 4th | `tracking_activity_number` | `0000060` | Activity sequence number |
| 5th | `tracking_channel_abbr` | `EMI` | Channel abbreviation (e.g. EMI=Email, EVT=Event) |
| 1st+2nd | `tracking_pack_id` | `QRREP-0000058` | Full communication pack identifier |

## Joins

- `tracking_channel_abbr` joins to `channels.channel_abbr` (with matching `source_type`)
- `tracking_cluster_id` joins to `clusters.cluster_abbreviation`
- `tracking_pack_id` joins to `packs.cpid`

## Purpose

The tracking ID allows communication managers and publishers to combine data into one single dashboard and analyze performance across channels. It links every activity back to its communication pack and tracking cluster.
