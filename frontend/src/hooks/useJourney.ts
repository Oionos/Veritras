import { useQuery } from "@tanstack/react-query";
import { fetchApi } from "./useApi";
import type { Shipment } from "@/types";
import type { components } from "@/types/api";

export function useShipment(id: string) {
  return useQuery<Shipment>({
    queryKey: ["shipment", id],
    queryFn: ({ signal }) => fetchApi(`/shipments/${encodeURIComponent(id)}`, { signal }),
    enabled: !!id,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
}

export function useTimeline(id: string, page: number) {
  return useQuery<components["schemas"]["TimelineResponse"]>({
    queryKey: ["timeline", id, page],
    queryFn: ({ signal }) =>
      fetchApi(
        `/products/${encodeURIComponent(id)}/timeline?skip=${page * 100}&limit=100`,
        { signal },
      ),
    enabled: !!id,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
}
