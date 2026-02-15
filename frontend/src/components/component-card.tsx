"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ComponentData } from "@/lib/api";

interface ComponentCardProps {
  component: ComponentData;
}

export function ComponentCard({ component }: ComponentCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    const imgPromise = fetch(component.url, {
      mode: "cors",
      cache: "no-store",
    }).then(async (response) => {
      if (!response.ok) throw new Error("Network error");
      const blob = await response.blob();
      return new Blob([blob], { type: "image/png" });
    });

    const item = new ClipboardItem({ "image/png": imgPromise });
    navigator.clipboard
      .write([item])
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      })
      .catch((err) => {
        console.error("Clipboard write failed:", err);
        window.open(component.url, "_blank");
      });
  };

  const isText = component.category === "text";

  return (
    <div className="relative w-fit max-w-sm overflow-hidden rounded-xl border bg-card">
      {/* Image — draggable with real src for iPad native drag */}
      <div className="relative flex justify-center p-2">
        <img
          src={component.url}
          alt={`${component.category} component`}
          className="w-full object-contain"
          draggable
          style={{ pointerEvents: "auto" }}
        />
      </div>

      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {component.category}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
          onClick={handleCopy}
          aria-label="Copy component image"
        >
          {copied ? (
            <Check className="h-4 w-4 text-green-500" />
          ) : (
            <Copy className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  );
}
