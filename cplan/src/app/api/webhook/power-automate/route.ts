import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import crypto from "crypto";

// Verify webhook signature for security
function verifyWebhookSignature(request: NextRequest, body: string): boolean {
  const signature = request.headers.get("X-Webhook-Signature");
  if (!signature || !process.env.WEBHOOK_SECRET) return false;

  const expectedSignature = crypto
    .createHmac("sha256", process.env.WEBHOOK_SECRET)
    .update(body)
    .digest("hex");

  return signature === expectedSignature;
}

// POST /api/webhook/power-automate - Receive events from Power Automate
export async function POST(request: NextRequest) {
  try {
    const bodyText = await request.text();

    // Verify webhook signature
    if (!verifyWebhookSignature(request, bodyText)) {
      return NextResponse.json({ error: "Invalid signature" }, { status: 401 });
    }

    const body = JSON.parse(bodyText);
    const { event, data } = body;

    console.log(`Received webhook event: ${event}`, data);

    switch (event) {
      case "approval.requested":
        await handleApprovalRequested(data);
        break;

      case "approval.completed":
        await handleApprovalCompleted(data);
        break;

      case "content.published":
        await handleContentPublished(data);
        break;

      case "metrics.updated":
        await handleMetricsUpdated(data);
        break;

      case "feedback.received":
        await handleFeedbackReceived(data);
        break;

      case "schedule.trigger":
        await handleScheduleTrigger(data);
        break;

      default:
        console.log(`Unknown event type: ${event}`);
    }

    return NextResponse.json({ success: true, event });
  } catch (error) {
    console.error("Webhook error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

// Handle approval request from Power Automate
async function handleApprovalRequested(data: any) {
  const { communicationId, approverId, level, notes } = data;

  const approval = await prisma.approval.create({
    data: {
      communicationId,
      approverId,
      level: level || 1,
      status: "PENDING",
      comments: notes,
    },
  });

  // Create notification for approver
  await prisma.notification.create({
    data: {
      userId: approverId,
      type: "APPROVAL_REQUIRED",
      title: "Approval Required",
      message: `You have a new communication to approve: ${communicationId}`,
      link: `/approvals/${approval.id}`,
    },
  });

  // Update communication status
  await prisma.communication.update({
    where: { id: communicationId },
    data: { status: "REVIEW" },
  });

  // Log activity
  await prisma.activity.create({
    data: {
      type: "COMMENTED",
      description: "Approval requested via Power Automate",
      communicationId,
      userId: approverId,
      metadata: data,
    },
  });
}

// Handle approval completion
async function handleApprovalCompleted(data: any) {
  const { approvalId, status, comments, approverId } = data;

  const approval = await prisma.approval.update({
    where: { id: approvalId },
    data: {
      status: status, // APPROVED, REJECTED, REQUESTED_CHANGES
      comments,
      approvedAt: status === "APPROVED" ? new Date() : null,
    },
    include: {
      communication: true,
    },
  });

  // Update communication status based on approval
  const newStatus = status === "APPROVED" ? "APPROVED" :
                   status === "REJECTED" ? "DRAFT" : "REVIEW";

  await prisma.communication.update({
    where: { id: approval.communicationId },
    data: { status: newStatus },
  });

  // Notify owner
  await prisma.notification.create({
    data: {
      userId: approval.communication.ownerId,
      type: "APPROVAL_RECEIVED",
      title: `Communication ${status.toLowerCase()}`,
      message: `Your communication "${approval.communication.title}" has been ${status.toLowerCase()}`,
      link: `/communications/${approval.communicationId}`,
    },
  });

  // Log activity
  await prisma.activity.create({
    data: {
      type: status === "APPROVED" ? "APPROVED" : "REJECTED",
      description: `Communication ${status.toLowerCase()} via Power Automate`,
      communicationId: approval.communicationId,
      userId: approverId,
      metadata: { comments },
    },
  });
}

// Handle content published event
async function handleContentPublished(data: any) {
  const { communicationId, channels, publishedAt } = data;

  // Update communication status
  await prisma.communication.update({
    where: { id: communicationId },
    data: {
      status: "PUBLISHED",
      publishDate: new Date(publishedAt),
    },
  });

  // Update channel statuses
  if (channels && Array.isArray(channels)) {
    for (const channel of channels) {
      await prisma.communicationChannel.updateMany({
        where: {
          communicationId,
          channel: channel.name,
        },
        data: {
          status: "PUBLISHED",
          publishedAt: new Date(publishedAt),
          metadata: channel.metadata,
        },
      });
    }
  }

  // Log activity
  await prisma.activity.create({
    data: {
      type: "PUBLISHED",
      description: "Content published via Power Automate",
      communicationId,
      userId: "system",
      metadata: data,
    },
  });
}

// Handle metrics update
async function handleMetricsUpdated(data: any) {
  const { communicationId, channel, metrics } = data;

  await prisma.communicationMetric.upsert({
    where: {
      communicationId_channel: {
        communicationId,
        channel,
      },
    },
    create: {
      communicationId,
      channel,
      ...metrics,
    },
    update: metrics,
  });

  // Log activity
  await prisma.activity.create({
    data: {
      type: "UPDATED",
      description: `Metrics updated for ${channel}`,
      communicationId,
      userId: "system",
      metadata: metrics,
    },
  });
}

// Handle feedback received
async function handleFeedbackReceived(data: any) {
  const { communicationId, userId, rating, comment, sentiment } = data;

  await prisma.feedback.create({
    data: {
      communicationId,
      userId,
      rating,
      comment,
      sentiment: sentiment || "NEUTRAL",
      isAnonymous: !userId,
    },
  });

  // Notify communication owner
  const communication = await prisma.communication.findUnique({
    where: { id: communicationId },
    select: { ownerId: true, title: true },
  });

  if (communication) {
    await prisma.notification.create({
      data: {
        userId: communication.ownerId,
        type: "FEEDBACK_RECEIVED",
        title: "New Feedback",
        message: `New feedback received for "${communication.title}"`,
        link: `/communications/${communicationId}#feedback`,
      },
    });
  }
}

// Handle scheduled trigger
async function handleScheduleTrigger(data: any) {
  const { action, filters } = data;

  switch (action) {
    case "publish_scheduled":
      // Find and publish scheduled communications
      const toPublish = await prisma.communication.findMany({
        where: {
          status: "SCHEDULED",
          publishDate: {
            lte: new Date(),
          },
        },
      });

      for (const comm of toPublish) {
        await prisma.communication.update({
          where: { id: comm.id },
          data: { status: "PUBLISHED" },
        });

        await prisma.activity.create({
          data: {
            type: "PUBLISHED",
            description: "Auto-published on schedule",
            communicationId: comm.id,
            userId: "system",
          },
        });
      }
      break;

    case "expire_old":
      // Archive expired communications
      const toExpire = await prisma.communication.findMany({
        where: {
          status: "PUBLISHED",
          expiryDate: {
            lte: new Date(),
          },
        },
      });

      for (const comm of toExpire) {
        await prisma.communication.update({
          where: { id: comm.id },
          data: { status: "EXPIRED" },
        });

        await prisma.activity.create({
          data: {
            type: "ARCHIVED",
            description: "Auto-expired based on expiry date",
            communicationId: comm.id,
            userId: "system",
          },
        });
      }
      break;

    case "send_reminders":
      // Send deadline reminders
      const upcoming = await prisma.communication.findMany({
        where: {
          status: "DRAFT",
          publishDate: {
            gte: new Date(),
            lte: new Date(Date.now() + 24 * 60 * 60 * 1000), // Next 24 hours
          },
        },
        include: {
          owner: true,
        },
      });

      for (const comm of upcoming) {
        await prisma.notification.create({
          data: {
            userId: comm.ownerId,
            type: "DEADLINE_APPROACHING",
            title: "Publication Deadline Approaching",
            message: `"${comm.title}" is scheduled for publication soon`,
            link: `/communications/${comm.id}`,
          },
        });
      }
      break;
  }
}