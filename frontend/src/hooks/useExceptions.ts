import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "./useApi";
import type { components } from "@/types/api";

export type ExceptionList = components["schemas"]["ExceptionList"];
export type ShipmentException = components["schemas"]["ExceptionResponse"];
export type Policy = components["schemas"]["PolicyResponse"];
export type PolicyUpdate = components["schemas"]["PolicyUpdate"];
export type ExceptionState =
  "open" | "unacknowledged" | "acknowledged" | "resolved" | "all";

export function useExceptions(
  state: ExceptionState = "open",
  page = 0,
  shipmentId?: string,
) {
  const query = new URLSearchParams({
    state,
    skip: String(page * 20),
    limit: "20",
  });
  if (shipmentId) query.set("shipment_id", shipmentId);
  return useQuery<ExceptionList>({
    queryKey: ["exceptions", state, page, shipmentId],
    queryFn: ({ signal }) => fetchApi(`/exceptions?${query}`, { signal }),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

export function useExceptionPolicy(shipmentId: string) {
  return useQuery<Policy>({
    queryKey: ["exception-policy", shipmentId],
    queryFn: ({ signal }) =>
      fetchApi(`/exceptions/policies/${encodeURIComponent(shipmentId)}`, { signal }),
    enabled: !!shipmentId,
  });
}

export function useSaveExceptionPolicy(shipmentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: PolicyUpdate) =>
      fetchApi(`/exceptions/policies/${encodeURIComponent(shipmentId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void client.invalidateQueries({
        queryKey: ["exception-policy", shipmentId],
      });
      void client.invalidateQueries({ queryKey: ["exceptions"] });
    },
  });
}

export function useAcknowledgeException() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      fetchApi(`/exceptions/${encodeURIComponent(id)}/acknowledgement`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: note || null }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["exceptions"] });
    },
  });
}
