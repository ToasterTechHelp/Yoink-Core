"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { renameUpload } from "@/lib/api";
import type { SupabaseJob } from "@/store/useYoinkStore";

const MAX_BASE_NAME_LENGTH = 120;
const INVALID_BASE_NAME_PATTERN = /[\\/\x00-\x1f\x7f]/;

function splitTitle(title: string): { baseName: string; extension: string } {
  const dotIndex = title.lastIndexOf(".");
  if (dotIndex <= 0) {
    return { baseName: title, extension: "" };
  }
  return {
    baseName: title.slice(0, dotIndex),
    extension: title.slice(dotIndex),
  };
}

interface RenameUploadDialogProps {
  open: boolean;
  job: SupabaseJob | null;
  onClose: () => void;
  onRenamed: (jobId: string, title: string) => void;
  getAccessToken: () => Promise<string | undefined>;
}

export function RenameUploadDialog({
  open,
  job,
  onClose,
  onRenamed,
  getAccessToken,
}: RenameUploadDialogProps) {
  const [baseName, setBaseName] = useState("");
  const [extension, setExtension] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !job) return;
    const titleParts = splitTitle(job.title);
    setBaseName(titleParts.baseName);
    setExtension(titleParts.extension);
  }, [open, job]);

  const handleClose = () => {
    if (loading) return;
    onClose();
  };

  const handleSubmit = async () => {
    if (!job) return;

    const cleaned = baseName.trim();
    if (!cleaned) {
      toast.error("Name cannot be empty");
      return;
    }
    if (cleaned.length > MAX_BASE_NAME_LENGTH) {
      toast.error(`Name must be at most ${MAX_BASE_NAME_LENGTH} characters`);
      return;
    }
    if (INVALID_BASE_NAME_PATTERN.test(cleaned)) {
      toast.error("Name cannot contain slashes or control characters");
      return;
    }

    setLoading(true);
    try {
      const token = await getAccessToken();
      if (!token) {
        throw new Error("Authentication required");
      }

      const result = await renameUpload(job.id, cleaned, token);
      onRenamed(job.id, result.title);
      toast.success("Upload renamed");
      onClose();
    } catch (err: any) {
      toast.error(err.message || "Failed to rename upload");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) handleClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename upload</DialogTitle>
          <DialogDescription>
            Update the upload name. The file extension stays {extension || "unchanged"}.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <label htmlFor="rename-upload-name" className="text-sm font-medium">
            Upload name
          </label>
          <div className="flex items-center gap-2">
            <input
              id="rename-upload-name"
              value={baseName}
              onChange={(e) => setBaseName(e.target.value)}
              maxLength={MAX_BASE_NAME_LENGTH}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              placeholder="New name"
              disabled={loading}
            />
            {extension && <span className="shrink-0 text-sm text-muted-foreground">{extension}</span>}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={loading}>
            {loading ? "Renaming..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
