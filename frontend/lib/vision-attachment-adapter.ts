"use client";

import type { Attachment, CompleteAttachment, PendingAttachment } from "@assistant-ui/react";

const MAX_VISION_IMAGE_SIZE_BYTES = 12 * 1024 * 1024;
const MAX_VISION_IMAGE_DATA_URL_CHARS = 2_000_000;
const MAX_VISION_IMAGE_DIMENSION = 1280;
const MIN_QUALITY = 0.45;
const INITIAL_QUALITY = 0.85;
const SCALE_STEP = 0.85;
const MAX_COMPRESSION_ATTEMPTS = 8;

const fileToDataUrl = async (file: File): Promise<string> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () =>
      reject(reader.error ?? new Error("Failed to read attachment"));
    reader.readAsDataURL(file);
  });
};

const loadImage = async (file: File): Promise<HTMLImageElement> => {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Failed to decode image attachment."));
    };
    image.src = url;
  });
};

const toVisionDataUrl = async (file: File): Promise<string> => {
  const image = await loadImage(file);
  let width = image.naturalWidth;
  let height = image.naturalHeight;
  const maxDimension = Math.max(width, height);
  if (maxDimension > MAX_VISION_IMAGE_DIMENSION) {
    const scale = MAX_VISION_IMAGE_DIMENSION / maxDimension;
    width = Math.max(1, Math.floor(width * scale));
    height = Math.max(1, Math.floor(height * scale));
  }

  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Unable to process image attachment.");
  }

  let quality = INITIAL_QUALITY;
  for (let attempt = 0; attempt < MAX_COMPRESSION_ATTEMPTS; attempt += 1) {
    canvas.width = width;
    canvas.height = height;
    context.clearRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);
    const dataUrl = canvas.toDataURL("image/jpeg", quality);
    if (dataUrl.length <= MAX_VISION_IMAGE_DATA_URL_CHARS) {
      return dataUrl;
    }

    quality = Math.max(MIN_QUALITY, quality - 0.08);
    width = Math.max(1, Math.floor(width * SCALE_STEP));
    height = Math.max(1, Math.floor(height * SCALE_STEP));
  }

  throw new Error(
    "Image is too large after compression. Please upload a smaller image.",
  );
};

export const visionImageAttachmentAdapter = {
  accept: "image/jpeg,image/png,image/webp,image/gif",
  async add({ file }: { file: File }): Promise<PendingAttachment> {
    if (!file.type.startsWith("image/")) {
      throw new Error("Only image attachments are supported.");
    }
    if (file.size > MAX_VISION_IMAGE_SIZE_BYTES) {
      throw new Error("Image size exceeds 20MB limit.");
    }

    return {
      id: crypto.randomUUID(),
      type: "image",
      name: file.name,
      contentType: file.type,
      file,
      status: { type: "running", reason: "uploading", progress: 0 },
    };
  },
  async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
    const imageDataUrl =
      attachment.file.size <= 512 * 1024
        ? await fileToDataUrl(attachment.file)
        : await toVisionDataUrl(attachment.file);
    if (imageDataUrl.length > MAX_VISION_IMAGE_DATA_URL_CHARS) {
      throw new Error(
        "Image is too large for the model request. Please use a smaller image.",
      );
    }
    const dataUrlHeader = imageDataUrl.slice(0, imageDataUrl.indexOf(";"));
    const contentType = dataUrlHeader.startsWith("data:")
      ? dataUrlHeader.slice(5)
      : attachment.contentType;
    return {
      id: attachment.id,
      type: "image",
      name: attachment.name,
      contentType,
      content: [
        {
          type: "image",
          image: imageDataUrl,
          filename: attachment.name,
        },
      ],
      status: { type: "complete" },
    };
  },
  async remove(_attachment: Attachment): Promise<void> {
    return;
  },
};
