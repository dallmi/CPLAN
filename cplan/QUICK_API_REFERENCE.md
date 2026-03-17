# CPLAN API Quick Reference - Unlimited Records Support

## 🚀 Key Feature: No 5K Limit!

CPLAN bypasses SharePoint's 5,000 item view limit using Microsoft Graph API.
**You can fetch MILLIONS of records!**

---

## 📊 Get Record Count (Super Fast)

```bash
# Get total count without fetching data
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?count=true"

Response: { "total": 2485372 }  # 2.4 million items!

# With filters
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?count=true&status=PUBLISHED"
```

⚡ **Performance:** < 1 second even for millions of records

---

## 📄 Paginated Fetch (Recommended)

```bash
# Fetch first page (1000 items)
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?limit=1000"

Response:
{
  "data": [...1000 items...],
  "pagination": {
    "total": 2500000,
    "count": 1000,
    "hasMore": true,
    "skipToken": "https://graph.microsoft.com/v1.0/..."
  }
}

# Fetch next page
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?skipToken=ENCODED_TOKEN"
```

---

## 🔍 Search with Filters

```bash
# Search by status and type
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?status=PUBLISHED&type=ANNOUNCEMENT&limit=100"

# Search by priority
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?priority=HIGH&limit=500"

# Combine filters
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?status=PUBLISHED&type=NEWSLETTER&priority=MEDIUM"
```

---

## 📥 Fetch ALL Records (Background Jobs Only)

```bash
# ⚠️ WARNING: Can take minutes for millions of records
# Only use for background jobs, exports, analytics

curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?fetchAll=true"

# With filters (recommended to reduce dataset)
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?fetchAll=true&status=PUBLISHED"
```

**Use Cases:**
- ✅ Background data exports
- ✅ Analytics calculations
- ✅ Scheduled reports
- ✅ Data migration

**Never Use For:**
- ❌ User-facing API calls
- ❌ Real-time requests
- ❌ Frontend pagination

---

## 🔨 Create Communication

```bash
curl -X POST \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Q1 2025 Strategic Update",
    "content": "Full content here...",
    "type": "ANNOUNCEMENT",
    "priority": "HIGH",
    "status": "DRAFT",
    "ownerId": "user123",
    "ownerEmail": "john.doe@company.com",
    "ownerName": "John Doe",
    "channels": ["EMAIL", "TEAMS", "INTRANET"],
    "tags": ["Q1", "Strategy", "Important"]
  }' \
  https://your-domain/api/communications-lists

Response:
{
  "id": "123",
  "trackingId": "COM-1A2B3C-XYZ456",
  "title": "Q1 2025 Strategic Update",
  ...
}
```

---

## ✏️ Update Communication

```bash
curl -X PATCH \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "PUBLISHED",
    "publishDate": "2025-01-20T10:00:00Z"
  }' \
  https://your-domain/api/communications-lists/COM-1A2B3C-XYZ456
```

---

## 🗑️ Archive Communication

```bash
curl -X DELETE \
  -H "X-API-Key: your-key" \
  https://your-domain/api/communications-lists/COM-1A2B3C-XYZ456

# Sets status to ARCHIVED (doesn't actually delete)
```

---

## 📝 Get Single Communication

```bash
# By tracking ID
curl -H "X-API-Key: your-key" \
  https://your-domain/api/communications-lists/COM-1A2B3C-XYZ456

# By item ID
curl -H "X-API-Key: your-key" \
  https://your-domain/api/communications-lists/123
```

---

## 🔄 Pagination Patterns

### Pattern 1: Load More (Infinite Scroll)

```javascript
let allItems = [];
let skipToken = null;

async function loadMore() {
  const url = skipToken
    ? `/api/communications-lists?skipToken=${encodeURIComponent(skipToken)}`
    : `/api/communications-lists?limit=100`;

  const response = await fetch(url, {
    headers: { 'X-API-Key': 'your-key' }
  });

  const data = await response.json();
  allItems.push(...data.data);

  if (data.pagination.hasMore) {
    skipToken = data.pagination.skipToken;
    // Show "Load More" button
  }
}
```

### Pattern 2: Fetch All (Background)

```javascript
async function fetchAllInBackground() {
  const response = await fetch(
    '/api/communications-lists?fetchAll=true&status=PUBLISHED',
    { headers: { 'X-API-Key': 'your-key' } }
  );

  const data = await response.json();
  console.log(`Fetched ${data.data.length} communications`);

  // Export to CSV, generate report, etc.
  return data.data;
}
```

### Pattern 3: Loop Through Pages

```javascript
async function processAllPages() {
  let hasMore = true;
  let skipToken = null;
  let total = 0;

  while (hasMore) {
    const url = skipToken
      ? `/api/communications-lists?skipToken=${encodeURIComponent(skipToken)}`
      : `/api/communications-lists?limit=1000`;

    const response = await fetch(url, {
      headers: { 'X-API-Key': 'your-key' }
    });

    const data = await response.json();

    // Process this page
    total += data.data.length;
    console.log(`Processed ${total} of ${data.pagination.total}`);

    hasMore = data.pagination.hasMore;
    skipToken = data.pagination.skipToken;
  }

  return total;
}
```

---

## ⚡ Performance Tips

### 1. Use Appropriate Page Sizes

```bash
# Real-time user requests
?limit=100

# Background processing
?limit=1000

# Default (good balance)
?limit=1000
```

### 2. Always Use Filters

```bash
# ✅ GOOD: Filtered query
?status=PUBLISHED&type=ANNOUNCEMENT

# ❌ BAD: No filters (fetches everything)
?limit=5000
```

### 3. Get Count First

```bash
# Check size before fetching
GET /api/communications-lists?count=true&status=PUBLISHED

# If count is small, fetch all
# If count is huge, use pagination
```

---

## 🎯 Common Scenarios

### Scenario 1: Display Recent 100 Items

```bash
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?limit=100"
```

### Scenario 2: Export All Published

```bash
# Background job only!
curl -H "X-API-Key: your-key" \
  "https://your-domain/api/communications-lists?fetchAll=true&status=PUBLISHED" \
  > export.json
```

### Scenario 3: Get Statistics

```bash
# Total count
curl "https://your-domain/api/communications-lists?count=true"

# Published count
curl "https://your-domain/api/communications-lists?count=true&status=PUBLISHED"

# Draft count
curl "https://your-domain/api/communications-lists?count=true&status=DRAFT"
```

### Scenario 4: Search by Date Range (Future Enhancement)

```bash
# Coming soon...
curl "https://your-domain/api/communications-lists?dateFrom=2025-01-01&dateTo=2025-12-31"
```

---

## 🔐 Authentication

All API calls require the `X-API-Key` header:

```bash
-H "X-API-Key: your-secret-api-key"
```

Set `API_SECRET_KEY` in `.env.local`

---

## 📊 Response Format

### Success (List)

```json
{
  "data": [
    {
      "id": "123",
      "trackingId": "COM-1A2B3C-XYZ456",
      "title": "Communication Title",
      "status": "PUBLISHED",
      "priority": "HIGH",
      "type": "ANNOUNCEMENT",
      "channels": ["EMAIL", "TEAMS"],
      "tags": ["Important"],
      "createdAt": "2025-01-15T10:00:00Z",
      "updatedAt": "2025-01-16T14:30:00Z"
    }
  ],
  "pagination": {
    "total": 2500000,
    "count": 1000,
    "hasMore": true,
    "skipToken": "https://graph.microsoft.com/..."
  }
}
```

### Success (Count)

```json
{
  "total": 2485372
}
```

### Error

```json
{
  "error": "Unauthorized",
  "status": 401
}
```

---

## 🎓 Learn More

- [Full Pagination Guide](./PAGINATION_GUIDE.md) - Detailed documentation
- [Microsoft Lists Setup](./MICROSOFT_LISTS_SETUP.md) - Initial setup
- [README](./README.md) - Getting started

---

**Remember:** CPLAN has NO 5K limit! Fetch millions of records effortlessly. 🚀