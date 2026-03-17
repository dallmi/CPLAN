"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  Save,
  Send,
  Calendar,
  Users,
  FileText,
  Hash,
  AlertCircle,
  Sparkles,
  Copy,
  Check,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { generateTrackingId } from "@/lib/utils";
import toast, { Toaster } from "react-hot-toast";

const communicationSchema = z.object({
  title: z.string().min(1, "Title is required").max(200),
  description: z.string().optional(),
  type: z.enum(["ANNOUNCEMENT", "UPDATE", "NEWSLETTER", "ALERT", "EVENT", "POLICY", "OTHER"]),
  priority: z.enum(["LOW", "MEDIUM", "HIGH", "URGENT"]),
  content: z.string().min(1, "Content is required"),
  channels: z.array(z.string()).min(1, "Select at least one channel"),
  publishDate: z.string().optional(),
  expiryDate: z.string().optional(),
  templateId: z.string().optional(),
  tags: z.array(z.string()).optional(),
});

type CommunicationForm = z.infer<typeof communicationSchema>;

const channelOptions = [
  { id: "EMAIL", label: "Email", icon: "📧" },
  { id: "INTRANET", label: "Intranet", icon: "🌐" },
  { id: "TEAMS", label: "Microsoft Teams", icon: "💬" },
  { id: "SLACK", label: "Slack", icon: "💼" },
  { id: "SMS", label: "SMS", icon: "📱" },
  { id: "MOBILE_APP", label: "Mobile App", icon: "📲" },
  { id: "DIGITAL_SIGNAGE", label: "Digital Signage", icon: "📺" },
  { id: "SOCIAL", label: "Social", icon: "🔗" },
];

export default function NewCommunicationPage() {
  const router = useRouter();
  const [trackingId, setTrackingId] = useState("");
  const [copied, setCopied] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<CommunicationForm>({
    resolver: zodResolver(communicationSchema),
    defaultValues: {
      type: "ANNOUNCEMENT",
      priority: "MEDIUM",
      channels: [],
    },
  });

  useEffect(() => {
    // Generate tracking ID on mount
    setTrackingId(generateTrackingId());
  }, []);

  const copyTrackingId = () => {
    navigator.clipboard.writeText(trackingId);
    setCopied(true);
    toast.success("Tracking ID copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const toggleChannel = (channelId: string) => {
    const newChannels = selectedChannels.includes(channelId)
      ? selectedChannels.filter(c => c !== channelId)
      : [...selectedChannels, channelId];

    setSelectedChannels(newChannels);
    setValue("channels", newChannels);
  };

  const onSubmit = async (data: CommunicationForm) => {
    try {
      // API call would go here
      console.log("Submitting:", { ...data, trackingId });

      toast.success("Communication created successfully!");
      setTimeout(() => {
        router.push(`/communications/${trackingId}`);
      }, 1500);
    } catch (error) {
      toast.error("Failed to create communication");
    }
  };

  const handleAISuggestions = async () => {
    setAiSuggesting(true);
    // Simulate AI processing
    setTimeout(() => {
      toast.success("AI suggestions applied to your content");
      setAiSuggesting(false);
    }, 2000);
  };

  const watchType = watch("type");
  const watchPriority = watch("priority");

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <Toaster position="top-right" />

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-secondary-900">Create New Communication</h1>
        <p className="text-neutral-600 mt-2">Plan and schedule your internal communication</p>
      </div>

      {/* Tracking ID Card */}
      <Card className="mb-6 border-primary/20 bg-primary/5">
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <Hash className="h-5 w-5 text-primary" />
              <div>
                <p className="text-sm text-neutral-600">Tracking ID</p>
                <p className="font-mono text-lg font-bold text-primary">{trackingId}</p>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={copyTrackingId}
              className="ml-4"
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              {copied ? "Copied!" : "Copy ID"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {/* Basic Information */}
        <Card>
          <CardHeader>
            <CardTitle>Basic Information</CardTitle>
            <CardDescription>Define the core details of your communication</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Title *</label>
              <input
                {...register("title")}
                className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder="Enter communication title"
              />
              {errors.title && (
                <p className="text-error-500 text-sm mt-1">{errors.title.message}</p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Description</label>
              <textarea
                {...register("description")}
                rows={3}
                className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder="Brief description of the communication"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-2">Type *</label>
                <select
                  {...register("type")}
                  className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value="ANNOUNCEMENT">Announcement</option>
                  <option value="UPDATE">Update</option>
                  <option value="NEWSLETTER">Newsletter</option>
                  <option value="ALERT">Alert</option>
                  <option value="EVENT">Event</option>
                  <option value="POLICY">Policy</option>
                  <option value="OTHER">Other</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">Priority *</label>
                <select
                  {...register("priority")}
                  className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value="LOW">Low</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="HIGH">High</option>
                  <option value="URGENT">Urgent</option>
                </select>
              </div>
            </div>

            {/* Display current selections */}
            <div className="flex items-center space-x-2 pt-2">
              <Badge variant="outline">{watchType}</Badge>
              <Badge variant={watchPriority === "URGENT" || watchPriority === "HIGH" ? "destructive" : watchPriority === "MEDIUM" ? "warning" : "secondary"}>
                {watchPriority} Priority
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Content */}
        <Card>
          <CardHeader>
            <CardTitle>Content</CardTitle>
            <CardDescription>Compose your communication message</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="block text-sm font-medium">Message Content *</label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleAISuggestions}
                  disabled={aiSuggesting}
                >
                  <Sparkles className="h-4 w-4 mr-2" />
                  {aiSuggesting ? "Generating..." : "AI Suggestions"}
                </Button>
              </div>
              <textarea
                {...register("content")}
                rows={10}
                className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
                placeholder="Enter your communication content here..."
              />
              {errors.content && (
                <p className="text-error-500 text-sm mt-1">{errors.content.message}</p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Distribution Channels */}
        <Card>
          <CardHeader>
            <CardTitle>Distribution Channels</CardTitle>
            <CardDescription>Select where this communication will be published</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {channelOptions.map((channel) => (
                <button
                  key={channel.id}
                  type="button"
                  onClick={() => toggleChannel(channel.id)}
                  className={`p-3 border rounded-lg text-center transition-all ${
                    selectedChannels.includes(channel.id)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-neutral-300 hover:border-neutral-400"
                  }`}
                >
                  <div className="text-2xl mb-1">{channel.icon}</div>
                  <div className="text-sm font-medium">{channel.label}</div>
                </button>
              ))}
            </div>
            {errors.channels && (
              <p className="text-error-500 text-sm mt-2">{errors.channels.message}</p>
            )}
          </CardContent>
        </Card>

        {/* Scheduling */}
        <Card>
          <CardHeader>
            <CardTitle>Scheduling</CardTitle>
            <CardDescription>Set publish and expiry dates for your communication</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-2">Publish Date</label>
                <input
                  type="datetime-local"
                  {...register("publishDate")}
                  className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Expiry Date</label>
                <input
                  type="datetime-local"
                  {...register("expiryDate")}
                  className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Action Buttons */}
        <div className="flex justify-between items-center pt-4">
          <Button
            type="button"
            variant="outline"
            onClick={() => router.back()}
          >
            Cancel
          </Button>
          <div className="flex space-x-3">
            <Button
              type="submit"
              variant="outline"
              disabled={isSubmitting}
            >
              <Save className="h-4 w-4 mr-2" />
              Save as Draft
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting}
            >
              <Send className="h-4 w-4 mr-2" />
              {isSubmitting ? "Creating..." : "Create & Continue"}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}