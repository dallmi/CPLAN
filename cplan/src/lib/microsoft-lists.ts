import { graphClient } from "./graph-client";
import { generateTrackingId } from "./utils";

// Microsoft Lists service layer
// This replaces Prisma with Microsoft Graph API calls to SharePoint Lists

const SITE_ID = process.env.SHAREPOINT_SITE_ID!;

// Helper to convert List item to our Communication type
function mapListItemToCommunication(item: any) {
  return {
    id: item.id,
    trackingId: item.fields.TrackingId,
    title: item.fields.Title,
    description: item.fields.Description,
    content: item.fields.Content,
    status: item.fields.Status,
    priority: item.fields.Priority,
    type: item.fields.Type,
    publishDate: item.fields.PublishDate ? new Date(item.fields.PublishDate) : null,
    expiryDate: item.fields.ExpiryDate ? new Date(item.fields.ExpiryDate) : null,
    ownerId: item.fields.OwnerId,
    ownerEmail: item.fields.OwnerEmail,
    ownerName: item.fields.OwnerName,
    templateId: item.fields.TemplateId,
    packId: item.fields.PackId,
    metadata: item.fields.Metadata ? JSON.parse(item.fields.Metadata) : null,
    aiSuggestions: item.fields.AISuggestions ? JSON.parse(item.fields.AISuggestions) : null,
    channels: item.fields.Channels ? JSON.parse(item.fields.Channels) : [],
    tags: item.fields.Tags ? JSON.parse(item.fields.Tags) : [],
    createdAt: new Date(item.createdDateTime),
    updatedAt: new Date(item.lastModifiedDateTime),
  };
}

// Communications Service
export const communicationsService = {
  // Get all communications with optional filters
  async findMany(filters?: {
    status?: string;
    type?: string;
    priority?: string;
    limit?: number;
    offset?: number;
  }) {
    try {
      const listId = process.env.COMMUNICATIONS_LIST_ID!;
      let endpoint = `/sites/${SITE_ID}/lists/${listId}/items?expand=fields`;

      // Build OData filter query
      const filterParts: string[] = [];
      if (filters?.status) filterParts.push(`fields/Status eq '${filters.status}'`);
      if (filters?.type) filterParts.push(`fields/Type eq '${filters.type}'`);
      if (filters?.priority) filterParts.push(`fields/Priority eq '${filters.priority}'`);

      if (filterParts.length > 0) {
        endpoint += `&$filter=${filterParts.join(" and ")}`;
      }

      // Add ordering
      endpoint += `&$orderby=createdDateTime desc`;

      // Add pagination
      if (filters?.limit) {
        endpoint += `&$top=${filters.limit}`;
      }
      if (filters?.offset) {
        endpoint += `&$skip=${filters.offset}`;
      }

      const response = await graphClient.api(endpoint).get();

      return {
        items: response.value.map(mapListItemToCommunication),
        total: response["@odata.count"] || response.value.length,
      };
    } catch (error) {
      console.error("Error fetching communications:", error);
      throw error;
    }
  },

  // Get single communication by ID or tracking ID
  async findById(id: string) {
    try {
      const listId = process.env.COMMUNICATIONS_LIST_ID!;

      // Try to find by tracking ID first
      let endpoint = `/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$filter=fields/TrackingId eq '${id}'`;
      let response = await graphClient.api(endpoint).get();

      if (response.value.length > 0) {
        return mapListItemToCommunication(response.value[0]);
      }

      // If not found, try by item ID
      endpoint = `/sites/${SITE_ID}/lists/${listId}/items/${id}?expand=fields`;
      response = await graphClient.api(endpoint).get();

      return mapListItemToCommunication(response);
    } catch (error) {
      console.error("Error fetching communication:", error);
      return null;
    }
  },

  // Create new communication
  async create(data: any) {
    try {
      const listId = process.env.COMMUNICATIONS_LIST_ID!;
      const trackingId = generateTrackingId();

      const fields = {
        TrackingId: trackingId,
        Title: data.title,
        Description: data.description || "",
        Content: data.content,
        Status: data.status || "DRAFT",
        Priority: data.priority || "MEDIUM",
        Type: data.type,
        PublishDate: data.publishDate || null,
        ExpiryDate: data.expiryDate || null,
        OwnerId: data.ownerId,
        OwnerEmail: data.ownerEmail,
        OwnerName: data.ownerName,
        TemplateId: data.templateId || null,
        PackId: data.packId || null,
        Metadata: data.metadata ? JSON.stringify(data.metadata) : null,
        AISuggestions: data.aiSuggestions ? JSON.stringify(data.aiSuggestions) : null,
        Channels: data.channels ? JSON.stringify(data.channels) : "[]",
        Tags: data.tags ? JSON.stringify(data.tags) : "[]",
      };

      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items`)
        .post({ fields });

      // Log activity
      await activitiesService.create({
        type: "CREATED",
        description: `Communication "${data.title}" created`,
        communicationId: response.id,
        userId: data.ownerId,
        metadata: { trackingId },
      });

      return mapListItemToCommunication(response);
    } catch (error) {
      console.error("Error creating communication:", error);
      throw error;
    }
  },

  // Update communication
  async update(id: string, data: any) {
    try {
      const listId = process.env.COMMUNICATIONS_LIST_ID!;

      // Find the item first
      const existing = await this.findById(id);
      if (!existing) throw new Error("Communication not found");

      const fields: any = {};
      if (data.title !== undefined) fields.Title = data.title;
      if (data.description !== undefined) fields.Description = data.description;
      if (data.content !== undefined) fields.Content = data.content;
      if (data.status !== undefined) fields.Status = data.status;
      if (data.priority !== undefined) fields.Priority = data.priority;
      if (data.type !== undefined) fields.Type = data.type;
      if (data.publishDate !== undefined) fields.PublishDate = data.publishDate;
      if (data.expiryDate !== undefined) fields.ExpiryDate = data.expiryDate;
      if (data.metadata !== undefined) fields.Metadata = JSON.stringify(data.metadata);
      if (data.aiSuggestions !== undefined) fields.AISuggestions = JSON.stringify(data.aiSuggestions);
      if (data.channels !== undefined) fields.Channels = JSON.stringify(data.channels);
      if (data.tags !== undefined) fields.Tags = JSON.stringify(data.tags);

      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items/${existing.id}/fields`)
        .patch(fields);

      // Log activity
      await activitiesService.create({
        type: "UPDATED",
        description: `Communication "${data.title || existing.title}" updated`,
        communicationId: existing.id,
        userId: data.userId || "system",
        metadata: { changes: data },
      });

      return mapListItemToCommunication({ id: existing.id, fields: response });
    } catch (error) {
      console.error("Error updating communication:", error);
      throw error;
    }
  },

  // Delete (archive) communication
  async delete(id: string) {
    try {
      return await this.update(id, { status: "ARCHIVED" });
    } catch (error) {
      console.error("Error archiving communication:", error);
      throw error;
    }
  },

  // Count communications
  async count(filters?: { status?: string; type?: string; priority?: string }) {
    const result = await this.findMany({ ...filters, limit: 1 });
    return result.total;
  },
};

// Templates Service
export const templatesService = {
  async findMany() {
    try {
      const listId = process.env.TEMPLATES_LIST_ID!;
      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$orderby=createdDateTime desc`)
        .get();

      return response.value.map((item: any) => ({
        id: item.id,
        name: item.fields.Title,
        description: item.fields.Description,
        content: item.fields.Content,
        type: item.fields.Type,
        category: item.fields.Category,
        isActive: item.fields.IsActive,
        usageCount: item.fields.UsageCount || 0,
        variables: item.fields.Variables ? JSON.parse(item.fields.Variables) : null,
        createdAt: new Date(item.createdDateTime),
        updatedAt: new Date(item.lastModifiedDateTime),
      }));
    } catch (error) {
      console.error("Error fetching templates:", error);
      return [];
    }
  },

  async findById(id: string) {
    try {
      const listId = process.env.TEMPLATES_LIST_ID!;
      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items/${id}?expand=fields`)
        .get();

      return {
        id: response.id,
        name: response.fields.Title,
        description: response.fields.Description,
        content: response.fields.Content,
        type: response.fields.Type,
        category: response.fields.Category,
        isActive: response.fields.IsActive,
        usageCount: response.fields.UsageCount || 0,
        variables: response.fields.Variables ? JSON.parse(response.fields.Variables) : null,
      };
    } catch (error) {
      console.error("Error fetching template:", error);
      return null;
    }
  },

  async create(data: any) {
    try {
      const listId = process.env.TEMPLATES_LIST_ID!;
      const fields = {
        Title: data.name,
        Description: data.description || "",
        Content: data.content,
        Type: data.type,
        Category: data.category || "",
        IsActive: data.isActive !== false,
        UsageCount: 0,
        Variables: data.variables ? JSON.stringify(data.variables) : null,
      };

      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items`)
        .post({ fields });

      return { id: response.id, ...fields };
    } catch (error) {
      console.error("Error creating template:", error);
      throw error;
    }
  },
};

// Activities Service
export const activitiesService = {
  async create(data: {
    type: string;
    description: string;
    communicationId?: string;
    userId: string;
    metadata?: any;
  }) {
    try {
      const listId = process.env.ACTIVITIES_LIST_ID!;
      const fields = {
        Title: data.description,
        Type: data.type,
        Description: data.description,
        CommunicationId: data.communicationId || null,
        UserId: data.userId,
        Metadata: data.metadata ? JSON.stringify(data.metadata) : null,
      };

      await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items`)
        .post({ fields });
    } catch (error) {
      console.error("Error creating activity:", error);
    }
  },

  async findByCommunication(communicationId: string) {
    try {
      const listId = process.env.ACTIVITIES_LIST_ID!;
      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$filter=fields/CommunicationId eq '${communicationId}'&$orderby=createdDateTime desc`)
        .get();

      return response.value.map((item: any) => ({
        id: item.id,
        type: item.fields.Type,
        description: item.fields.Description,
        userId: item.fields.UserId,
        metadata: item.fields.Metadata ? JSON.parse(item.fields.Metadata) : null,
        createdAt: new Date(item.createdDateTime),
      }));
    } catch (error) {
      console.error("Error fetching activities:", error);
      return [];
    }
  },
};

// Approvals Service
export const approvalsService = {
  async create(data: {
    communicationId: string;
    approverId: string;
    level?: number;
    comments?: string;
  }) {
    try {
      const listId = process.env.APPROVALS_LIST_ID!;
      const fields = {
        Title: `Approval for ${data.communicationId}`,
        CommunicationId: data.communicationId,
        ApproverId: data.approverId,
        Status: "PENDING",
        Level: data.level || 1,
        Comments: data.comments || "",
      };

      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items`)
        .post({ fields });

      return { id: response.id, ...fields };
    } catch (error) {
      console.error("Error creating approval:", error);
      throw error;
    }
  },

  async update(id: string, data: { status: string; comments?: string }) {
    try {
      const listId = process.env.APPROVALS_LIST_ID!;
      const fields: any = {
        Status: data.status,
      };

      if (data.comments) fields.Comments = data.comments;
      if (data.status === "APPROVED") fields.ApprovedAt = new Date().toISOString();

      await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items/${id}/fields`)
        .patch(fields);

      return { id, ...fields };
    } catch (error) {
      console.error("Error updating approval:", error);
      throw error;
    }
  },

  async findByCommunication(communicationId: string) {
    try {
      const listId = process.env.APPROVALS_LIST_ID!;
      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$filter=fields/CommunicationId eq '${communicationId}'`)
        .get();

      return response.value.map((item: any) => ({
        id: item.id,
        communicationId: item.fields.CommunicationId,
        approverId: item.fields.ApproverId,
        status: item.fields.Status,
        level: item.fields.Level,
        comments: item.fields.Comments,
        approvedAt: item.fields.ApprovedAt ? new Date(item.fields.ApprovedAt) : null,
        createdAt: new Date(item.createdDateTime),
      }));
    } catch (error) {
      console.error("Error fetching approvals:", error);
      return [];
    }
  },
};

// Metrics Service
export const metricsService = {
  async upsert(data: {
    communicationId: string;
    channel: string;
    sent?: number;
    delivered?: number;
    opened?: number;
    clicked?: number;
    bounced?: number;
  }) {
    try {
      const listId = process.env.METRICS_LIST_ID!;

      // Check if metric exists
      const existing = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$filter=fields/CommunicationId eq '${data.communicationId}' and fields/Channel eq '${data.channel}'`)
        .get();

      const fields = {
        Title: `${data.communicationId}-${data.channel}`,
        CommunicationId: data.communicationId,
        Channel: data.channel,
        Sent: data.sent || 0,
        Delivered: data.delivered || 0,
        Opened: data.opened || 0,
        Clicked: data.clicked || 0,
        Bounced: data.bounced || 0,
      };

      if (existing.value.length > 0) {
        // Update existing
        await graphClient
          .api(`/sites/${SITE_ID}/lists/${listId}/items/${existing.value[0].id}/fields`)
          .patch(fields);
        return { id: existing.value[0].id, ...fields };
      } else {
        // Create new
        const response = await graphClient
          .api(`/sites/${SITE_ID}/lists/${listId}/items`)
          .post({ fields });
        return { id: response.id, ...fields };
      }
    } catch (error) {
      console.error("Error upserting metrics:", error);
      throw error;
    }
  },

  async findByCommunication(communicationId: string) {
    try {
      const listId = process.env.METRICS_LIST_ID!;
      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$filter=fields/CommunicationId eq '${communicationId}'`)
        .get();

      return response.value.map((item: any) => ({
        id: item.id,
        communicationId: item.fields.CommunicationId,
        channel: item.fields.Channel,
        sent: item.fields.Sent || 0,
        delivered: item.fields.Delivered || 0,
        opened: item.fields.Opened || 0,
        clicked: item.fields.Clicked || 0,
        bounced: item.fields.Bounced || 0,
      }));
    } catch (error) {
      console.error("Error fetching metrics:", error);
      return [];
    }
  },
};

// Packs Service
export const packsService = {
  async findMany() {
    try {
      const listId = process.env.PACKS_LIST_ID!;
      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$orderby=createdDateTime desc`)
        .get();

      return response.value.map((item: any) => ({
        id: item.id,
        name: item.fields.Title,
        description: item.fields.Description,
        createdAt: new Date(item.createdDateTime),
        updatedAt: new Date(item.lastModifiedDateTime),
      }));
    } catch (error) {
      console.error("Error fetching packs:", error);
      return [];
    }
  },

  async create(data: { name: string; description?: string }) {
    try {
      const listId = process.env.PACKS_LIST_ID!;
      const fields = {
        Title: data.name,
        Description: data.description || "",
      };

      const response = await graphClient
        .api(`/sites/${SITE_ID}/lists/${listId}/items`)
        .post({ fields });

      return { id: response.id, ...fields };
    } catch (error) {
      console.error("Error creating pack:", error);
      throw error;
    }
  },
};