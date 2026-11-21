
import { apiRequest } from "./client";

const ENDPOINT = "/scheduledEvents";

export function getScheduledEvents() {
  return apiRequest(ENDPOINT);
}

export function createScheduledEvent(event) {
  return apiRequest(ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(event),
  });
}

export function deleteScheduledEvent(id) {
  return apiRequest(
    `${ENDPOINT}/${encodeURIComponent(id)}`,
    { method: "DELETE" }
  );
}
