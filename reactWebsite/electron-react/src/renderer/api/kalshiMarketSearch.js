
import { apiRequest } from "./client";

const ENDPOINT = "/kalshiMarketSearch";

export function getKalshiMarketSearch(query) {
  return apiRequest(ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(query),
  });
}
