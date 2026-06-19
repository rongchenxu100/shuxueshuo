import {
  UploadJobProgressEventSchema,
  type UploadJobProgressEvent,
} from "../contracts";

export function parseUploadJobEvent(
  eventName: string,
  data: string,
): UploadJobProgressEvent {
  const payload = JSON.parse(data) as unknown;

  if (typeof payload === "object" && payload !== null && "type" in payload) {
    return UploadJobProgressEventSchema.parse(payload);
  }

  return UploadJobProgressEventSchema.parse({
    ...(payload as object),
    type: eventName,
  });
}

export function formatSseEvent(eventName: string, data: unknown): string {
  return `event: ${eventName}\ndata: ${JSON.stringify(data)}\n\n`;
}
