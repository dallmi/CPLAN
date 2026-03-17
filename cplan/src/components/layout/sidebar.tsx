"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FileText,
  Calendar,
  Users,
  BarChart3,
  Settings,
  PlusCircle,
  FolderOpen,
  Bell,
  MessageSquare,
  Layers,
  Workflow,
  Send,
  Archive,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navigation = [
  { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { name: "Create", href: "/communications/new", icon: PlusCircle },
  { name: "Communications", href: "/communications", icon: FileText },
  { name: "Calendar", href: "/calendar", icon: Calendar },
  { name: "Templates", href: "/templates", icon: FolderOpen },
  { name: "Packs", href: "/packs", icon: Layers },
  { name: "Approvals", href: "/approvals", icon: Workflow },
  { name: "Analytics", href: "/analytics", icon: BarChart3 },
  { name: "Distribution", href: "/distribution", icon: Send },
  { name: "Archive", href: "/archive", icon: Archive },
  { name: "Feedback", href: "/feedback", icon: MessageSquare },
  { name: "Team", href: "/team", icon: Users },
  { name: "Notifications", href: "/notifications", icon: Bell },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="flex h-full w-64 flex-col bg-white border-r border-neutral-200">
      <div className="flex h-16 items-center px-6 border-b border-neutral-200">
        <Link href="/dashboard" className="flex items-center space-x-2">
          <div className="w-8 h-8 bg-primary rounded-md flex items-center justify-center">
            <span className="text-white font-bold text-lg">C</span>
          </div>
          <span className="text-xl font-bold text-secondary-900">CPLAN</span>
        </Link>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4 overflow-y-auto">
        {navigation.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "flex items-center px-3 py-2 text-sm font-medium rounded-md transition-colors",
                isActive
                  ? "bg-primary text-white"
                  : "text-neutral-700 hover:text-neutral-900 hover:bg-neutral-100"
              )}
            >
              <item.icon className={cn("mr-3 h-5 w-5", isActive ? "text-white" : "text-neutral-500")} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-neutral-200 p-4">
        <div className="flex items-center">
          <div className="w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center">
            <span className="text-primary-600 text-sm font-medium">JD</span>
          </div>
          <div className="ml-3">
            <p className="text-sm font-medium text-neutral-900">John Doe</p>
            <p className="text-xs text-neutral-500">Admin</p>
          </div>
        </div>
      </div>
    </div>
  );
}