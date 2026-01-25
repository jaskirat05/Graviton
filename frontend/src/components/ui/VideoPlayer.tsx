"use client";

/**
 * VideoPlayer - Video player using Mux
 */

import MuxVideo from "@mux/mux-video-react";

interface VideoPlayerProps {
  url: string;
  className?: string;
}

export function VideoPlayer({ url, className = "" }: VideoPlayerProps) {
  return (
    <div className={`relative overflow-hidden bg-black ${className}`}>
      <MuxVideo
        src={url}
        controls
        muted
        playsInline
        preload="metadata"
        style={{ width: "100%", height: "100%", objectFit: "contain" }}
      />
    </div>
  );
}
