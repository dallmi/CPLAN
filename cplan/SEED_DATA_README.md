# Seed Mock Data - Quick Start

## 🎯 What This Does

Creates **50+ realistic enterprise communications** in your Microsoft Lists:

- 📊 Quarterly financial results (6 communications)
- 📋 Policy updates (6 communications)
- 💼 Leadership messages (6 communications)
- 🎉 Event announcements (6 communications)
- 📰 Monthly newsletters (6 communications)
- ⚠️ Urgent alerts (6 communications)
- 🎓 Training announcements (6 communications)
- 💰 Benefits updates (6 communications)

**Plus:**
- 3 reusable templates
- 3 communication packs
- Realistic users, tags, dates, and content

---

## ✅ Prerequisites

Before running the seed script, you MUST:

1. ✅ **Configure `.env.local`** with all your Azure AD and SharePoint details
2. ✅ **Create Microsoft Lists** using the PowerShell script
3. ✅ **Verify connection** - server should run without errors

See [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md) for setup instructions.

---

## 🚀 How to Run

### Step 1: Make sure your configuration is complete

```bash
# Open .env.local and verify all values are filled in
cat .env.local

# Look for placeholders like "your-app-client-id" - these must be replaced!
```

### Step 2: Start the development server (optional but recommended)

```bash
npm run dev
# Let it run in a separate terminal window
# This helps verify your configuration works
```

### Step 3: Run the seed script

```bash
# In a new terminal window
cd /Users/micha/Documents/Arbeit/CPLAN/cplan
npm run seed-data
```

---

## 📊 What You'll See

```
🌱 Starting to seed mock data...

📝 Creating QUARTERLY_RESULTS communications...
📝 Creating POLICY_UPDATES communications...
📝 Creating LEADERSHIP_MESSAGES communications...
📝 Creating EVENTS communications...
📝 Creating NEWSLETTERS communications...
📝 Creating URGENT_ALERTS communications...
📝 Creating TRAINING communications...
📝 Creating BENEFITS communications...

✅ Generated 48 communications

📤 Uploading to Microsoft Lists...

✓ [1/48] Created: Q1 2025 Financial Results Announced
✓ [2/48] Created: Q2 2025 Earnings Beat Expectations
✓ [3/48] Created: Q3 2025 Quarterly Performance Update
...

================================================================================
📊 SEED SUMMARY
================================================================================
✅ Successfully uploaded: 48 communications
❌ Failed uploads: 0 communications
📈 Success rate: 100.0%
================================================================================

📋 Creating templates...
✓ Created template: Quarterly Results Template
✓ Created template: Policy Update Template
✓ Created template: Event Invitation Template

📦 Creating communication packs...
✓ Created pack: Q1 2025 Communications
✓ Created pack: Policy Updates 2025
✓ Created pack: Leadership Messages

🎉 Mock data seeding complete!

✅ All done!
```

**Time:** ~2-3 minutes (depending on network speed)

---

## 📁 What Gets Created

### Communications (48 items)

**Status Distribution:**
- 📤 Published: ~24 items (50%)
- 📅 Scheduled: ~7 items (15%)
- 📝 Draft: ~10 items (20%)
- 🔍 In Review: ~5 items (10%)
- 📦 Archived: ~2 items (5%)

**Sample Communications:**

| Title | Type | Priority | Status | Channels |
|-------|------|----------|--------|----------|
| Q1 2025 Financial Results Announced | Announcement | High | Published | Email, Intranet, Teams |
| Updated Remote Work Policy - Effective March 2025 | Policy | Medium | Published | Email, Intranet |
| CEO Message: Strategic Vision for 2025 | Announcement | High | Scheduled | Email, Teams, Signage |
| System Maintenance Tonight: 11 PM - 2 AM | Alert | Urgent | Published | Email, SMS, Teams, Mobile |
| Monthly Digest: January 2025 | Newsletter | Low | Draft | Email, Intranet |

**Realistic Features:**
- ✅ Unique tracking IDs (COM-XXXXX-YYYYY)
- ✅ Realistic publish dates (past 6 months)
- ✅ Scheduled dates (next 3 months)
- ✅ Multiple channels per communication
- ✅ Relevant tags (Urgent, Company-Wide, Q1 2025, etc.)
- ✅ Assigned to different departments
- ✅ Professional content and formatting

### Templates (3 items)

1. **Quarterly Results Template**
   - Variables: QUARTER, YEAR, DETAILS
   - Category: Financial

2. **Policy Update Template**
   - Variables: POLICY_NAME, DATE
   - Category: HR

3. **Event Invitation Template**
   - Variables: EVENT_NAME, DATE, TIME, LOCATION
   - Category: Events

### Communication Packs (3 items)

1. **Q1 2025 Communications** - All Q1 related comms
2. **Policy Updates 2025** - Policy changes
3. **Leadership Messages** - Executive communications

---

## 🔧 Troubleshooting

### Error: "Invalid client secret" or "Unauthorized"

**Problem:** Azure AD credentials not configured

**Solution:**
```bash
# Check .env.local has real values (not placeholders)
cat .env.local | grep AZURE_AD

# Should show actual IDs, not "your-app-client-id"
```

See [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md) Step 1

### Error: "Site not found"

**Problem:** SharePoint site doesn't exist or ID is wrong

**Solution:**
```bash
# Verify site exists
# Visit: https://yourtenant.sharepoint.com/sites/CPLAN

# Get correct Site ID using Graph Explorer or PowerShell
```

See [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md) Step 2

### Error: "List not found"

**Problem:** Microsoft Lists haven't been created

**Solution:**
```powershell
# Run the PowerShell script to create lists
./setup-lists.ps1 -SiteUrl "https://yourtenant.sharepoint.com/sites/CPLAN"
```

See [MICROSOFT_LISTS_SETUP.md](./MICROSOFT_LISTS_SETUP.md)

### Error: "Cannot find module"

**Problem:** Dependencies not installed

**Solution:**
```bash
npm install
```

### Partial Success (some items fail)

**Example:**
```
✅ Successfully uploaded: 35 communications
❌ Failed uploads: 13 communications
```

**Common causes:**
- Network timeouts
- API rate limiting
- Malformed data

**Solution:**
```bash
# Just run the script again
# It will create the missing items
npm run seed-data
```

---

## 🧪 Testing After Seeding

### 1. Check Dashboard

```bash
# Visit dashboard
http://localhost:3000/dashboard

# Should show:
# - Total communications count (48+)
# - Published, Scheduled, Draft counts
# - Recent communications list
```

### 2. Check Calendar

```bash
# Visit calendar
http://localhost:3000/calendar

# Should show:
# - Scheduled communications as calendar events
# - Color-coded by priority
# - Multiple items across different dates
```

### 3. Check via API

```bash
# Count all communications
curl "http://localhost:3000/api/communications-lists?count=true" \
  -H "X-API-Key: YOUR_API_SECRET_KEY"

# Should return: {"total": 48} or more

# List published communications
curl "http://localhost:3000/api/communications-lists?status=PUBLISHED&limit=10" \
  -H "X-API-Key: YOUR_API_SECRET_KEY"
```

### 4. Check SharePoint Lists Directly

```
https://yourtenant.sharepoint.com/sites/CPLAN

Navigate to:
- Communications list (should have 48+ items)
- Templates list (should have 3 items)
- Packs list (should have 3 items)
```

---

## 🔁 Re-running the Script

**Safe to re-run?** ✅ Yes!

Each run creates NEW communications (won't duplicate).

**To start fresh:**

1. **Option A:** Delete items in SharePoint Lists manually
2. **Option B:** Delete and recreate lists:
   ```powershell
   ./setup-lists.ps1 -SiteUrl "https://yourtenant.sharepoint.com/sites/CPLAN"
   ```

---

## 📊 Customizing Mock Data

Want different data? Edit the script:

```typescript
// File: scripts/seed-mock-data.ts

// Add more communication types
const COMMUNICATION_TYPES = {
  MY_CUSTOM_TYPE: {
    type: 'ANNOUNCEMENT',
    priority: 'HIGH',
    titles: [
      'My Custom Title 1',
      'My Custom Title 2',
    ],
    channels: ['EMAIL', 'TEAMS'],
  },
  // ... existing types
};

// Add more users
const MOCK_USERS = [
  { id: 'user-008', name: 'Your Name', email: 'you@company.com', dept: 'Your Dept' },
  // ... existing users
];

// Add more tags
const TAGS = [
  'CustomTag1', 'CustomTag2',
  // ... existing tags
];
```

Then run:
```bash
npm run seed-data
```

---

## 🎯 Next Steps

After seeding:

1. ✅ **Explore the Dashboard** - See statistics and recent items
2. ✅ **Try the Calendar** - Visual view of scheduled communications
3. ✅ **Create New Communication** - Test the form
4. ✅ **Search & Filter** - Test pagination and filtering
5. ✅ **Test API Endpoints** - Try the REST API

---

## 📚 Related Documentation

- [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md) - Setup instructions
- [MICROSOFT_LISTS_SETUP.md](./MICROSOFT_LISTS_SETUP.md) - Creating lists
- [PAGINATION_GUIDE.md](./PAGINATION_GUIDE.md) - Handling large datasets
- [QUICK_API_REFERENCE.md](./QUICK_API_REFERENCE.md) - API examples

---

**Ready to seed?** Run: `npm run seed-data` 🚀