import { UserRole } from "@prisma/client";
import NextAuth from "next-auth";

declare module "next-auth" {
  interface User {
    id: string;
    role: UserRole;
    department?: string | null;
    location?: string | null;
  }

  interface Session {
    user: User & {
      id: string;
      role: UserRole;
      department?: string | null;
      location?: string | null;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id: string;
    role: UserRole;
    department?: string | null;
    location?: string | null;
  }
}