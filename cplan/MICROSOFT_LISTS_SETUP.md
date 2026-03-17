# Microsoft Lists Setup Guide for CPLAN

This guide will help you set up the required Microsoft Lists in SharePoint to use as the backend for CPLAN.

## Prerequisites

1. **Microsoft 365 Tenant** with SharePoint Online
2. **Admin Access** to create SharePoint sites and lists
3. **Azure AD App Registration** for API access
4. **Power Automate** (optional, for advanced workflows)

---

## Step 1: Create SharePoint Site

1. Go to SharePoint Admin Center
2. Create a new Communication or Team Site named **"CPLAN"**
3. Note the Site URL: `https://yourtenant.sharepoint.com/sites/CPLAN`
4. Get the Site ID using PowerShell or Graph Explorer:
   ```
   GET https://graph.microsoft.com/v1.0/sites/yourtenant.sharepoint.com:/sites/CPLAN
   ```

---

## Step 2: Register Azure AD Application

1. Go to **Azure Portal** → **Azure Active Directory** → **App registrations**
2. Click **"New registration"**
3. Name: **CPLAN API**
4. Supported account types: **Single tenant**
5. Click **Register**

### Configure API Permissions

Add the following Microsoft Graph API permissions (Application type):

- `Sites.ReadWrite.All` - Read and write items in all site collections
- `Sites.FullControl.All` - Have full control of all site collections
- `User.Read.All` - Read all users' full profiles

**Grant admin consent** for these permissions.

### Create Client Secret

1. Go to **Certificates & secrets**
2. Click **New client secret**
3. Description: **CPLAN Backend**
4. Expiration: **24 months** (or as per policy)
5. Copy the **Value** (Client Secret) - you won't see it again!

### Get Application Details

Note these values for your `.env.local`:
- **Application (client) ID** → `AZURE_AD_CLIENT_ID`
- **Directory (tenant) ID** → `AZURE_AD_TENANT_ID`
- **Client Secret Value** → `AZURE_AD_CLIENT_SECRET`

---

## Step 3: Create Microsoft Lists

Create the following lists in your CPLAN SharePoint site:

### 1. Communications List

**Columns:**

| Column Name | Type | Required | Description |
|------------|------|----------|-------------|
| Title | Single line of text | Yes | Communication title |
| TrackingId | Single line of text | Yes | Unique tracking ID (indexed) |
| Description | Multiple lines of text | No | Brief description |
| Content | Multiple lines of text | Yes | Full communication content |
| Status | Choice | Yes | DRAFT, REVIEW, APPROVED, SCHEDULED, PUBLISHED, ARCHIVED, EXPIRED |
| Priority | Choice | Yes | LOW, MEDIUM, HIGH, URGENT |
| Type | Choice | Yes | ANNOUNCEMENT, UPDATE, NEWSLETTER, ALERT, EVENT, POLICY, OTHER |
| PublishDate | Date and Time | No | Scheduled publish date |
| ExpiryDate | Date and Time | No | Expiration date |
| OwnerId | Single line of text | Yes | User ID of owner |
| OwnerEmail | Single line of text | Yes | Email of owner |
| OwnerName | Single line of text | Yes | Name of owner |
| TemplateId | Single line of text | No | Reference to template |
| PackId | Single line of text | No | Reference to pack |
| Metadata | Multiple lines of text | No | JSON metadata |
| AISuggestions | Multiple lines of text | No | JSON AI suggestions |
| Channels | Multiple lines of text | No | JSON array of channels |
| Tags | Multiple lines of text | No | JSON array of tags |

**List Settings:**
- Enable versioning
- Create index on `TrackingId` column

### 2. Templates List

**Columns:**

| Column Name | Type | Required | Description |
|------------|------|----------|-------------|
| Title | Single line of text | Yes | Template name |
| Description | Multiple lines of text | No | Template description |
| Content | Multiple lines of text | Yes | Template content |
| Type | Choice | Yes | Same as Communications |
| Category | Single line of text | No | Template category |
| IsActive | Yes/No | Yes | Template active status |
| UsageCount | Number | No | Times template was used |
| Variables | Multiple lines of text | No | JSON template variables |

### 3. Approvals List

**Columns:**

| Column Name | Type | Required | Description |
|------------|------|----------|-------------|
| Title | Single line of text | Yes | Approval title |
| CommunicationId | Single line of text | Yes | Reference to communication |
| ApproverId | Single line of text | Yes | User ID of approver |
| Status | Choice | Yes | PENDING, APPROVED, REJECTED, REQUESTED_CHANGES |
| Level | Number | Yes | Approval level (1, 2, 3, etc.) |
| Comments | Multiple lines of text | No | Approver comments |
| ApprovedAt | Date and Time | No | When approved |

### 4. Activities List

**Columns:**

| Column Name | Type | Required | Description |
|------------|------|----------|-------------|
| Title | Single line of text | Yes | Activity description |
| Type | Choice | Yes | CREATED, UPDATED, PUBLISHED, ARCHIVED, APPROVED, REJECTED, etc. |
| Description | Multiple lines of text | Yes | Detailed description |
| CommunicationId | Single line of text | No | Related communication ID |
| UserId | Single line of text | Yes | User who performed action |
| Metadata | Multiple lines of text | No | JSON metadata |

### 5. Metrics List

**Columns:**

| Column Name | Type | Required | Description |
|------------|------|----------|-------------|
| Title | Single line of text | Yes | Metric identifier |
| CommunicationId | Single line of text | Yes | Related communication ID |
| Channel | Choice | Yes | EMAIL, INTRANET, TEAMS, SLACK, SMS, etc. |
| Sent | Number | No | Number sent |
| Delivered | Number | No | Number delivered |
| Opened | Number | No | Number opened |
| Clicked | Number | No | Number clicked |
| Bounced | Number | No | Number bounced |

### 6. Packs List

**Columns:**

| Column Name | Type | Required | Description |
|------------|------|----------|-------------|
| Title | Single line of text | Yes | Pack name |
| Description | Multiple lines of text | No | Pack description |

### 7. Tags List (Optional)

**Columns:**

| Column Name | Type | Required | Description |
|------------|------|----------|-------------|
| Title | Single line of text | Yes | Tag name |
| Color | Single line of text | No | Tag color (hex) |

---

## Step 4: Get List IDs

For each list created, get the List ID:

### Option A: Using SharePoint UI
1. Go to List Settings
2. Look at the URL: `...lists/LISTNAME/AllItems.aspx?viewid=...`
3. Or use Site Contents and hover over the list

### Option B: Using Graph Explorer
```
GET https://graph.microsoft.com/v1.0/sites/{site-id}/lists
```

Copy the `id` of each list.

---

## Step 5: Configure Environment Variables

Update your `/Users/micha/Documents/Arbeit/CPLAN/cplan/.env.local` file:

```env
# Microsoft 365 / Azure AD Configuration
AZURE_AD_CLIENT_ID=your-app-client-id-here
AZURE_AD_CLIENT_SECRET=your-app-client-secret-here
AZURE_AD_TENANT_ID=your-tenant-id-here

# Microsoft Graph API
GRAPH_API_ENDPOINT=https://graph.microsoft.com/v1.0
SHAREPOINT_SITE_ID=your-sharepoint-site-id-here
SHAREPOINT_SITE_URL=https://yourtenant.sharepoint.com/sites/CPLAN

# Microsoft Lists Configuration
COMMUNICATIONS_LIST_ID=your-communications-list-id-here
TEMPLATES_LIST_ID=your-templates-list-id-here
APPROVALS_LIST_ID=your-approvals-list-id-here
ACTIVITIES_LIST_ID=your-activities-list-id-here
METRICS_LIST_ID=your-metrics-list-id-here
PACKS_LIST_ID=your-packs-list-id-here
TAGS_LIST_ID=your-tags-list-id-here

# Authentication
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=generate-a-random-secret-key

# API Security
API_SECRET_KEY=generate-another-random-secret-key

# Optional: OpenAI for AI features
OPENAI_API_KEY=your-openai-api-key

# Optional: Power Automate
POWER_AUTOMATE_WEBHOOK_URL=your-webhook-url
WEBHOOK_SECRET=your-webhook-secret
USE_APP_ONLY_AUTH=true
```

---

## Step 6: Test the Connection

### Test Script

Create a test file `test-graph-connection.ts`:

```typescript
import { graphClient } from './src/lib/graph-client';

async function testConnection() {
  try {
    // Test site access
    const site = await graphClient
      .api(`/sites/${process.env.SHAREPOINT_SITE_ID}`)
      .get();

    console.log('✅ Connected to site:', site.displayName);

    // Test list access
    const lists = await graphClient
      .api(`/sites/${process.env.SHAREPOINT_SITE_ID}/lists`)
      .get();

    console.log('✅ Found', lists.value.length, 'lists');

    // Test creating an item
    const testItem = await graphClient
      .api(`/sites/${process.env.SHAREPOINT_SITE_ID}/lists/${process.env.COMMUNICATIONS_LIST_ID}/items`)
      .post({
        fields: {
          Title: 'Test Communication',
          TrackingId: 'TEST-123',
          Content: 'Test content',
          Status: 'DRAFT',
          Priority: 'LOW',
          Type: 'OTHER',
          OwnerId: 'test-user',
          OwnerEmail: 'test@example.com',
          OwnerName: 'Test User',
        }
      });

    console.log('✅ Created test item:', testItem.id);

    return true;
  } catch (error) {
    console.error('❌ Connection test failed:', error);
    return false;
  }
}

testConnection();
```

Run: `npm run test-connection`

---

## Step 7: Power Automate Integration (Optional)

### Create Flows for:

1. **Auto-publish scheduled communications**
   - Trigger: Recurrence (every hour)
   - Condition: PublishDate <= Now AND Status = SCHEDULED
   - Action: Update Status to PUBLISHED

2. **Send approval notifications**
   - Trigger: When item created in Approvals list
   - Action: Send email to approver

3. **Track metrics from email campaigns**
   - Trigger: When email is opened/clicked
   - Action: Update Metrics list

4. **Expire old communications**
   - Trigger: Recurrence (daily)
   - Condition: ExpiryDate <= Today AND Status = PUBLISHED
   - Action: Update Status to EXPIRED

---

## Troubleshooting

### Permission Errors
- Verify Azure AD app has correct permissions
- Ensure admin consent is granted
- Check that Site ID and List IDs are correct

### Authentication Errors
- Verify client secret hasn't expired
- Check tenant ID is correct
- Ensure `USE_APP_ONLY_AUTH=true` in .env

### Data Access Issues
- Verify list column names match exactly (case-sensitive)
- Check that indexed columns are created
- Ensure choice field options match code enums

---

## Benefits of Microsoft Lists Backend

✅ **No Database Setup** - Use existing M365 infrastructure
✅ **Native Power Automate** - Easy workflow automation
✅ **Familiar Interface** - Users can view/edit in SharePoint
✅ **Built-in Versioning** - Automatic change tracking
✅ **Enterprise Security** - Azure AD authentication
✅ **Compliance** - Leverage M365 compliance features
✅ **Backup & Recovery** - Built into M365
✅ **Scalability** - Microsoft's infrastructure

---

## Next Steps

1. ✅ Create all lists in SharePoint
2. ✅ Configure Azure AD app
3. ✅ Update .env.local with all IDs
4. ✅ Test the connection
5. ✅ Start using CPLAN!

For questions or issues, refer to:
- [Microsoft Graph API Documentation](https://docs.microsoft.com/graph/)
- [SharePoint Lists REST API](https://docs.microsoft.com/sharepoint/dev/)
- [Azure AD App Registration](https://docs.microsoft.com/azure/active-directory/)