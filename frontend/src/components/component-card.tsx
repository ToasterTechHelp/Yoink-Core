"use client";

import { useRef, useState, type DragEvent } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ComponentData } from "@/lib/api";

interface ComponentCardProps {
  component: ComponentData;
}

export function ComponentCard({ component }: ComponentCardProps) {
  const [copied, setCopied] = useState(false);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const noSelectClasses =
    "select-none [-webkit-touch-callout:none] [-webkit-user-select:none]";

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

  const handleDragStart = (event: DragEvent<HTMLDivElement>) => {
    const dt = event.dataTransfer;
    dt.effectAllowed = "copy";
    dt.setData("text/plain", component.url);
    dt.setData("text/uri-list", component.url);
    dt.setData("text/html", `<img src="${component.url}" alt="component image">`);

    if (imageRef.current) {
      dt.setDragImage(
        imageRef.current,
        imageRef.current.width / 2,
        imageRef.current.height / 2
      );
    }
  };

  return (
    <div
      className={`relative w-fit max-w-sm overflow-hidden rounded-xl border bg-card ${noSelectClasses}`}
    >
      {/* Image — draggable with real src for iPad native drag */}
      <div className="relative flex justify-center p-2">
        <img
          ref={imageRef}
          src={component.url}
          alt={`${component.category} component`}
          className={`w-full object-contain pointer-events-none [-webkit-user-drag:none] ${noSelectClasses}`}
          draggable={false}
        />
        <div
          className={`absolute inset-2 z-10 cursor-grab active:cursor-grabbing touch-none ${noSelectClasses}`}
          draggable
          onDragStart={handleDragStart}
          onContextMenu={(event) => event.preventDefault()}
          aria-label={`Drag ${component.category} component`}
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
