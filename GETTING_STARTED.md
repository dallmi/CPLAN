# Getting Started with CPLAN

## 🎯 Quick Overview

**What you have:** Enterprise communication planning tool
**Backend:** Microsoft Lists (SharePoint)
**Configuration:** One file (`.env.local`)
**Mock Data:** 50+ realistic communications ready to create

---

## 📋 Setup Checklist

### 1️⃣ Configure Azure AD & SharePoint (30 min)

**File to edit:** `.env.local`

Follow: [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md)

**You need:**
- Azure AD app registration (get 3 IDs)
- SharePoint site created
- Microsoft Lists created (run PowerShell script)
- Random secrets generated

**Status check:**
```bash
# After configuration, this should work:
npm run dev
# Visit: http://localhost:3000
```

### 2️⃣ Create Microsoft Lists (10 min)

**Run PowerShell script:**
```powershell
./setup-lists.ps1 -SiteUrl "https://yourtenant.sharepoint.com/sites/CPLAN"
```

**Creates:**
- 7 SharePoint Lists (Communications, Templates, etc.)
- Outputs all List IDs (copy to `.env.local`)

Follow: [MICROSOFT_LISTS_SETUP.md](./MICROSOFT_LISTS_SETUP.md)

### 3️⃣ Seed Mock Data (3 min)

**Run seed script:**
```bash
npm run seed-data
```

**Creates:**
- 48 realistic enterprise communications
- 3 templates
- 3 communication packs

Follow: [SEED_DATA_README.md](./SEED_DATA_README.md)

---

## 🚀 Where Configuration Lives

**Everything is in ONE file:**

```
/Users/micha/Documents/Arbeit/CPLAN/cplan/.env.local
```

**Edit this file** with:
- VS Code
- Any text editor
- Terminal: `nano .env.local`

**No web UI for secrets** - this is normal and secure!

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `.env.local` | **ALL configuration** (secrets, IDs) |
| `setup-lists.ps1` | Creates SharePoint Lists |
| `package.json` | npm scripts |
| `scripts/seed-mock-data.ts` | Generates test data |

---

## 🎬 Quick Start Commands

```bash
# 1. Install dependencies (one-time)
npm install

# 2. Configure .env.local
# Edit the file and add your Azure/SharePoint details

# 3. Start dev server
npm run dev

# 4. Create mock data
npm run seed-data

# 5. Open app
# Visit: http://localhost:3000
```

---

## 📚 Documentation Guide

**Start here:**
1. [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md) - How to configure
2. [MICROSOFT_LISTS_SETUP.md](./MICROSOFT_LISTS_SETUP.md) - Create SharePoint Lists
3. [SEED_DATA_README.md](./SEED_DATA_README.md) - Add test data

**Advanced:**
4. [PAGINATION_GUIDE.md](./PAGINATION_GUIDE.md) - Handle millions of records
5. [QUICK_API_REFERENCE.md](./QUICK_API_REFERENCE.md) - API examples
6. [README.md](./README.md) - Project overview

---

## 🔍 Current Status

**Your app is:**
- ✅ Installed (dependencies ready)
- ⏳ Not configured (need to edit `.env.local`)
- ⏳ Lists not created (need to run PowerShell script)
- ⏳ No data yet (need to run seed script)

**Next step:** [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md)

---

## ❓ Common Questions

**Q: Where do I enter my Azure AD credentials?**
A: In `.env.local` file (text file, no UI)

**Q: How do I create the Microsoft Lists?**
A: Run `./setup-lists.ps1` PowerShell script

**Q: How do I add test data?**
A: Run `npm run seed-data` after configuration

**Q: Can this work with millions of records?**
A: Yes! See [PAGINATION_GUIDE.md](./PAGINATION_GUIDE.md)

**Q: Can I deploy this as a single HTML file?**
A: No, needs Node.js server (see README for deployment options)

---

## 🎯 Success Criteria

**You're ready when:**
- ✅ `npm run dev` starts without errors
- ✅ Dashboard loads at http://localhost:3000
- ✅ Seed script runs successfully
- ✅ Dashboard shows 48+ communications

**Total setup time:** ~45 minutes

---

Need help? Start with [CONFIGURATION_GUIDE.md](./CONFIGURATION_GUIDE.md) 🚀
