import { NextRequest, NextResponse } from "next/server";
import { communicationsService, activitiesService } from "@/lib/microsoft-lists-paginated";

// API authentication middleware
function verifyApiKey(request: NextRequest): boolean {
  const apiKey = request.headers.get("X-API-Key");
  return apiKey === process.env.API_SECRET_KEY;
}

// GET /api/communications-lists/[id] - Get single communication
export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const communication = await communicationsService.findById(params.id);

    if (!communication) {
      return NextResponse.json(
        { error: "Communication not found" },
        { status: 404 }
      );
    }

    // Fetch related data (activities only for now)
    const activities = await activitiesService.findByCommunication(communication.id);

    return NextResponse.json({
      ...communication,
      activities,
    });
  } catch (error) {
    console.error("Error fetching communication:", error);
    return NextResponse.json(
      { error: "Internal server error", details: (error as Error).message },
      { status: 500 }
    );
  }
}

// PATCH /api/communications-lists/[id] - Update communication
export async function PATCH(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();

    const updated = await communicationsService.update(params.id, {
      title: body.title,
      description: body.description,
      content: body.content,
      type: body.type,
      priority: body.priority,
      status: body.status,
      publishDate: body.publishDate,
      expiryDate: body.expiryDate,
      metadata: body.metadata,
      aiSuggestions: body.aiSuggestions,
      channels: body.channels,
      tags: body.tags,
      userId: body.userId || "system",
    });

    // Send webhook notification to Power Automate
    if (process.env.POWER_AUTOMATE_WEBHOOK_URL) {
      await fetch(process.env.POWER_AUTOMATE_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event: "communication.updated",
          data: updated,
        }),
      }).catch(console.error);
    }

    return NextResponse.json(updated);
  } catch (error) {
    console.error("Error updating communication:", error);
    return NextResponse.json(
      { error: "Internal server error", details: (error as Error).message },
      { status: 500 }
    );
  }
}

// DELETE /api/communications-lists/[id] - Archive/Delete communication
export async function DELETE(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const archived = await communicationsService.delete(params.id);

    if (!archived) {
      return NextResponse.json(
        { error: "Communication not found" },
        { status: 404 }
      );
    }

    // Send webhook notification
    if (process.env.POWER_AUTOMATE_WEBHOOK_URL) {
      await fetch(process.env.POWER_AUTOMATE_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event: "communication.archived",
          data: { id: archived.id, trackingId: archived.trackingId },
        }),
      }).catch(console.error);
    }

    return NextResponse.json({
      message: "Communication archived successfully",
      id: archived.id,
    });
  } catch (error) {
    console.error("Error archiving communication:", error);
    return NextResponse.json(
      { error: "Internal server error", details: (error as Error).message },
      { status: 500 }
    );
  }
}