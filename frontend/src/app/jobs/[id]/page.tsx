"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { ArrowLeft, Flag } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ComponentCard } from "@/components/component-card";
import { CategoryFilter } from "@/components/category-filter";
import { PageJump } from "@/components/page-jump";
import { createClient } from "@/lib/supabase/client";
import { useYoinkStore } from "@/store/useYoinkStore";
import { submitFeedback, getJobResult, buildTransparentRenderUrl } from "@/lib/api";
import type { ComponentData } from "@/lib/api";
import type { SupabaseJob } from "@/store/useYoinkStore";

function componentKey(component: ComponentData): string {
  return `${component.page_number}:${component.id}`;
}

export default function ResultsPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const jobId = params.id as string;
  const isGuest = searchParams.get("guest") === "true";

  const supabase = useMemo(() => createClient(), []);
  const guestResult = useYoinkStore((s) => s.guestResult);
  const user = useYoinkStore((s) => s.user);

  const [components, setComponents] = useState<ComponentData[]>([]);
  const [sourceFile, setSourceFile] = useState("");
  const [totalComponents, setTotalComponents] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [activeCategories, setActiveCategories] = useState<Set<string>>(
    new Set()
  );
  const [isGlobalTransparent, setIsGlobalTransparent] = useState(false);
  const [transparentModeByKey, setTransparentModeByKey] = useState<
    Record<string, boolean>
  >({});

  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  useEffect(() => {
    setIsGlobalTransparent(false);
    setTransparentModeByKey({});
  }, [jobId]);

  // Load data
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);

      if (isGuest && guestResult && guestResult.jobId === jobId) {
        // Guest — use Zustand store
        setComponents(guestResult.components);
        setSourceFile(guestResult.sourceFile);
        setTotalComponents(guestResult.totalComponents);
        setTotalPages(guestResult.totalPages);

        const cats = new Set(guestResult.components.map((c) => c.category));
        setActiveCategories(cats);
        setLoading(false);
        return;
      }

      if (isGuest) {
        try {
          const data = await getJobResult(jobId);
          if ("components" in data) {
            setComponents(data.components);
            setSourceFile(data.source_file);
            setTotalComponents(data.total_components);
            setTotalPages(data.total_pages);

            const cats = new Set(data.components.map((c) => c.category));
            setActiveCategories(cats);
          } else {
            toast.error("Guest job not found");
            router.push("/");
            return;
          }
        } catch (error) {
          console.error(error);
          toast.error("Failed to load guest job");
          router.push("/");
          return;
        }

        setLoading(false);
        return;
      }

      if (!isGuest && user && supabase) {
        // Authenticated — load from Supabase
        const { data, error } = await supabase
          .from("jobs")
          .select("*")
          .eq("id", jobId)
          .single();

        if (error || !data) {
          toast.error("Job not found");
          router.push("/");
          return;
        }

        const job = data as SupabaseJob;
        const comps = job.results?.components ?? [];
        setComponents(comps);
        setSourceFile(job.title);
        setTotalComponents(job.total_components);
        setTotalPages(job.total_pages);

        const cats = new Set(comps.map((c) => c.category));
        setActiveCategories(cats);
        setLoading(false);
        return;
      }

      // Fallback — no data
      setLoading(false);
    };

    loadData();
  }, [jobId, isGuest, guestResult, user, supabase, router]);

  // Derive unique categories
  const allCategories = useMemo(() => {
    return [...new Set(components.map((c) => c.category))];
  }, [components]);

  // Filter components
  const filtered = useMemo(() => {
    if (activeCategories.size === 0) return components;
    return components.filter((c) => activeCategories.has(c.category));
  }, [components, activeCategories]);

  // Group by page
  const grouped = useMemo(() => {
    const map = new Map<number, ComponentData[]>();
    for (const c of filtered) {
      const arr = map.get(c.page_number) || [];
      arr.push(c);
      map.set(c.page_number, arr);
    }
    return [...map.entries()].sort(([a], [b]) => a - b);
  }, [filtered]);

  const visiblePages = useMemo(() => {
    return grouped.map(([pageNum]) => pageNum);
  }, [grouped]);

  const handleJump = (page: number) => {
    const el = pageRefs.current.get(page);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const handleReport = async () => {
    try {
      await submitFeedback(jobId, "bug");
      toast.success("Report submitted. Thank you!");
    } catch {
      toast.error("Failed to submit report");
    }
  };

  const handleGlobalTransparentToggle = () => {
    setIsGlobalTransparent((prev) => !prev);
    setTransparentModeByKey({});
  };

  if (loading) {
    return (
      <div className="flex h-[60dvh] items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading results...</p>
      </div>
    );
  }

  if (components.length === 0) {
    return (
      <div className="flex h-[60dvh] flex-col items-center justify-center gap-2">
        <p className="text-sm text-muted-foreground">No components found.</p>
        <Button variant="ghost" size="sm" onClick={() => router.push("/")}>
          <ArrowLeft className="mr-1 h-4 w-4" /> Back home
        </Button>
      </div>
    );
  }

  return (
    <div className="pb-20">
      {/* Header */}
      <div className="sticky top-14 z-30 border-b bg-background/95 backdrop-blur">
        <div className="container mx-auto flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3 min-w-0">
            <Button
              variant="ghost"
              size="icon"
              className="shrink-0"
              onClick={() => router.push("/")}
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{sourceFile}</p>
              <p className="text-xs text-muted-foreground">
                {totalComponents} components extracted
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleGlobalTransparentToggle}
            >
              Transparent: {isGlobalTransparent ? "On" : "Off"}
            </Button>
            <Button variant="outline" size="sm" onClick={handleReport}>
              <Flag className="mr-1 h-3.5 w-3.5" />
              <span className="hidden sm:inline">Report a problem</span>
            </Button>
          </div>
        </div>

        {/* Category filters */}
        <div className="container mx-auto px-4 pb-3">
          <CategoryFilter
            categories={allCategories}
            active={activeCategories}
            onChange={setActiveCategories}
          />
        </div>
      </div>

      {/* Component grid */}
      <div className="container mx-auto px-4 pt-4">
        {grouped.map(([pageNum, comps]) => (
          <div
            key={pageNum}
            ref={(el) => {
              if (el) pageRefs.current.set(pageNum, el);
            }}
            className="mb-8"
          >
            <div className="mb-3 flex items-center gap-2">
              <span className="rounded-md bg-muted px-2.5 py-1 text-xs font-semibold">
                Page {pageNum}
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>

            {/* Flex-wrap: cards size to their content */}
            <div className="flex flex-wrap items-start gap-4">
              {comps.map((comp) => {
                const key = componentKey(comp);
                const isTransparent = transparentModeByKey[key] ?? isGlobalTransparent;
                const imageUrl = isTransparent
                  ? buildTransparentRenderUrl(comp.url)
                  : comp.url;

                return (
                  <ComponentCard
                    key={key}
                    component={comp}
                    imageUrl={imageUrl}
                    isTransparent={isTransparent}
                    onToggleTransparent={() =>
                      setTransparentModeByKey((prev) => {
                        const current = prev[key] ?? isGlobalTransparent;
                        return {
                          ...prev,
                          [key]: !current,
                        };
                      })
                    }
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Page jump */}
      <PageJump pages={visiblePages} onJump={handleJump} />
    </div>
  );
}
