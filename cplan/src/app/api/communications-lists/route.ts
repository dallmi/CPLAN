import { NextRequest, NextResponse } from "next/server";
import { communicationsService, activitiesService } from "@/lib/microsoft-lists-paginated";
import { generateTrackingId } from "@/lib/utils";

// API authentication middleware
function verifyApiKey(request: NextRequest): boolean {
  const apiKey = request.headers.get("X-API-Key");
  return apiKey === process.env.API_SECRET_KEY;
}

// GET /api/communications-lists - List communications with UNLIMITED pagination support
export async function GET(request: NextRequest) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const searchParams = request.nextUrl.searchParams;
    const status = searchParams.get("status") || undefined;
    const type = searchParams.get("type") || undefined;
    const priority = searchParams.get("priority") || undefined;
    const limit = parseInt(searchParams.get("limit") || "1000");
    const skipToken = searchParams.get("skipToken") || undefined;
    const fetchAll = searchParams.get("fetchAll") === "true"; // WARNING: Use carefully
    const count = searchParams.get("count") === "true"; // Just get count

    // Option 1: Get count only (very fast, even for millions of records)
    if (count) {
      const total = await communicationsService.count({ status, type, priority });
      return NextResponse.json({ total });
    }

    // Option 2: Fetch ALL records (can be millions - use with caution)
    // Example: GET /api/communications-lists?fetchAll=true&status=PUBLISHED
    const result = await communicationsService.findMany({
      status,
      type,
      priority,
      limit,
      skipToken,
      fetchAll,
    });

    return NextResponse.json({
      data: result.items,
      pagination: {
        total: result.total,
        count: result.items.length,
        hasMore: result.hasMore || false,
        nextLink: result.nextLink,
        skipToken: result.skipToken, // Use this for next page
      },
    });
  } catch (error) {
    console.error("Error fetching communications:", error);
    return NextResponse.json(
      { error: "Internal server error", details: (error as Error).message },
      { status: 500 }
    );
  }
}

// POST /api/communications-lists - Create new communication
export async function POST(request: NextRequest) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();

    const communication = await communicationsService.create({
      title: body.title,
      description: body.description,
      content: body.content,
      type: body.type,
      priority: body.priority,
      status: body.status || "DRAFT",
      publishDate: body.publishDate || null,
      expiryDate: body.expiryDate || null,
      ownerId: body.ownerId,
      ownerEmail: body.ownerEmail,
      ownerName: body.ownerName,
      templateId: body.templateId,
      packId: body.packId,
      metadata: body.metadata,
      channels: body.channels || [],
      tags: body.tags || [],
    });

    // Send webhook notification to Power Automate if configured
    if (process.env.POWER_AUTOMATE_WEBHOOK_URL) {
      await fetch(process.env.POWER_AUTOMATE_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event: "communication.created",
          data: communication,
        }),
      }).catch(console.error);
    }

    return NextResponse.json(communication, { status: 201 });
  } catch (error) {
    console.error("Error creating communication:", error);
    return NextResponse.json(
      { error: "Internal server error", details: (error as Error).message },
      { status: 500 }
    );
  }
}

// PUT /api/communications-lists - Bulk update communications
export async function PUT(request: NextRequest) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();
    const { ids, updates } = body;

    if (!ids || !Array.isArray(ids) || ids.length === 0) {
      return NextResponse.json(
        { error: "Invalid communication IDs" },
        { status: 400 }
      );
    }

    // Update each communication
    let count = 0;
    for (const id of ids) {
      try {
        await communicationsService.update(id, updates);
        count++;
      } catch (error) {
        console.error(`Error updating communication ${id}:`, error);
      }
    }

    return NextResponse.json({
      message: "Communications updated",
      count,
    });
  } catch (error) {
    console.error("Error updating communications:", error);
    return NextResponse.json(
      { error: "Internal server error", details: (error as Error).message },
      { status: 500 }
    );
  }
}