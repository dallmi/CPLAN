"use client";

import { useState, useCallback, useMemo } from "react";
import { Calendar, momentLocalizer, View, Event } from "react-big-calendar";
import moment from "moment";
import "react-big-calendar/lib/css/react-big-calendar.css";
import {
  ChevronLeft,
  ChevronRight,
  Calendar as CalendarIcon,
  Filter,
  Download,
  Upload,
  Plus,
  List,
  Grid3x3,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import toast, { Toaster } from "react-hot-toast";

const localizer = momentLocalizer(moment);

// Custom event type for communications
interface CommunicationEvent extends Event {
  id: string;
  trackingId: string;
  type: string;
  priority: string;
  status: string;
  channels: string[];
  owner: string;
}

// Mock data for calendar events
const mockEvents: CommunicationEvent[] = [
  {
    id: "1",
    trackingId: "COM-1A2B3C4D-XYZ123",
    title: "Q1 Strategic Update",
    start: new Date(2025, 0, 20, 10, 0),
    end: new Date(2025, 0, 20, 11, 0),
    type: "ANNOUNCEMENT",
    priority: "HIGH",
    status: "SCHEDULED",
    channels: ["EMAIL", "INTRANET"],
    owner: "John Doe",
  },
  {
    id: "2",
    trackingId: "COM-2B3C4D5E-ABC456",
    title: "Weekly Team Newsletter",
    start: new Date(2025, 0, 22, 14, 0),
    end: new Date(2025, 0, 22, 15, 0),
    type: "NEWSLETTER",
    priority: "MEDIUM",
    status: "DRAFT",
    channels: ["EMAIL"],
    owner: "Jane Smith",
  },
  {
    id: "3",
    trackingId: "COM-3C4D5E6F-DEF789",
    title: "Emergency System Maintenance",
    start: new Date(2025, 0, 23, 8, 0),
    end: new Date(2025, 0, 23, 9, 0),
    type: "ALERT",
    priority: "URGENT",
    status: "APPROVED",
    channels: ["EMAIL", "SMS", "TEAMS"],
    owner: "IT Team",
  },
  {
    id: "4",
    trackingId: "COM-4D5E6F7G-GHI012",
    title: "Policy Update Review",
    start: new Date(2025, 0, 25, 11, 0),
    end: new Date(2025, 0, 25, 12, 0),
    type: "POLICY",
    priority: "HIGH",
    status: "REVIEW",
    channels: ["INTRANET"],
    owner: "HR Department",
  },
  {
    id: "5",
    trackingId: "COM-5E6F7G8H-JKL345",
    title: "Company Town Hall",
    start: new Date(2025, 0, 28, 15, 0),
    end: new Date(2025, 0, 28, 16, 30),
    type: "EVENT",
    priority: "HIGH",
    status: "PUBLISHED",
    channels: ["EMAIL", "TEAMS", "DIGITAL_SIGNAGE"],
    owner: "Leadership Team",
  },
];

// Custom styles for calendar
const calendarStyles = `
  .rbc-calendar {
    font-family: inherit;
  }
  .rbc-header {
    background: #ECEBE4;
    padding: 10px;
    font-weight: 600;
    border-bottom: 2px solid #CCCABC;
  }
  .rbc-today {
    background-color: #fff1f1;
  }
  .rbc-event {
    border-radius: 4px;
    padding: 2px 5px;
  }
  .rbc-event-high {
    background-color: #e60000;
    border-color: #8A000A;
  }
  .rbc-event-urgent {
    background-color: #8A000A;
    border-color: #620004;
    animation: pulse 2s infinite;
  }
  .rbc-event-medium {
    background-color: #E4A911;
    border-color: #E4A911;
  }
  .rbc-event-low {
    background-color: #B8B3A2;
    border-color: #7A7870;
  }
  @keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.8; }
    100% { opacity: 1; }
  }
`;

export default function CalendarPage() {
  const [events, setEvents] = useState<CommunicationEvent[]>(mockEvents);
  const [view, setView] = useState<View>("month");
  const [date, setDate] = useState(new Date());
  const [selectedEvent, setSelectedEvent] = useState<CommunicationEvent | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState({
    type: "ALL",
    priority: "ALL",
    status: "ALL",
    channel: "ALL",
  });

  // Calendar event handlers
  const handleSelectEvent = useCallback((event: CommunicationEvent) => {
    setSelectedEvent(event);
    toast.custom((t) => (
      <div className={`bg-white p-4 rounded-lg shadow-lg ${t.visible ? "animate-enter" : "animate-leave"}`}>
        <div className="flex justify-between items-start mb-2">
          <h3 className="font-bold">{event.title}</h3>
          <button onClick={() => toast.dismiss(t.id)} className="text-neutral-400 hover:text-neutral-600">
            ×
          </button>
        </div>
        <div className="space-y-2 text-sm">
          <p className="text-neutral-600">ID: {event.trackingId}</p>
          <div className="flex gap-2">
            <Badge variant={event.priority === "URGENT" || event.priority === "HIGH" ? "destructive" : event.priority === "MEDIUM" ? "warning" : "secondary"}>
              {event.priority}
            </Badge>
            <Badge variant="outline">{event.type}</Badge>
            <Badge variant={event.status === "PUBLISHED" ? "success" : "default"}>{event.status}</Badge>
          </div>
          <p className="text-neutral-600">Owner: {event.owner}</p>
          <p className="text-neutral-600">Channels: {event.channels.join(", ")}</p>
        </div>
        <div className="flex gap-2 mt-3">
          <Link href={`/communications/${event.trackingId}`}>
            <Button size="sm">View Details</Button>
          </Link>
          <Button size="sm" variant="outline">Edit</Button>
        </div>
      </div>
    ), { duration: 5000 });
  }, []);

  const handleNavigate = useCallback((newDate: Date) => {
    setDate(newDate);
  }, []);

  const handleViewChange = useCallback((newView: View) => {
    setView(newView);
  }, []);

  // Custom event style getter
  const eventStyleGetter = useCallback((event: CommunicationEvent) => {
    let className = "";

    switch (event.priority) {
      case "URGENT":
        className = "rbc-event-urgent";
        break;
      case "HIGH":
        className = "rbc-event-high";
        break;
      case "MEDIUM":
        className = "rbc-event-medium";
        break;
      case "LOW":
        className = "rbc-event-low";
        break;
    }

    return { className };
  }, []);

  // Filter events based on selected filters
  const filteredEvents = useMemo(() => {
    return events.filter(event => {
      if (filters.type !== "ALL" && event.type !== filters.type) return false;
      if (filters.priority !== "ALL" && event.priority !== filters.priority) return false;
      if (filters.status !== "ALL" && event.status !== filters.status) return false;
      if (filters.channel !== "ALL" && !event.channels.includes(filters.channel)) return false;
      return true;
    });
  }, [events, filters]);

  // Custom toolbar component
  const CustomToolbar = useCallback((toolbar: any) => {
    const goToBack = () => {
      toolbar.onNavigate("PREV");
    };

    const goToNext = () => {
      toolbar.onNavigate("NEXT");
    };

    const goToToday = () => {
      toolbar.onNavigate("TODAY");
    };

    return (
      <div className="flex justify-between items-center mb-4 p-4 bg-white border rounded-lg">
        <div className="flex items-center space-x-2">
          <Button variant="outline" size="sm" onClick={goToBack}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={goToToday}>
            Today
          </Button>
          <Button variant="outline" size="sm" onClick={goToNext}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <span className="ml-4 text-lg font-semibold">
            {moment(toolbar.date).format("MMMM YYYY")}
          </span>
        </div>

        <div className="flex items-center space-x-2">
          <Button
            variant={view === "month" ? "default" : "outline"}
            size="sm"
            onClick={() => setView("month")}
          >
            <Grid3x3 className="h-4 w-4 mr-1" />
            Month
          </Button>
          <Button
            variant={view === "week" ? "default" : "outline"}
            size="sm"
            onClick={() => setView("week")}
          >
            <CalendarIcon className="h-4 w-4 mr-1" />
            Week
          </Button>
          <Button
            variant={view === "agenda" ? "default" : "outline"}
            size="sm"
            onClick={() => setView("agenda")}
          >
            <List className="h-4 w-4 mr-1" />
            Agenda
          </Button>
        </div>
      </div>
    );
  }, [view]);

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <Toaster position="top-right" />
      <style jsx global>{calendarStyles}</style>

      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold text-secondary-900">Communication Calendar</h1>
          <p className="text-neutral-600 mt-1">Plan and schedule your communications</p>
        </div>
        <div className="flex space-x-3">
          <Button variant="outline" onClick={() => setShowFilters(!showFilters)}>
            <Filter className="h-4 w-4 mr-2" />
            Filters
          </Button>
          <Button variant="outline">
            <Download className="h-4 w-4 mr-2" />
            Export
          </Button>
          <Button asChild>
            <Link href="/communications/new">
              <Plus className="h-4 w-4 mr-2" />
              New Communication
            </Link>
          </Button>
        </div>
      </div>

      {/* Filters */}
      {showFilters && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Filters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-4 gap-4">
              <div>
                <label className="block text-sm font-medium mb-2">Type</label>
                <select
                  value={filters.type}
                  onChange={(e) => setFilters({ ...filters, type: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                >
                  <option value="ALL">All Types</option>
                  <option value="ANNOUNCEMENT">Announcement</option>
                  <option value="UPDATE">Update</option>
                  <option value="NEWSLETTER">Newsletter</option>
                  <option value="ALERT">Alert</option>
                  <option value="EVENT">Event</option>
                  <option value="POLICY">Policy</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Priority</label>
                <select
                  value={filters.priority}
                  onChange={(e) => setFilters({ ...filters, priority: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                >
                  <option value="ALL">All Priorities</option>
                  <option value="URGENT">Urgent</option>
                  <option value="HIGH">High</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="LOW">Low</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Status</label>
                <select
                  value={filters.status}
                  onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                >
                  <option value="ALL">All Statuses</option>
                  <option value="DRAFT">Draft</option>
                  <option value="REVIEW">Review</option>
                  <option value="APPROVED">Approved</option>
                  <option value="SCHEDULED">Scheduled</option>
                  <option value="PUBLISHED">Published</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Channel</label>
                <select
                  value={filters.channel}
                  onChange={(e) => setFilters({ ...filters, channel: e.target.value })}
                  className="w-full px-3 py-2 border rounded-md"
                >
                  <option value="ALL">All Channels</option>
                  <option value="EMAIL">Email</option>
                  <option value="INTRANET">Intranet</option>
                  <option value="TEAMS">Teams</option>
                  <option value="SMS">SMS</option>
                  <option value="DIGITAL_SIGNAGE">Digital Signage</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end mt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFilters({ type: "ALL", priority: "ALL", status: "ALL", channel: "ALL" })}
              >
                Clear Filters
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Calendar */}
      <Card>
        <CardContent className="p-0">
          <div style={{ height: 600 }}>
            <Calendar
              localizer={localizer}
              events={filteredEvents}
              startAccessor="start"
              endAccessor="end"
              style={{ height: "100%" }}
              onSelectEvent={handleSelectEvent}
              onNavigate={handleNavigate}
              view={view}
              onView={handleViewChange}
              date={date}
              eventPropGetter={eventStyleGetter}
              components={{
                toolbar: CustomToolbar,
              }}
              views={["month", "week", "agenda"]}
            />
          </div>
        </CardContent>
      </Card>

      {/* Legend */}
      <div className="mt-4 p-4 bg-white border rounded-lg">
        <p className="text-sm font-medium mb-2">Priority Legend:</p>
        <div className="flex space-x-4">
          <div className="flex items-center">
            <div className="w-4 h-4 bg-[#8A000A] rounded mr-2"></div>
            <span className="text-sm">Urgent</span>
          </div>
          <div className="flex items-center">
            <div className="w-4 h-4 bg-[#e60000] rounded mr-2"></div>
            <span className="text-sm">High</span>
          </div>
          <div className="flex items-center">
            <div className="w-4 h-4 bg-[#E4A911] rounded mr-2"></div>
            <span className="text-sm">Medium</span>
          </div>
          <div className="flex items-center">
            <div className="w-4 h-4 bg-[#B8B3A2] rounded mr-2"></div>
            <span className="text-sm">Low</span>
          </div>
        </div>
      </div>
    </div>
  );
}