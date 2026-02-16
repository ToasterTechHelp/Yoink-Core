const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export interface JobStatus {
  job_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  filename: string;
  progress: { current_page: number; total_pages: number };
  error: string | null;
  created_at: string;
}

export interface ComponentData {
  id: number;
  page_number: number;
  category: string;
  original_label: string;
  confidence: number;
  bbox: number[];
  url: string;
}

export interface GuestResult {
  source_file: string;
  total_pages: number;
  total_components: number;
  components: ComponentData[];
}

export interface UserResultMeta {
  source_file: string;
  total_pages: number;
  total_components: number;
  is_guest: boolean;
}

export async function uploadFile(
  file: File,
  token?: string
): Promise<{ job_id: string; status: string }> {
  const formData = new FormData();
  formData.append("file", file);

  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}/api/v1/extract`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Upload failed");
  }

  return res.json();
}

export async function pollJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_URL}/api/v1/jobs/${jobId}`);
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to get job status");
  }
  return res.json();
}

export async function getJobResult(
  jobId: string
): Promise<GuestResult | UserResultMeta> {
  const res = await fetch(`${API_URL}/api/v1/jobs/${jobId}/result`);
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to get result");
  }
  return res.json();
}

export async function deleteJob(jobId: string, token: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/v1/jobs/${jobId}`, {
    method: "DELETE",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok && res.status !== 204) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to delete job");
  }
}

export async function renameUpload(
  jobId: string,
  baseName: string,
  token: string
): Promise<{ job_id: string; title: string }> {
  const res = await fetch(`${API_URL}/api/v1/jobs/${jobId}/rename`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ base_name: baseName }),
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to rename upload");
  }

  return res.json();
}

export async function submitFeedback(
  jobId: string,
  type: "bug" | "content_violation",
  message?: string
): Promise<void> {
  const res = await fetch(`${API_URL}/api/v1/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId, type, message }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to submit feedback");
  }
}
