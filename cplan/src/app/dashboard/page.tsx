"use client";

import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Send,
  Clock,
  CheckCircle,
  AlertCircle,
  TrendingUp,
  Users,
  FileText,
  Calendar,
  Activity,
  BarChart3,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Link from "next/link";

// Mock data - will be replaced with API calls
const stats = {
  totalCommunications: 156,
  published: 89,
  scheduled: 23,
  draft: 44,
  avgEngagement: 78.5,
  activeUsers: 1245,
  pendingApprovals: 7,
  upcomingDeadlines: 3,
};

const recentCommunications = [
  {
    id: "COM-1A2B3C4D-XYZ123",
    title: "Q1 2025 Strategic Update",
    status: "PUBLISHED",
    type: "ANNOUNCEMENT",
    priority: "HIGH",
    publishDate: "2025-01-15T10:00:00",
    engagement: 92,
  },
  {
    id: "COM-2B3C4D5E-ABC456",
    title: "New Remote Work Policy",
    status: "REVIEW",
    type: "POLICY",
    priority: "MEDIUM",
    publishDate: "2025-01-20T14:00:00",
    engagement: null,
  },
  {
    id: "COM-3C4D5E6F-DEF789",
    title: "February Newsletter Draft",
    status: "DRAFT",
    type: "NEWSLETTER",
    priority: "LOW",
    publishDate: null,
    engagement: null,
  },
];

const upcomingSchedule = [
  { date: "2025-01-18", count: 3, items: ["Team Update", "Product Launch", "Training Reminder"] },
  { date: "2025-01-19", count: 2, items: ["Weekly Digest", "Event Invitation"] },
  { date: "2025-01-20", count: 4, items: ["Policy Update", "Survey Launch", "Department News", "System Maintenance"] },
];

const performanceMetrics = [
  { channel: "Email", sent: 4520, opened: 3214, clicked: 1876, rate: 71.1 },
  { channel: "Intranet", sent: 8932, opened: 5421, clicked: 3200, rate: 60.8 },
  { channel: "Teams", sent: 3456, opened: 3102, clicked: 892, rate: 89.8 },
  { channel: "Mobile", sent: 2341, opened: 1987, clicked: 743, rate: 84.9 },
];

export default function DashboardPage() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Simulate loading
    setTimeout(() => setLoading(false), 1000);
  }, []);

  const getStatusBadge = (status: string) => {
    const variants: Record<string, any> = {
      PUBLISHED: "success",
      REVIEW: "warning",
      DRAFT: "secondary",
      APPROVED: "info",
      SCHEDULED: "info",
    };
    return <Badge variant={variants[status] || "default"}>{status}</Badge>;
  };

  const getPriorityBadge = (priority: string) => {
    const variants: Record<string, any> = {
      HIGH: "destructive",
      URGENT: "destructive",
      MEDIUM: "warning",
      LOW: "secondary",
    };
    return <Badge variant={variants[priority] || "default"}>{priority}</Badge>;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-secondary-900">Communications Dashboard</h1>
          <p className="text-neutral-600 mt-1">Monitor and manage your internal communications</p>
        </div>
        <div className="flex space-x-3">
          <Button variant="outline" asChild>
            <Link href="/analytics">
              <BarChart3 className="h-4 w-4 mr-2" />
              View Analytics
            </Link>
          </Button>
          <Button asChild>
            <Link href="/communications/new">
              <FileText className="h-4 w-4 mr-2" />
              New Communication
            </Link>
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Communications</CardTitle>
            <LayoutDashboard className="h-4 w-4 text-neutral-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.totalCommunications}</div>
            <p className="text-xs text-neutral-600 mt-1">
              <TrendingUp className="h-3 w-3 inline mr-1 text-success-500" />
              +12% from last month
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Published</CardTitle>
            <CheckCircle className="h-4 w-4 text-success-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.published}</div>
            <p className="text-xs text-neutral-600 mt-1">{stats.scheduled} scheduled</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg. Engagement</CardTitle>
            <Activity className="h-4 w-4 text-info-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.avgEngagement}%</div>
            <p className="text-xs text-neutral-600 mt-1">Across all channels</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pending Approvals</CardTitle>
            <AlertCircle className="h-4 w-4 text-warning-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.pendingApprovals}</div>
            <p className="text-xs text-neutral-600 mt-1">{stats.upcomingDeadlines} deadlines approaching</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Communications */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent Communications</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {recentCommunications.map((comm) => (
                <div key={comm.id} className="flex items-center justify-between p-4 border rounded-lg hover:bg-neutral-50 transition-colors">
                  <div className="flex-1">
                    <div className="flex items-center space-x-2">
                      <Link href={`/communications/${comm.id}`} className="font-medium hover:text-primary transition-colors">
                        {comm.title}
                      </Link>
                      {getStatusBadge(comm.status)}
                      {getPriorityBadge(comm.priority)}
                    </div>
                    <div className="flex items-center space-x-4 mt-2 text-sm text-neutral-600">
                      <span className="font-mono text-xs">{comm.id}</span>
                      <Badge variant="outline">{comm.type}</Badge>
                      {comm.engagement && (
                        <span className="flex items-center">
                          <Activity className="h-3 w-3 mr-1" />
                          {comm.engagement}%
                        </span>
                      )}
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" asChild>
                    <Link href={`/communications/${comm.id}`}>View</Link>
                  </Button>
                </div>
              ))}
            </div>
            <div className="mt-4 text-center">
              <Button variant="outline" asChild>
                <Link href="/communications">View All Communications</Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Upcoming Schedule */}
        <Card>
          <CardHeader>
            <CardTitle>Upcoming Schedule</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {upcomingSchedule.map((day) => (
                <div key={day.date} className="border-l-2 border-primary pl-4">
                  <div className="flex items-center justify-between">
                    <div className="font-medium">
                      {new Date(day.date).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
                    </div>
                    <Badge variant="secondary">{day.count} items</Badge>
                  </div>
                  <div className="mt-2 space-y-1">
                    {day.items.slice(0, 2).map((item, idx) => (
                      <p key={idx} className="text-sm text-neutral-600">• {item}</p>
                    ))}
                    {day.items.length > 2 && (
                      <p className="text-sm text-neutral-500">+{day.items.length - 2} more</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4">
              <Button variant="outline" className="w-full" asChild>
                <Link href="/calendar">
                  <Calendar className="h-4 w-4 mr-2" />
                  View Full Calendar
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Channel Performance */}
      <Card>
        <CardHeader>
          <CardTitle>Channel Performance</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b">
                  <th className="text-left p-2">Channel</th>
                  <th className="text-right p-2">Sent/Views</th>
                  <th className="text-right p-2">Opened/Unique</th>
                  <th className="text-right p-2">Clicked/Actions</th>
                  <th className="text-right p-2">Rate</th>
                </tr>
              </thead>
              <tbody>
                {performanceMetrics.map((metric) => (
                  <tr key={metric.channel} className="border-b hover:bg-neutral-50">
                    <td className="p-2 font-medium">{metric.channel}</td>
                    <td className="text-right p-2">{metric.sent.toLocaleString()}</td>
                    <td className="text-right p-2">{metric.opened.toLocaleString()}</td>
                    <td className="text-right p-2">{metric.clicked.toLocaleString()}</td>
                    <td className="text-right p-2">
                      <span className={cn(
                        "font-medium",
                        metric.rate > 80 ? "text-success-600" : metric.rate > 60 ? "text-warning-600" : "text-error-600"
                      )}>
                        {metric.rate}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function cn(...classes: string[]) {
  return classes.filter(Boolean).join(" ");
}