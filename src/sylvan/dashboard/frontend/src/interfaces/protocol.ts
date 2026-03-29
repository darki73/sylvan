export interface DashboardRequest {
    id: string;
    type: string;
    args?: Record<string, unknown>;
}

export interface DashboardResponse {
    id?: string;
    type: string;
    data?: unknown;
    error?: string;
}

export type RequestHandler = (data: unknown) => void;
export type PushHandler = (data: unknown) => void;
