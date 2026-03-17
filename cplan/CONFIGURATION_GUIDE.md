# CPLAN Configuration Guide

## 📍 Where Configuration Lives

All configuration is in **ONE file**: `.env.local`

**Location:** `/Users/micha/Documents/Arbeit/CPLAN/cplan/.env.local`

---

## 🔐 Current Configuration Status

Your `.env.local` file currently has **placeholder values** that need to be replaced:

```env
# Microsoft 365 / Azure AD Configuration
AZURE_AD_CLIENT_ID=your-app-client-id              # ← REPLACE THIS
AZURE_AD_CLIENT_SECRET=your-app-client-secret      # ← REPLACE THIS
AZURE_AD_TENANT_ID=your-tenant-id                  # ← REPLACE THIS

# Microsoft Graph API
SHAREPOINT_SITE_ID=your-sharepoint-site-id         # ← REPLACE THIS
SHAREPOINT_SITE_URL=https://yourtenant.sharepoint.com/sites/CPLAN  # ← REPLACE THIS

# Microsoft Lists Configuration
COMMUNICATIONS_LIST_ID=your-communications-list-id  # ← REPLACE THIS
TEMPLATES_LIST_ID=your-templates-list-id            # ← REPLACE THIS
APPROVALS_LIST_ID=your-approvals-list-id            # ← REPLACE THIS
ACTIVITIES_LIST_ID=your-activities-list-id          # ← REPLACE THIS
METRICS_LIST_ID=your-metrics-list-id                # ← REPLACE THIS
PACKS_LIST_ID=your-packs-list-id                    # ← REPLACE THIS
TAGS_LIST_ID=your-tags-list-id                      # ← REPLACE THIS

# Authentication
NEXTAUTH_URL=http://localhost:3000                  # ✅ OK for development
NEXTAUTH_SECRET=your-secret-key-change-in-production  # ← GENERATE RANDOM

# API Security
API_SECRET_KEY=your-api-secret-key                  # ← GENERATE RANDOM

# Optional Features
OPENAI_API_KEY=your-openai-api-key                  # Optional - for AI features
POWER_AUTOMATE_WEBHOOK_URL=your-webhook-url         # Optional - for automation
```

---

## ⚙️ No UI for Configuration (Yet)

**Current State:**
- ❌ No admin UI for entering secrets
- ✅ Configuration via text file (`.env.local`)
- ✅ Environment variables loaded automatically by Next.js

**Why no UI?**
- Security: Secrets shouldn't be editable via web UI
- Enterprise: Secrets typically managed by DevOps/IT
- Standard: `.env` files are industry standard

**Future Enhancement:**
We could build an admin settings page for non-secret settings like:
- Feature flags
- UI preferences
- Email templates
- But NOT for secrets (Azure AD credentials, API keys)

---

## 📝 Step-by-Step Configuration

### Step 1: Set Up Azure AD App (15 minutes)

1. **Go to Azure Portal**
   ```
   https://portal.azure.com
   ```

2. **Navigate to Azure Active Directory** → **App registrations** → **New registration**

3. **Create App:**
   - Name: `CPLAN API`
   - Supported account types: `Single tenant`
   - Redirect URI: Leave blank (not needed for app-only auth)
   - Click **Register**

4. **Copy Values to `.env.local`:**
   - **Application (client) ID** → `AZURE_AD_CLIENT_ID`
   - **Directory (tenant) ID** → `AZURE_AD_TENANT_ID`

5. **Create Client Secret:**
   - Go to **Certificates & secrets** → **New client secret**
   - Description: `CPLAN Backend`
   - Expires: `24 months` (or per your policy)
   - Click **Add**
   - **COPY THE VALUE IMMEDIATELY** → `AZURE_AD_CLIENT_SECRET`
   - ⚠️ You can't see it again!

6. **Add API Permissions:**
   - Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions**
   - Add these permissions:
     - `Sites.ReadWrite.All`
     - `Sites.FullControl.All`
   - Click **Grant admin consent**

### Step 2: Create SharePoint Site (5 minutes)

1. **Go to SharePoint Admin Center**
   ```
   https://yourtenant-admin.sharepoint.com
   ```

2. **Create Site:**
   - Sites → Active sites → Create
   - Type: Team site or Communication site
   - Name: `CPLAN`
   - URL: `https://yourtenant.sharepoint.com/sites/CPLAN`

3. **Get Site ID:**

   **Option A: PowerShell**
   ```powershell
   Connect-PnPOnline -Url "https://yourtenant.sharepoint.com/sites/CPLAN" -Interactive
   Get-PnPSite | Select Id
   ```

   **Option B: Graph Explorer**
   ```
   GET https://graph.microsoft.com/v1.0/sites/yourtenant.sharepoint.com:/sites/CPLAN
   ```
   Copy the `id` from response

4. **Update `.env.local`:**
   ```env
   SHAREPOINT_SITE_ID=your-actual-site-id-here
   SHAREPOINT_SITE_URL=https://yourtenant.sharepoint.com/sites/CPLAN
   ```

### Step 3: Create Microsoft Lists (10 minutes)

**Automated way (Recommended):**

```powershell
# Install PnP PowerShell (one-time)
Install-Module -Name PnP.PowerShell -Scope CurrentUser

# Run the setup script
cd /Users/micha/Documents/Arbeit/CPLAN/cplan
./setup-lists.ps1 -SiteUrl "https://yourtenant.sharepoint.com/sites/CPLAN"
```

**The script will:**
- ✅ Create all 7 Microsoft Lists
- ✅ Configure columns and settings
- ✅ Output all List IDs
- ✅ You just copy-paste IDs to `.env.local`

**Manual way:**
See [MICROSOFT_LISTS_SETUP.md](./MICROSOFT_LISTS_SETUP.md) for manual instructions

### Step 4: Generate Random Secrets (2 minutes)

```bash
# Generate random secrets
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
# Copy output to NEXTAUTH_SECRET

node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
# Copy output to API_SECRET_KEY
```

Or use online generator: https://generate-secret.vercel.app/32

Update `.env.local`:
```env
NEXTAUTH_SECRET=abc123def456... (64 characters)
API_SECRET_KEY=xyz789uvw012... (64 characters)
```

### Step 5: Verify Configuration

After updating all values in `.env.local`, restart the dev server:

```bash
# Stop current server (Ctrl+C)
npm run dev
```

Server should start without errors if configuration is correct.

---

## 📂 Complete `.env.local` Example

Here's what it should look like when properly configured:

```env
# Microsoft 365 / Azure AD Configuration
AZURE_AD_CLIENT_ID=12345678-1234-1234-1234-123456789abc
AZURE_AD_CLIENT_SECRET=abc~def~ghi~jkl~mno~pqr~stu~vwx~yz
AZURE_AD_TENANT_ID=87654321-4321-4321-4321-cba987654321

# Microsoft Graph API
GRAPH_API_ENDPOINT=https://graph.microsoft.com/v1.0
SHAREPOINT_SITE_ID=yourtenant.sharepoint.com,abc123,def456
SHAREPOINT_SITE_URL=https://yourtenant.sharepoint.com/sites/CPLAN

# Microsoft Lists Configuration (from PowerShell script output)
COMMUNICATIONS_LIST_ID=a1b2c3d4-e5f6-7890-abcd-ef1234567890
TEMPLATES_LIST_ID=b2c3d4e5-f6a7-8901-bcde-f12345678901
APPROVALS_LIST_ID=c3d4e5f6-a7b8-9012-cdef-123456789012
ACTIVITIES_LIST_ID=d4e5f6a7-b8c9-0123-def1-234567890123
METRICS_LIST_ID=e5f6a7b8-c9d0-1234-ef12-345678901234
PACKS_LIST_ID=f6a7b8c9-d0e1-2345-f123-456789012345
TAGS_LIST_ID=a7b8c9d0-e1f2-3456-1234-567890123456

# Authentication
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2

# API Security
API_SECRET_KEY=b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2g3

# Optional: OpenAI for AI features
OPENAI_API_KEY=sk-proj-abc123def456...

# Optional: Power Automate
POWER_AUTOMATE_WEBHOOK_URL=https://prod-12.westus.logic.azure.com:443/workflows/abc123...
WEBHOOK_SECRET=your-webhook-secret-here

# Optional
USE_APP_ONLY_AUTH=true
```

---

## 🔍 How to Check Your Configuration

### Test 1: Environment Variables Loaded

```bash
# In terminal
cd /Users/micha/Documents/Arbeit/CPLAN/cplan
node -e "require('dotenv').config({ path: '.env.local' }); console.log(process.env.AZURE_AD_CLIENT_ID)"
```

Should print your client ID (not "your-app-client-id")

### Test 2: Server Starts Without Errors

```bash
npm run dev
```

Look for errors in console. If configuration is wrong, you'll see errors like:
- "Invalid credentials"
- "Site not found"
- "List not found"

### Test 3: API Endpoint Works

```bash
# After server is running
curl http://localhost:3000/api/communications-lists?count=true \
  -H "X-API-Key: YOUR_API_SECRET_KEY"
```

Should return: `{"total": 0}` (or actual count if you have data)

---

## 🚨 Common Configuration Errors

### Error: "Invalid client secret"
**Cause:** `AZURE_AD_CLIENT_SECRET` is wrong or expired
**Fix:** Generate new client secret in Azure Portal

### Error: "Site not found"
**Cause:** `SHAREPOINT_SITE_ID` is incorrect
**Fix:** Re-fetch Site ID using Graph Explorer or PowerShell

### Error: "List not found"
**Cause:** List IDs are wrong or lists weren't created
**Fix:** Run `setup-lists.ps1` script or create lists manually

### Error: "Unauthorized"
**Cause:** Azure AD app doesn't have permissions
**Fix:** Add `Sites.ReadWrite.All` permission and grant admin consent

---

## 🔒 Security Best Practices

### ✅ DO:
- Keep `.env.local` in `.gitignore` (already configured)
- Use strong random secrets (32+ characters)
- Rotate client secrets every 6-12 months
- Use different secrets for dev/prod environments
- Limit Azure AD app permissions to minimum needed

### ❌ DON'T:
- Commit `.env.local` to Git
- Share secrets in chat/email
- Use same secrets across environments
- Hard-code secrets in source files
- Expose secrets in browser JavaScript

---

## 📦 Next Steps After Configuration

1. **Verify everything works:**
   ```bash
   npm run dev
   # Visit http://localhost:3000
   ```

2. **Create Microsoft Lists:**
   ```powershell
   ./setup-lists.ps1 -SiteUrl "https://yourtenant.sharepoint.com/sites/CPLAN"
   ```

3. **Seed mock data:**
   ```bash
   npm run seed-data
   ```

4. **Test the application:**
   - Dashboard should load
   - Calendar should display
   - Create new communication should work

---

## 🎯 Quick Configuration Checklist

- [ ] Azure AD app created
- [ ] Client ID, Tenant ID, Client Secret copied to `.env.local`
- [ ] API permissions added and consent granted
- [ ] SharePoint site created
- [ ] Site ID and URL in `.env.local`
- [ ] PowerShell script run (lists created)
- [ ] All List IDs in `.env.local`
- [ ] Random secrets generated for NEXTAUTH_SECRET and API_SECRET_KEY
- [ ] Server runs without errors (`npm run dev`)
- [ ] Mock data seeded (`npm run seed-data`)

---

## 💡 Future: Admin Configuration UI

We could build an admin panel for non-secret settings:

```typescript
// Future feature: Admin Settings Page
/settings/admin
  ├── Feature Flags (enable/disable features)
  ├── UI Customization (colors, logos)
  ├── Email Templates
  ├── Notification Settings
  └── User Management
```

**But secrets (Azure AD, API keys) should always be in `.env.local` for security!**

---

Need help with configuration? Check:
1. This guide
2. [MICROSOFT_LISTS_SETUP.md](./MICROSOFT_LISTS_SETUP.md) - Detailed setup
3. Console errors when running `npm run dev`
4. Azure Portal error messages