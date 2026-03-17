import { graphClient } from "./graph-client";
import { generateTrackingId } from "./utils";

// Microsoft Lists service layer with UNLIMITED pagination support
// Handles millions of records by using Microsoft Graph API pagination
// No 5K item limitation like SharePoint UI

const SITE_ID = process.env.SHAREPOINT_SITE_ID!;
const PAGE_SIZE = 1000; // Graph API max is 5000, but 1000 is optimal for performance

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

/**
 * Fetch ALL items from a list using pagination
 * This bypasses the 5K SharePoint view threshold completely
 * Can handle millions of records efficiently
 */
async function fetchAllItems(
  listId: string,
  filterQuery?: string,
  orderBy: string = "createdDateTime desc",
  onProgress?: (count: number) => void
): Promise<any[]> {
  const allItems: any[] = [];
  let endpoint = `/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$top=${PAGE_SIZE}&$orderby=${orderBy}`;

  if (filterQuery) {
    endpoint += `&$filter=${filterQuery}`;
  }

  // Add count to get total items
  endpoint += `&$count=true`;

  let hasMore = true;
  let nextLink: string | undefined = endpoint;

  while (hasMore) {
    try {
      const response = await graphClient.api(nextLink).get();

      // Add items to our collection
      allItems.push(...response.value);

      // Report progress
      if (onProgress) {
        onProgress(allItems.length);
      }

      // Check if there are more pages
      if (response["@odata.nextLink"]) {
        nextLink = response["@odata.nextLink"];
      } else {
        hasMore = false;
      }
    } catch (error) {
      console.error("Error fetching page:", error);
      throw error;
    }
  }

  return allItems;
}

/**
 * Fetch items with cursor-based pagination (recommended for large datasets)
 * Returns a page of results plus a continuation token
 */
async function fetchPaginatedItems(
  listId: string,
  options: {
    pageSize?: number;
    skipToken?: string;
    filter?: string;
    orderBy?: string;
  } = {}
): Promise<{
  items: any[];
  nextLink?: string;
  hasMore: boolean;
  total?: number;
}> {
  const pageSize = options.pageSize || PAGE_SIZE;
  let endpoint = `/sites/${SITE_ID}/lists/${listId}/items?expand=fields&$top=${pageSize}`;

  if (options.orderBy) {
    endpoint += `&$orderby=${options.orderBy}`;
  } else {
    endpoint += `&$orderby=createdDateTime desc`;
  }

  if (options.filter) {
    endpoint += `&$filter=${options.filter}`;
  }

  // Add count to get total
  endpoint += `&$count=true`;

  // If skipToken is provided, use the nextLink directly
  const apiUrl = options.skipToken || endpoint;

  const response = await graphClient.api(apiUrl).get();

  return {
    items: response.value,
    nextLink: response["@odata.nextLink"],
    hasMore: !!response["@odata.nextLink"],
    total: response["@odata.count"],
  };
}

// Communications Service with UNLIMITED record support
export const communicationsService = {
  /**
   * Get communications with smart pagination
   * - For small datasets (<1000): Returns all at once
   * - For large datasets: Returns paginated with continuation token
   */
  async findMany(filters?: {
    status?: string;
    type?: string;
    priority?: string;
    limit?: number;
    skipToken?: string; // For cursor-based pagination
    fetchAll?: boolean; // Set to true to get ALL records (use carefully)
  }) {
    try {
      const listId = process.env.COMMUNICATIONS_LIST_ID!;

      // Build OData filter query
      const filterParts: string[] = [];
      if (filters?.status) filterParts.push(`fields/Status eq '${filters.status}'`);
      if (filters?.type) filterParts.push(`fields/Type eq '${filters.type}'`);
      if (filters?.priority) filterParts.push(`fields/Priority eq '${filters.priority}'`);

      const filterQuery = filterParts.length > 0 ? filterParts.join(" and ") : undefined;

      // Option 1: Fetch ALL records (can be millions)
      if (filters?.fetchAll) {
        console.log("Fetching ALL communications from Microsoft Lists...");
        const allItems = await fetchAllItems(
          listId,
          filterQuery,
          "createdDateTime desc",
          (count) => console.log(`Fetched ${count} communications...`)
        );

        return {
          items: allItems.map(mapListItemToCommunication),
          total: allItems.length,
          hasMore: false,
        };
      }

      // Option 2: Cursor-based pagination (recommended for large datasets)
      const pageSize = filters?.limit || PAGE_SIZE;
      const result = await fetchPaginatedItems(listId, {
        pageSize,
        skipToken: filters?.skipToken,
        filter: filterQuery,
        orderBy: "createdDateTime desc",
      });

      return {
        items: result.items.map(mapListItemToCommunication),
        total: result.total,
        hasMore: result.hasMore,
        nextLink: result.nextLink,
        skipToken: result.nextLink, // Can be used for next page
      };
    } catch (error) {
      console.error("Error fetching communications:", error);
      throw error;
    }
  },

  /**
   * Get total count without fetching all items (very efficient)
   */
  async count(filters?: {
    status?: string;
    type?: string;
    priority?: string;
  }): Promise<number> {
    try {
      const listId = process.env.COMMUNICATIONS_LIST_ID!;

      // Build filter
      const filterParts: string[] = [];
      if (filters?.status) filterParts.push(`fields/Status eq '${filters.status}'`);
      if (filters?.type) filterParts.push(`fields/Type eq '${filters.type}'`);
      if (filters?.priority) filterParts.push(`fields/Priority eq '${filters.priority}'`);

      let endpoint = `/sites/${SITE_ID}/lists/${listId}/items?$top=1&$count=true`;

      if (filterParts.length > 0) {
        endpoint += `&$filter=${filterParts.join(" and ")}`;
      }

      const response = await graphClient.api(endpoint).get();
      return response["@odata.count"] || 0;
    } catch (error) {
      console.error("Error counting communications:", error);
      return 0;
    }
  },

  /**
   * Search communications efficiently across large datasets
   * Uses indexed columns for fast searching even with millions of records
   */
  async search(query: {
    searchText?: string;
    status?: string;
    type?: string;
    dateFrom?: Date;
    dateTo?: Date;
    pageSize?: number;
    skipToken?: string;
  }) {
    try {
      const listId = process.env.COMMUNICATIONS_LIST_ID!;
      const filterParts: string[] = [];

      // Text search on indexed columns
      if (query.searchText) {
        // Search in Title and TrackingId (should be indexed)
        filterParts.push(
          `(startswith(fields/Title, '${query.searchText}') or ` +
          `contains(fields/Title, '${query.searchText}') or ` +
          `startswith(fields/TrackingId, '${query.searchText}'))`
        );
      }

      if (query.status) filterParts.push(`fields/Status eq '${query.status}'`);
      if (query.type) filterParts.push(`fields/Type eq '${query.type}'`);

      if (query.dateFrom) {
        filterParts.push(`fields/PublishDate ge ${query.dateFrom.toISOString()}`);
      }
      if (query.dateTo) {
        filterParts.push(`fields/PublishDate le ${query.dateTo.toISOString()}`);
      }

      const filterQuery = filterParts.length > 0 ? filterParts.join(" and ") : undefined;

      const result = await fetchPaginatedItems(listId, {
        pageSize: query.pageSize || 100,
        skipToken: query.skipToken,
        filter: filterQuery,
        orderBy: "createdDateTime desc",
      });

      return {
        items: result.items.map(mapListItemToCommunication),
        total: result.total,
        hasMore: result.hasMore,
        nextLink: result.nextLink,
      };
    } catch (error) {
      console.error("Error searching communications:", error);
      throw error;
    }
  },

  /**
   * Batch operations for bulk updates (can handle thousands of items)
   */
  async bulkUpdate(
    itemIds: string[],
    updates: any,
    onProgress?: (completed: number, total: number) => void
  ) {
    const listId = process.env.COMMUNICATIONS_LIST_ID!;
    const batchSize = 20; // Process in batches to avoid timeouts
    let completed = 0;

    for (let i = 0; i < itemIds.length; i += batchSize) {
      const batch = itemIds.slice(i, i + batchSize);

      // Process batch in parallel
      await Promise.all(
        batch.map(async (id) => {
          try {
            await this.update(id, updates);
            completed++;
            if (onProgress) onProgress(completed, itemIds.length);
          } catch (error) {
            console.error(`Failed to update item ${id}:`, error);
          }
        })
      );
    }

    return { completed, total: itemIds.length };
  },

  // Get single communication by ID or tracking ID
  async findById(id: string) {
    try {
      const listId = process.env.COMMUNICATIONS_LIST_ID!;

      // Try to find by tracking ID first (indexed for fast lookup)
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
};

// Activities Service (similar pagination support)
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

  async findByCommunication(communicationId: string, pageSize: number = 100) {
    try {
      const listId = process.env.ACTIVITIES_LIST_ID!;

      const result = await fetchPaginatedItems(listId, {
        pageSize,
        filter: `fields/CommunicationId eq '${communicationId}'`,
        orderBy: "createdDateTime desc",
      });

      return result.items.map((item: any) => ({
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

// Export utility functions for custom use
export { fetchAllItems, fetchPaginatedItems };