import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

// API authentication middleware
function verifyApiKey(request: NextRequest): boolean {
  const apiKey = request.headers.get("X-API-Key");
  return apiKey === process.env.API_SECRET_KEY;
}

// GET /api/communications/[id] - Get single communication
export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const communication = await prisma.communication.findFirst({
      where: {
        OR: [{ id: params.id }, { trackingId: params.id }],
      },
      include: {
        owner: true,
        channels: true,
        approvals: {
          include: { approver: true },
        },
        metrics: true,
        attachments: true,
        tags: true,
        versions: {
          orderBy: { version: "desc" },
          take: 5,
        },
        feedbacks: {
          include: { user: true },
        },
        assignments: {
          include: { user: true },
        },
        pack: true,
        template: true,
      },
    });

    if (!communication) {
      return NextResponse.json(
        { error: "Communication not found" },
        { status: 404 }
      );
    }

    return NextResponse.json(communication);
  } catch (error) {
    console.error("Error fetching communication:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

// PATCH /api/communications/[id] - Update communication
export async function PATCH(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();

    // Find the communication
    const existing = await prisma.communication.findFirst({
      where: {
        OR: [{ id: params.id }, { trackingId: params.id }],
      },
    });

    if (!existing) {
      return NextResponse.json(
        { error: "Communication not found" },
        { status: 404 }
      );
    }

    // Create a version before updating
    const lastVersion = await prisma.communicationVersion.findFirst({
      where: { communicationId: existing.id },
      orderBy: { version: "desc" },
    });

    await prisma.communicationVersion.create({
      data: {
        communicationId: existing.id,
        version: (lastVersion?.version || 0) + 1,
        content: existing.content,
        metadata: existing.metadata,
        createdBy: body.userId || "system",
        changeNote: body.changeNote || "Updated via API",
      },
    });

    // Update the communication
    const updated = await prisma.communication.update({
      where: { id: existing.id },
      data: {
        title: body.title,
        description: body.description,
        content: body.content,
        type: body.type,
        priority: body.priority,
        status: body.status,
        publishDate: body.publishDate ? new Date(body.publishDate) : undefined,
        expiryDate: body.expiryDate ? new Date(body.expiryDate) : undefined,
        metadata: body.metadata,
        aiSuggestions: body.aiSuggestions,
      },
      include: {
        owner: true,
        channels: true,
        tags: true,
      },
    });

    // Log activity
    await prisma.activity.create({
      data: {
        type: "UPDATED",
        description: `Communication "${updated.title}" updated`,
        communicationId: updated.id,
        userId: body.userId || "system",
        metadata: { changes: body },
      },
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
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

// DELETE /api/communications/[id] - Archive/Delete communication
export async function DELETE(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const communication = await prisma.communication.findFirst({
      where: {
        OR: [{ id: params.id }, { trackingId: params.id }],
      },
    });

    if (!communication) {
      return NextResponse.json(
        { error: "Communication not found" },
        { status: 404 }
      );
    }

    // Archive instead of delete
    const archived = await prisma.communication.update({
      where: { id: communication.id },
      data: { status: "ARCHIVED" },
    });

    // Log activity
    await prisma.activity.create({
      data: {
        type: "ARCHIVED",
        description: `Communication "${archived.title}" archived`,
        communicationId: archived.id,
        userId: "system",
      },
    });

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
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}