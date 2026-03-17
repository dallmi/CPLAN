# PowerShell Script to Create Microsoft Lists for CPLAN
# Run this script with SharePoint PnP PowerShell

# Install PnP PowerShell if not already installed:
# Install-Module -Name PnP.PowerShell -Scope CurrentUser

param(
    [Parameter(Mandatory=$true)]
    [string]$SiteUrl
)

Write-Host "Connecting to SharePoint site: $SiteUrl" -ForegroundColor Cyan
Connect-PnPOnline -Url $SiteUrl -Interactive

Write-Host "`nCreating Microsoft Lists for CPLAN...`n" -ForegroundColor Green

# 1. Create Communications List
Write-Host "Creating Communications List..." -ForegroundColor Yellow
$commList = New-PnPList -Title "Communications" -Template GenericList -EnableVersioning

Add-PnPField -List "Communications" -DisplayName "TrackingId" -InternalName "TrackingId" -Type Text -AddToDefaultView -Required
Add-PnPField -List "Communications" -DisplayName "Description" -InternalName "Description" -Type Note -AddToDefaultView
Add-PnPField -List "Communications" -DisplayName "Content" -InternalName "Content" -Type Note -Required
Add-PnPField -List "Communications" -DisplayName "Status" -InternalName "Status" -Type Choice -Choices "DRAFT","REVIEW","APPROVED","SCHEDULED","PUBLISHED","ARCHIVED","EXPIRED" -Required -AddToDefaultView
Add-PnPField -List "Communications" -DisplayName "Priority" -InternalName "Priority" -Type Choice -Choices "LOW","MEDIUM","HIGH","URGENT" -Required -AddToDefaultView
Add-PnPField -List "Communications" -DisplayName "Type" -InternalName "Type" -Type Choice -Choices "ANNOUNCEMENT","UPDATE","NEWSLETTER","ALERT","EVENT","POLICY","OTHER" -Required -AddToDefaultView
Add-PnPField -List "Communications" -DisplayName "PublishDate" -InternalName "PublishDate" -Type DateTime -AddToDefaultView
Add-PnPField -List "Communications" -DisplayName "ExpiryDate" -InternalName "ExpiryDate" -Type DateTime
Add-PnPField -List "Communications" -DisplayName "OwnerId" -InternalName "OwnerId" -Type Text -Required
Add-PnPField -List "Communications" -DisplayName "OwnerEmail" -InternalName "OwnerEmail" -Type Text -Required
Add-PnPField -List "Communications" -DisplayName "OwnerName" -InternalName "OwnerName" -Type Text -Required
Add-PnPField -List "Communications" -DisplayName "TemplateId" -InternalName "TemplateId" -Type Text
Add-PnPField -List "Communications" -DisplayName "PackId" -InternalName "PackId" -Type Text
Add-PnPField -List "Communications" -DisplayName "Metadata" -InternalName "Metadata" -Type Note
Add-PnPField -List "Communications" -DisplayName "AISuggestions" -InternalName "AISuggestions" -Type Note
Add-PnPField -List "Communications" -DisplayName "Channels" -InternalName "Channels" -Type Note
Add-PnPField -List "Communications" -DisplayName "Tags" -InternalName "Tags" -Type Note

# Add index on TrackingId for faster queries
Add-PnPFieldToView -List "Communications" -Field "TrackingId" -View "All Items"

Write-Host "✅ Communications List created" -ForegroundColor Green
Write-Host "List ID: $($commList.Id)" -ForegroundColor Cyan

# 2. Create Templates List
Write-Host "`nCreating Templates List..." -ForegroundColor Yellow
$tempList = New-PnPList -Title "Templates" -Template GenericList -EnableVersioning

Add-PnPField -List "Templates" -DisplayName "Description" -InternalName "Description" -Type Note -AddToDefaultView
Add-PnPField -List "Templates" -DisplayName "Content" -InternalName "Content" -Type Note -Required
Add-PnPField -List "Templates" -DisplayName "Type" -InternalName "Type" -Type Choice -Choices "ANNOUNCEMENT","UPDATE","NEWSLETTER","ALERT","EVENT","POLICY","OTHER" -Required -AddToDefaultView
Add-PnPField -List "Templates" -DisplayName "Category" -InternalName "Category" -Type Text -AddToDefaultView
Add-PnPField -List "Templates" -DisplayName "IsActive" -InternalName "IsActive" -Type Boolean -Required -AddToDefaultView
Add-PnPField -List "Templates" -DisplayName "UsageCount" -InternalName "UsageCount" -Type Number
Add-PnPField -List "Templates" -DisplayName "Variables" -InternalName "Variables" -Type Note

Write-Host "✅ Templates List created" -ForegroundColor Green
Write-Host "List ID: $($tempList.Id)" -ForegroundColor Cyan

# 3. Create Approvals List
Write-Host "`nCreating Approvals List..." -ForegroundColor Yellow
$approvList = New-PnPList -Title "Approvals" -Template GenericList

Add-PnPField -List "Approvals" -DisplayName "CommunicationId" -InternalName "CommunicationId" -Type Text -Required -AddToDefaultView
Add-PnPField -List "Approvals" -DisplayName "ApproverId" -InternalName "ApproverId" -Type Text -Required -AddToDefaultView
Add-PnPField -List "Approvals" -DisplayName "Status" -InternalName "Status" -Type Choice -Choices "PENDING","APPROVED","REJECTED","REQUESTED_CHANGES" -Required -AddToDefaultView
Add-PnPField -List "Approvals" -DisplayName "Level" -InternalName "Level" -Type Number -Required
Add-PnPField -List "Approvals" -DisplayName "Comments" -InternalName "Comments" -Type Note
Add-PnPField -List "Approvals" -DisplayName "ApprovedAt" -InternalName "ApprovedAt" -Type DateTime

Write-Host "✅ Approvals List created" -ForegroundColor Green
Write-Host "List ID: $($approvList.Id)" -ForegroundColor Cyan

# 4. Create Activities List
Write-Host "`nCreating Activities List..." -ForegroundColor Yellow
$actList = New-PnPList -Title "Activities" -Template GenericList

Add-PnPField -List "Activities" -DisplayName "Type" -InternalName "Type" -Type Choice -Choices "CREATED","UPDATED","PUBLISHED","ARCHIVED","APPROVED","REJECTED","COMMENTED","VIEWED","EXPORTED" -Required -AddToDefaultView
Add-PnPField -List "Activities" -DisplayName "Description" -InternalName "Description" -Type Note -Required -AddToDefaultView
Add-PnPField -List "Activities" -DisplayName "CommunicationId" -InternalName "CommunicationId" -Type Text -AddToDefaultView
Add-PnPField -List "Activities" -DisplayName "UserId" -InternalName "UserId" -Type Text -Required -AddToDefaultView
Add-PnPField -List "Activities" -DisplayName "Metadata" -InternalName "Metadata" -Type Note

Write-Host "✅ Activities List created" -ForegroundColor Green
Write-Host "List ID: $($actList.Id)" -ForegroundColor Cyan

# 5. Create Metrics List
Write-Host "`nCreating Metrics List..." -ForegroundColor Yellow
$metricsList = New-PnPList -Title "Metrics" -Template GenericList

Add-PnPField -List "Metrics" -DisplayName "CommunicationId" -InternalName "CommunicationId" -Type Text -Required -AddToDefaultView
Add-PnPField -List "Metrics" -DisplayName "Channel" -InternalName "Channel" -Type Choice -Choices "EMAIL","INTRANET","TEAMS","SLACK","SMS","MOBILE_APP","DIGITAL_SIGNAGE","SOCIAL" -Required -AddToDefaultView
Add-PnPField -List "Metrics" -DisplayName "Sent" -InternalName "Sent" -Type Number -AddToDefaultView
Add-PnPField -List "Metrics" -DisplayName "Delivered" -InternalName "Delivered" -Type Number -AddToDefaultView
Add-PnPField -List "Metrics" -DisplayName "Opened" -InternalName "Opened" -Type Number -AddToDefaultView
Add-PnPField -List "Metrics" -DisplayName "Clicked" -InternalName "Clicked" -Type Number -AddToDefaultView
Add-PnPField -List "Metrics" -DisplayName "Bounced" -InternalName "Bounced" -Type Number

Write-Host "✅ Metrics List created" -ForegroundColor Green
Write-Host "List ID: $($metricsList.Id)" -ForegroundColor Cyan

# 6. Create Packs List
Write-Host "`nCreating Packs List..." -ForegroundColor Yellow
$packsList = New-PnPList -Title "Packs" -Template GenericList

Add-PnPField -List "Packs" -DisplayName "Description" -InternalName "Description" -Type Note -AddToDefaultView

Write-Host "✅ Packs List created" -ForegroundColor Green
Write-Host "List ID: $($packsList.Id)" -ForegroundColor Cyan

# 7. Create Tags List
Write-Host "`nCreating Tags List..." -ForegroundColor Yellow
$tagsList = New-PnPList -Title "Tags" -Template GenericList

Add-PnPField -List "Tags" -DisplayName "Color" -InternalName "Color" -Type Text -AddToDefaultView

Write-Host "✅ Tags List created" -ForegroundColor Green
Write-Host "List ID: $($tagsList.Id)" -ForegroundColor Cyan

# Output summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "All Lists Created Successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`nAdd these IDs to your .env.local file:" -ForegroundColor Yellow
Write-Host "`nCOMMUNICATIONS_LIST_ID=$($commList.Id)"
Write-Host "TEMPLATES_LIST_ID=$($tempList.Id)"
Write-Host "APPROVALS_LIST_ID=$($approvList.Id)"
Write-Host "ACTIVITIES_LIST_ID=$($actList.Id)"
Write-Host "METRICS_LIST_ID=$($metricsList.Id)"
Write-Host "PACKS_LIST_ID=$($packsList.Id)"
Write-Host "TAGS_LIST_ID=$($tagsList.Id)"

Write-Host "`nGet your Site ID with:" -ForegroundColor Yellow
Write-Host "GET https://graph.microsoft.com/v1.0/sites/yourtenant.sharepoint.com:/sites/CPLAN" -ForegroundColor Cyan

Write-Host "`nSetup complete! 🎉" -ForegroundColor Green

Disconnect-PnPOnline