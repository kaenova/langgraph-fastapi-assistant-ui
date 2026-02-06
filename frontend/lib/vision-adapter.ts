"use client";

import {
  AttachmentAdapter,
  CompleteAttachment,
  PendingAttachment,
} from "@assistant-ui/react";

const BaseAPIPath = "/api/be";

export class VisionImageAdapter implements AttachmentAdapter {
  accept = "image/jpeg,image/png,image/webp";

  async add({ file }: { file: File }): Promise<PendingAttachment> {
    // Validate file size (e.g., 20MB limit for most LLMs)
    const maxSize = 20 * 1024 * 1024; // 20MB
    if (file.size > maxSize) {
      throw new Error("Image size exceeds 20MB limit");
    }
    // Return pending attachment while processing
    return {
      id: crypto.randomUUID(),
      type: "image",
      name: file.name,
      contentType: file.type,
      file,
      status: {
        type: "running",
        reason: "uploading",
        progress: 0,
      },
    };
  }

  async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
    try {
      // Upload image to backend
      const formData = new FormData();
      formData.append("file", attachment.file);
      formData.append("type", "image");

      const response = await fetch(`${BaseAPIPath}/api/v1/attachments`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Failed to upload attachment: ${response.statusText}`);
      }

      const data = await response.json();

      // Return in assistant-ui format with chatbot:// URL
      return {
        id: attachment.id,
        type: "image",
        name: attachment.name,
        contentType: attachment.contentType || "image/jpeg",
        content: [
          {
            type: "image",
            image: data.url, // chatbot://{id} format from backend
          },
        ],
        status: { type: "complete" },
      };
    } catch (error) {
      console.error("Error uploading attachment:", error);
      throw error;
    }
  }

  async remove(_attachment: PendingAttachment): Promise<void> {
    // Cleanup if needed (e.g., delete from backend)
    // Could implement DELETE request to backend if needed
  }
}
