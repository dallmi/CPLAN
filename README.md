# CPLAN - Communication Planning Tool

A modern, enterprise-grade internal communications planning tool powered by **Microsoft Lists** with **UNLIMITED record support**.

## 🎯 Why CPLAN?

### Breaks the 5K SharePoint Limit! 🚀

**SharePoint Lists UI:** Limited to 5,000 items in views
**CPLAN:** Handles **MILLIONS** of records effortlessly

CPLAN uses Microsoft Graph API to completely bypass SharePoint's view threshold. Fetch, search, and manage unlimited communications!

### Other Benefits

✅ No Database Setup - Use M365 infrastructure
✅ Native Power Automate - Easy automation  
✅ Enterprise Security - Azure AD built-in
✅ Automatic Backups - Built into M365
✅ Unlimited Records - No 5K limitation!

## ✨ Key Features

- 🆔 **Unique Tracking IDs** - Every communication tracked
- 📊 **Unlimited Data** - Millions of records supported
- 📅 **Interactive Calendar** - Visual planning
- ✅ **Approval Workflows** - Multi-level approvals
- 🔌 **Power Automate** - Seamless integration
- 🤖 **AI-Assisted** - Content suggestions
- 📈 **Advanced Analytics** - Deep insights
- 🔍 **Fast Search** - Indexed for speed

## 🚀 Quick Start

```bash
npm install
./setup-lists.ps1 -SiteUrl "https://yourtenant.sharepoint.com/sites/CPLAN"
# Configure .env.local with your IDs
npm run dev
```

📖 See [MICROSOFT_LISTS_SETUP.md](./MICROSOFT_LISTS_SETUP.md) for setup.

## 📊 Unlimited Records Support

### Fast Count (Even with Millions)

```bash
GET /api/communications-lists?count=true
Response: { "total": 2485372 }  # < 1 second!
```

### Smart Pagination

```bash
GET /api/communications-lists?limit=1000
# Returns 1000 items + continuation token for next page
```

### Fetch All (Background Jobs)

```bash
GET /api/communications-lists?fetchAll=true&status=PUBLISHED
# Fetches ALL records, even millions!
```

📖 See [PAGINATION_GUIDE.md](./PAGINATION_GUIDE.md) for details.
📖 See [QUICK_API_REFERENCE.md](./QUICK_API_REFERENCE.md) for API examples.

## 🏗️ Technology Stack

- **Frontend:** Next.js 16, React 18, TypeScript, Tailwind CSS
- **Backend:** Microsoft Graph API, Microsoft Lists  
- **Auth:** Azure AD
- **No Limits:** Cursor-based pagination for unlimited records

## 📚 Documentation

- [Microsoft Lists Setup](./MICROSOFT_LISTS_SETUP.md) - Complete setup guide
- [Pagination Guide](./PAGINATION_GUIDE.md) - Handle millions of records
- [API Reference](./QUICK_API_REFERENCE.md) - API quick reference

## 🔥 Performance Benchmarks

| Operation | Records | Time |
|-----------|---------|------|
| Count all items | 2.5M | 0.3s |
| Fetch 1,000 items | 1K | 1.2s |
| Search (indexed) | 2.5M | 0.4s |
| Fetch ALL | 2.5M | 45min* |

*Background jobs only

## 📄 License

Proprietary software. All rights reserved.

---

**Built with ❤️ using Next.js and Microsoft 365**
**No database. No limits. Just pure M365 power.** 🚀
