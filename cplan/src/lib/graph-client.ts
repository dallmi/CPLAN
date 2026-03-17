import { Client } from "@microsoft/microsoft-graph-client";
import { ClientSecretCredential } from "@azure/identity";
import "isomorphic-fetch";

// Azure AD credentials
const credential = new ClientSecretCredential(
  process.env.AZURE_AD_TENANT_ID!,
  process.env.AZURE_AD_CLIENT_ID!,
  process.env.AZURE_AD_CLIENT_SECRET!
);

// Create Microsoft Graph client with app-only authentication
export function getGraphClient(): Client {
  return Client.initWithMiddleware({
    authProvider: {
      getAccessToken: async () => {
        const tokenResponse = await credential.getToken(
          "https://graph.microsoft.com/.default"
        );
        return tokenResponse.token;
      },
    },
  });
}

// Helper function to get the Graph client
export const graphClient = getGraphClient();