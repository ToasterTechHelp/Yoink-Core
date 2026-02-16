"use client";

import { formatDistanceToNow } from "date-fns";
import { ExternalLink, MoreVertical, Trash2, FileText, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { SupabaseJob } from "@/store/useYoinkStore";

interface JobCardProps {
  job: SupabaseJob;
  onOpen: (jobId: string) => void;
  onRename: (job: SupabaseJob) => void;
  onDelete: (jobId: string) => void;
}

export function JobCard({ job, onOpen, onRename, onDelete }: JobCardProps) {
  const timeAgo = formatDistanceToNow(new Date(job.created_at), {
    addSuffix: true,
  });

  return (
    <div className="flex items-center gap-3 rounded-xl border p-3 transition-colors hover:bg-muted/50">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
        <FileText className="h-5 w-5 text-muted-foreground" />
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{job.title}</p>
        <p className="text-xs text-muted-foreground">{timeAgo}</p>
        <p className="text-xs text-orange-500">
          {job.total_pages} pages | {job.total_components} components
        </p>
      </div>

      <Button
        variant="ghost"
        size="icon"
        className="shrink-0"
        onClick={() => onOpen(job.id)}
      >
        <ExternalLink className="h-4 w-4" />
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="shrink-0">
            <MoreVertical className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => onRename(job)}>
            <Pencil className="mr-2 h-4 w-4" />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem
            className="text-destructive"
            onClick={() => onDelete(job.id)}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
