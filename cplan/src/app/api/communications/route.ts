import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { generateTrackingId } from "@/lib/utils";

// API authentication middleware
function verifyApiKey(request: NextRequest): boolean {
  const apiKey = request.headers.get("X-API-Key");
  return apiKey === process.env.API_SECRET_KEY;
}

// GET /api/communications - List all communications with filters
export async function GET(request: NextRequest) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const searchParams = request.nextUrl.searchParams;
    const status = searchParams.get("status");
    const type = searchParams.get("type");
    const priority = searchParams.get("priority");
    const limit = parseInt(searchParams.get("limit") || "50");
    const offset = parseInt(searchParams.get("offset") || "0");

    const where: any = {};
    if (status) where.status = status;
    if (type) where.type = type;
    if (priority) where.priority = priority;

    const communications = await prisma.communication.findMany({
      where,
      take: limit,
      skip: offset,
      orderBy: { createdAt: "desc" },
      include: {
        owner: {
          select: {
            id: true,
            name: true,
            email: true,
          },
        },
        channels: true,
        metrics: true,
        tags: true,
      },
    });

    const total = await prisma.communication.count({ where });

    return NextResponse.json({
      data: communications,
      pagination: {
        total,
        limit,
        offset,
        hasMore: offset + limit < total,
      },
    });
  } catch (error) {
    console.error("Error fetching communications:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

// POST /api/communications - Create new communication
export async function POST(request: NextRequest) {
  try {
    if (!verifyApiKey(request)) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();
    const trackingId = generateTrackingId();

    const communication = await prisma.communication.create({
      data: {
        trackingId,
        title: body.title,
        description: body.description,
        content: body.content,
        type: body.type,
        priority: body.priority,
        status: body.status || "DRAFT",
        publishDate: body.publishDate ? new Date(body.publishDate) : null,
        expiryDate: body.expiryDate ? new Date(body.expiryDate) : null,
        ownerId: body.ownerId,
        templateId: body.templateId,
        packId: body.packId,
        metadata: body.metadata,
        channels: {
          create: body.channels?.map((channel: string) => ({
            channel,
            status: "PENDING",
          })),
        },
        tags: {
          connectOrCreate: body.tags?.map((tag: string) => ({
            where: { name: tag },
            create: { name: tag },
          })),
        },
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
        type: "CREATED",
        description: `Communication "${communication.title}" created`,
        communicationId: communication.id,
        userId: body.ownerId,
      },
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
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

// PUT /api/communications - Bulk update communications
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

    const result = await prisma.communication.updateMany({
      where: { id: { in: ids } },
      data: updates,
    });

    return NextResponse.json({
      message: "Communications updated",
      count: result.count,
    });
  } catch (error) {
    console.error("Error updating communications:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}